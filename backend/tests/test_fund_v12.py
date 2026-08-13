"""V1.2 基金回测完善测试：赎回费阶梯（持有期分档）+ 分笔 FIFO、基金分红、价值平均定投。

所有净值/盈亏断言基于手工核算，防止口径回归。
"""

from __future__ import annotations

import datetime as dt
from typing import List, Tuple

import pytest

from app.backtest import (
    BacktestEngine,
    FundAccount,
    FundValueAvgStrategy,
    Strategy,
    build_report,
)
from app.backtest.costs import CostRates, resolve_redemption_fee_rate
from app.market import Bar, Instrument


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def make_nav_bars(
    closes: List[float], symbol: str = "FUND.X", volume: float = 0.0
) -> List[Bar]:
    base = dt.date(2024, 1, 2)
    return [
        Bar(
            symbol=symbol,
            date=(base + dt.timedelta(days=i)).isoformat(),
            open=float(c), high=float(c), low=float(c), close=float(c),
            volume=volume,
        )
        for i, c in enumerate(closes)
    ]


def make_nav_bars_dates(dates_closes: List[Tuple[str, float]], symbol: str = "FUND.X") -> List[Bar]:
    return [
        Bar(
            symbol=symbol, date=d, open=float(c), high=float(c),
            low=float(c), close=float(c), volume=0.0,
        )
        for d, c in dates_closes
    ]


def fund_instrument(symbol: str = "FUND.X") -> Instrument:
    return Instrument(symbol=symbol, name="测试基金", market="fund", exchange="")


def tiered_rates() -> CostRates:
    """阶梯：持有 <7 天 0.5%，>=7 天 1.5%。"""
    return CostRates(redemption_fee_tiers=((0, 0.005), (7, 0.015)))


# --------------------------------------------------------------------------- #
# 赎回费阶梯（持有期分档）
# --------------------------------------------------------------------------- #
class TestTieredRedemptionFee:
    def test_short_holding_uses_lower_tier(self):
        acc = FundAccount(cost_rates=tiered_rates())
        acc.subscribe("FUND.X", 10000, nav=1.0, date="2024-01-02", confirm_date="2024-01-03")
        acc.confirm_pending()
        # 赎回日距确认日 6 天 -> 命中 (0, 0.005)
        t = acc.redeem("FUND.X", 9985, nav=1.2, date="2024-01-09")
        gross = 9985 * 1.2
        assert t.fee == pytest.approx(gross * 0.005)
        assert t.fee_rate == pytest.approx(0.005)
        assert t.holding_days == 6

    def test_long_holding_uses_higher_tier(self):
        acc = FundAccount(cost_rates=tiered_rates())
        acc.subscribe("FUND.X", 10000, nav=1.0, date="2024-01-02", confirm_date="2024-01-03")
        acc.confirm_pending()
        # 赎回日距确认日 7 天 -> 命中 (7, 0.015)
        t = acc.redeem("FUND.X", 9985, nav=1.2, date="2024-01-10")
        gross = 9985 * 1.2
        assert t.fee == pytest.approx(gross * 0.015)
        assert t.fee_rate == pytest.approx(0.015)
        assert t.holding_days == 7

    def test_default_tiers_equal_flat_five_percent(self):
        # 默认 CostRates 等效统一 0.5%，任何持有期均命中
        acc = FundAccount()
        acc.subscribe("FUND.X", 10000, nav=1.0, date="2024-01-02", confirm_date="2024-01-03")
        acc.confirm_pending()
        t = acc.redeem("FUND.X", 9985, nav=1.2, date="2025-01-01")
        assert t.fee == pytest.approx(9985 * 1.2 * 0.005)


def test_resolve_redemption_fee_rate_helper():
    tiers = ((0, 0.005), (7, 0.015), (30, 0.0))
    assert resolve_redemption_fee_rate(tiers, 0) == 0.005
    assert resolve_redemption_fee_rate(tiers, 6) == 0.005
    assert resolve_redemption_fee_rate(tiers, 7) == 0.015
    assert resolve_redemption_fee_rate(tiers, 29) == 0.015
    assert resolve_redemption_fee_rate(tiers, 30) == 0.0
    assert resolve_redemption_fee_rate((), 10) == 0.0


# --------------------------------------------------------------------------- #
# 分笔 FIFO 成本
# --------------------------------------------------------------------------- #
class TestFifoCost:
    def test_fifo_redeem_oldest_lot_first(self):
        acc = FundAccount()
        # 批次1：@1.0，确认 01-03；批次2：@2.0，确认 01-05
        acc.subscribe("FUND.X", 10000, nav=1.0, date="2024-01-02", confirm_date="2024-01-03")
        acc.subscribe("FUND.X", 10000, nav=2.0, date="2024-01-04", confirm_date="2024-01-05")
        acc.confirm_pending()
        lots = acc.to_dict()["lots"]
        assert len(lots) == 2
        assert lots[0]["acquire_date"] == "2024-01-03"
        assert lots[0]["shares"] == pytest.approx((10000 - 15) / 1.0)
        assert lots[1]["shares"] == pytest.approx((10000 - 15) / 2.0)

        # 赎回 5000 份，全部来自批次1（FIFO）
        t = acc.redeem("FUND.X", 5000, nav=2.0, date="2024-01-06")
        expected_proceeds = 5000 * 2.0 * (1 - 0.005)
        expected_cost = (10000 / 9985) * 5000
        assert t.shares == pytest.approx(5000)
        assert t.fee == pytest.approx(5000 * 2.0 * 0.005)
        assert t.pnl == pytest.approx(expected_proceeds - expected_cost, abs=1e-4)
        # 批次1 余 4985 份，批次2 不变
        remaining = acc.to_dict()["lots"]
        assert remaining[0]["shares"] == pytest.approx(9985 - 5000)
        assert remaining[1]["shares"] == pytest.approx((10000 - 15) / 2.0)


# --------------------------------------------------------------------------- #
# 基金分红
# --------------------------------------------------------------------------- #
class TestDividend:
    def _seeded(self) -> FundAccount:
        acc = FundAccount()
        acc.subscribe("FUND.X", 10000, nav=1.0, date="2024-01-02", confirm_date="2024-01-03")
        acc.confirm_pending()
        return acc

    def test_cash_dividend_credits_cash_keeps_shares(self):
        acc = self._seeded()
        base_cash = acc.cash
        # 9985 份 * 0.1 = 998.5 入现金，份额不变
        amount = acc.apply_dividend("FUND.X", 0.1, nav=1.0, date="2024-01-10", policy="cash")
        assert amount == pytest.approx(998.5)
        assert acc.cash == pytest.approx(base_cash + 998.5)
        assert acc.positions["FUND.X"].shares == pytest.approx(9985)

    def test_reinvest_dividend_adds_shares_at_nav(self):
        acc = self._seeded()
        base_cash = acc.cash
        amount = acc.apply_dividend("FUND.X", 0.1, nav=1.0, date="2024-01-10", policy="reinvest")
        assert amount == pytest.approx(998.5)
        # 现金不变，份额增加 998.5/1.0 = 998.5（单份成本 = 除息净值 1.0）
        assert acc.cash == pytest.approx(base_cash)
        assert acc.positions["FUND.X"].shares == pytest.approx(9985 + 998.5)
        reinvest_lot = [l for l in acc.to_dict()["lots"] if l["acquire_date"] == "2024-01-10"][0]
        assert reinvest_lot["cost_per_share"] == pytest.approx(1.0)

    def test_cash_and_reinvest_preserve_total_at_ex_nav(self):
        # 除息净值下，两种政策总资产一致（净值已反映除息）
        cash_acc = self._seeded()
        reinvest_acc = self._seeded()
        cash_acc.apply_dividend("FUND.X", 0.1, nav=1.0, date="2024-01-10", policy="cash")
        reinvest_acc.apply_dividend("FUND.X", 0.1, nav=1.0, date="2024-01-10", policy="reinvest")
        assert cash_acc.total_value({"FUND.X": 1.0}) == pytest.approx(
            reinvest_acc.total_value({"FUND.X": 1.0})
        )

    def test_dividend_applied_in_engine_cash_policy(self):
        """引擎在除息日自动按现金政策计入分红。"""
        dates_closes = [
            ("2024-01-02", 1.0),  # 申购日
            ("2024-01-03", 1.0),  # 确认 + 除息（dividend=0.1）
            ("2024-01-04", 1.0),
        ]
        bars = make_nav_bars_dates(dates_closes)
        bars[1].dividend = 0.1  # 除息日
        result = BacktestEngine(
            _FundSubscribeOnce(), {"FUND.X": bars}, instruments={"FUND.X": fund_instrument()}
        ).run()
        # 无分红基准：首日申购 1 万 @1.0，次日确认 9985 份 -> 总资产 999985
        # 含分红：现金多 9985*0.1=998.5 -> 总资产 1000983.5
        assert result.equity_curve[-1].total_value == pytest.approx(1_000_983.5, abs=1e-2)
        assert result.fund_account.to_dict()["dividend_policy"] == "cash"


class _FundSubscribeOnce(Strategy):
    def initialize(self, ctx):
        self.done = False

    def handle_data(self, ctx):
        if not self.done:
            ctx.subscribe(ctx.symbols()[0], 10000)
            self.done = True


# --------------------------------------------------------------------------- #
# 价值平均定投策略
# --------------------------------------------------------------------------- #
class TestFundValueAvg:
    def test_subscribes_increasing_then_redeems_on_last_day(self):
        dates_closes = [
            ("2024-01-02", 1.0),
            ("2024-02-02", 1.0),
            ("2024-03-02", 1.0),
        ]
        bars = make_nav_bars_dates(dates_closes)
        result = BacktestEngine(
            FundValueAvgStrategy(amount=1000),
            {"FUND.X": bars},
            instruments={"FUND.X": fund_instrument()},
        ).run()
        subs = [t for t in result.trades if t.side == "subscribe"]
        reds = [t for t in result.trades if t.side == "redeem"]
        # 3 个月各补足一次 + 末日全赎
        assert len(subs) == 3
        assert len(reds) == 1
        # 每期目标递增：申购金额大致递增（受现金约束）
        assert subs[1].amount >= subs[0].amount
        assert subs[2].amount >= subs[1].amount

    def test_rising_nav_redeems_excess_above_target(self):
        """净值快速上涨时，市值超过目标 -> 赎回超出部分（不赎回全部，除非末日）。"""

        class VAProbe(Strategy):
            def initialize(self, ctx):
                self.last_month = ""
                self.period = 0
                self.redeemed_mid = False

            def handle_data(self, ctx):
                sym = ctx.symbols()[0]
                month = ctx.date[:7]
                if month == self.last_month:
                    return
                self.last_month = month
                self.period += 1
                fa = ctx.fund_account
                nav = ctx.bar(sym).close
                invested = (fa.positions[sym].shares if sym in fa.positions else 0.0) * nav
                target = 1000 * self.period
                delta = target - invested
                if delta > 0:
                    ctx.subscribe(sym, min(delta, fa.cash))
                else:
                    pos = fa.positions.get(sym)
                    if pos and pos.shares > 0:
                        ctx.redeem(sym, min(-delta / nav, pos.shares))
                        if ctx.date != ctx.calendar[-1]:
                            self.redeemed_mid = True

        # 净值每月大幅上涨，目标仅线性增长 -> 必然触发中途赎回
        dates_closes = [
            ("2024-01-02", 1.0),
            ("2024-02-02", 10.0),
            ("2024-03-02", 100.0),
        ]
        bars = make_nav_bars_dates(dates_closes)
        probe = VAProbe()
        BacktestEngine(probe, {"FUND.X": bars}, instruments={"FUND.X": fund_instrument()}).run()
        assert probe.redeemed_mid is True

    def test_value_avg_in_report(self):
        dates_closes = [
            ("2024-01-02", 1.0),
            ("2024-02-02", 1.0),
            ("2024-03-02", 1.0),
        ]
        bars = make_nav_bars_dates(dates_closes)
        result = BacktestEngine(
            FundValueAvgStrategy(amount=1000),
            {"FUND.X": bars},
            instruments={"FUND.X": fund_instrument()},
        ).run()
        report = build_report(result, strategy_name="价值平均定投")
        assert "fund_account" in report
        assert len(report["trades"]) == 4  # 3 申购 + 1 赎回
