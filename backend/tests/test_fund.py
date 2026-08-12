"""M2 回测引擎基金测试：场外基金账户、申购/赎回、T+1 确认、净值曲线。

对标开发计划 §4.2 与 V1.2「基金回测」：本文件净值/盈亏断言
全部基于手工核算，防止口径回归。
"""

from __future__ import annotations

import datetime as dt
from typing import List

import pytest

from app.backtest import (
    BacktestEngine,
    FundAccount,
    FundOrderRejected,
    PerformanceMetrics,
    Strategy,
    build_report,
)
from app.backtest.fund import FundPosition, FundTrade
from app.market import Bar, Instrument


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def make_nav_bars(
    closes: List[float], symbol: str = "FUND.X", volume: float = 0.0
) -> List[Bar]:
    """构造基金净值序列（OHLC=净值，默认成交量为 0）；股票可传 volume>0。"""
    base = dt.date(2024, 1, 2)
    bars = []
    for i, c in enumerate(closes):
        d = (base + dt.timedelta(days=i)).isoformat()
        bars.append(
            Bar(
                symbol=symbol,
                date=d,
                open=float(c),
                high=float(c),
                low=float(c),
                close=float(c),
                volume=volume,  # 场外基金无成交量
            )
        )
    return bars


def fund_instrument(symbol: str = "FUND.X") -> Instrument:
    return Instrument(symbol=symbol, name="测试基金", market="fund", exchange="")


def run_fund_buy_hold(closes: List[float], amount: float = 10000.0) -> "BacktestEngine":
    """基金买入持有回测：首日申购 amount 元，末日全部赎回。"""

    class FundBuyHold(Strategy):
        def initialize(self, ctx):
            self.subscribed = False

        def handle_data(self, ctx):
            sym = ctx.symbols()[0]
            if not self.subscribed:
                ctx.subscribe(sym, amount)
                self.subscribed = True
            elif ctx.date == ctx.calendar[-1]:
                # 通过基金账户查询持仓份额
                fa = getattr(ctx, "fund_account", None)
                if fa and sym in fa.positions:
                    ctx.redeem(sym, fa.positions[sym].shares)

    data = {"FUND.X": make_nav_bars(closes)}
    engine = BacktestEngine(
        FundBuyHold(), data, instruments={"FUND.X": fund_instrument()}
    )
    return engine


# --------------------------------------------------------------------------- #
# FundAccount 基础
# --------------------------------------------------------------------------- #
class TestFundAccount:
    def test_subscribe_math(self):
        """申购 10000 元、净值 1.5：手续费 15，份额 (10000-15)/1.5。"""
        acc = FundAccount()
        t = acc.subscribe("FUND.X", 10000, nav=1.5, date="d1", confirm_date="d2")
        assert t is not None
        assert t.side == "subscribe"
        assert t.amount == 10000
        assert t.fee == pytest.approx(15.0)
        assert t.shares == pytest.approx((10000 - 15) / 1.5)
        assert t.confirm_date == "d2"
        # 现金当日扣款、份额待确认
        assert acc.cash == pytest.approx(1_000_000 - 10000)
        assert acc.positions == {}

    def test_confirm_credits_shares_with_fee_in_cost(self):
        acc = FundAccount()
        acc.subscribe("FUND.X", 10000, nav=1.0, date="d1")
        acc.confirm_pending()
        pos = acc.positions["FUND.X"]
        assert pos.shares == pytest.approx(9985.0)  # (10000-15)/1.0
        # 成本含申购费摊薄：10000 / 9985
        assert pos.cost == pytest.approx(10000 / 9985)

    def test_redeem_math_and_pnl(self):
        acc = FundAccount()
        acc.subscribe("FUND.X", 10000, nav=1.0, date="d1")
        acc.confirm_pending()
        # 全部赎回：9985 份 @1.2
        t = acc.redeem("FUND.X", 9985, nav=1.2, date="d2", confirm_date="d3")
        assert t is not None
        assert t.side == "redeem"
        gross = 9985 * 1.2
        fee = gross * 0.005
        assert t.fee == pytest.approx(fee)
        # 已实现盈亏 = 到账 - 持仓成本（10000 含申购费）
        assert t.pnl == pytest.approx(gross - fee - 10000)
        # 份额当日锁定（扣减），资金 T+1 到账
        assert "FUND.X" not in acc.positions
        assert acc.cash == pytest.approx(1_000_000 - 10000)
        acc.confirm_pending()
        assert acc.cash == pytest.approx(1_000_000 - 10000 + gross - fee)

    def test_redeem_exceeding_holding_clamps(self):
        acc = FundAccount()
        acc.subscribe("FUND.X", 10000, nav=1.0, date="d1")
        acc.confirm_pending()
        t = acc.redeem("FUND.X", 999_999, nav=1.0, date="d2")
        assert t.shares == pytest.approx(9985.0)

    def test_redeem_no_position_returns_none(self):
        acc = FundAccount()
        assert acc.redeem("FUND.X", 100, nav=1.0, date="d1") is None

    def test_negative_amount_rejected(self):
        acc = FundAccount()
        with pytest.raises(FundOrderRejected):
            acc.subscribe("FUND.X", -100, nav=1.0, date="d1")

    def test_insufficient_cash_partial_fill(self):
        acc = FundAccount(initial_cash=5000)
        t = acc.subscribe("FUND.X", 10000, nav=1.0, date="d1")
        assert t.amount == pytest.approx(5000)
        assert t.shares == pytest.approx((5000 - 7.5) / 1.0)
        assert acc.cash == pytest.approx(0)

    def test_subscription_limit(self):
        acc = FundAccount(max_subscription_amount=10000)
        t1 = acc.subscribe("FUND.X", 20000, nav=1.0, date="d1")
        assert t1.amount == pytest.approx(10000)  # 限额截断
        assert acc.subscribe("FUND.X", 1000, nav=1.0, date="d1") is None  # 当日已达上限
        acc.start_new_day()
        t2 = acc.subscribe("FUND.X", 1000, nav=1.0, date="d2")
        assert t2 is not None and t2.amount == pytest.approx(1000)

    def test_total_value_includes_pending(self):
        acc = FundAccount()
        acc.subscribe("FUND.X", 10000, nav=1.0, date="d1")
        # 当日：现金 99 万 + 待确认份额 9985 份 @1.0
        assert acc.total_value({"FUND.X": 1.0}) == pytest.approx(1_000_000 - 10000 + 9985)
        acc.confirm_pending()
        assert acc.total_value({"FUND.X": 1.1}) == pytest.approx(990_000 + 9985 * 1.1)


# --------------------------------------------------------------------------- #
# 引擎集成（场外基金）
# --------------------------------------------------------------------------- #
class TestFundEngine:
    def test_fund_buy_hold_hand_calculated(self):
        """净值 1.0 -> 1.1 -> 1.2，首日申购 1 万元、末日全赎。

        d1: 申购 10000，费 15，份额 9985，现金 990000
            净值 1.0：总资产 = 990000 + 9985*1.0 = 999985
        d2: 确认份额，净值 1.1：总资产 = 990000 + 9985*1.1 = 1000983.5
        d3: 全赎 @1.2：到账 9985*1.2 - 9985*1.2*0.005 = 11922.09
            总资产 = 990000 + 11922.09 = 1001922.09
        """
        result = run_fund_buy_hold([1.0, 1.1, 1.2]).run()
        curve = result.equity_curve
        assert len(curve) == 3
        assert curve[0].total_value == pytest.approx(999_985, abs=1e-2)
        assert curve[1].total_value == pytest.approx(1_000_983.5, abs=1e-2)
        assert curve[2].total_value == pytest.approx(1_001_922.09, abs=1e-2)

        assert len(result.trades) == 2
        sub, red = result.trades
        assert isinstance(sub, FundTrade) and sub.side == "subscribe"
        assert isinstance(red, FundTrade) and red.side == "redeem"
        assert red.pnl == pytest.approx(9985 * 1.2 * (1 - 0.005) - 10000, abs=1e-2)

        # 指标
        m = PerformanceMetrics(curve, 1_000_000, result.trades)
        assert m.total_return == pytest.approx(1_001_922.09 / 1_000_000 - 1, abs=1e-6)
        assert m.win_rate == pytest.approx(1.0)
        # 换手 = (申购金额 + 赎回净值额) / 初始资金
        assert m.turnover == pytest.approx((10000 + 9985 * 1.2) / 1_000_000, abs=1e-6)

    def test_fund_ignores_limit_up(self):
        """基金净值单日 +20% 不影响申购（无涨跌停限制）。"""

        class BuyAfterJump(Strategy):
            def handle_data(self, ctx):
                if ctx.date == ctx.calendar[1]:
                    ctx.subscribe(ctx.symbols()[0], 10000)

        engine = BacktestEngine(
            BuyAfterJump(),
            {"FUND.X": make_nav_bars([1.0, 1.2, 1.3])},  # +20%
            instruments={"FUND.X": fund_instrument()},
        )
        result = engine.run()
        assert len(result.trades) == 1
        assert result.trades[0].nav == pytest.approx(1.2)

    def test_fund_zero_volume_still_tradeable(self):
        """场外基金成交量为 0 仍可交易（不同于股票停牌判定）。"""

        class SubAlways(Strategy):
            def handle_data(self, ctx):
                ctx.subscribe(ctx.symbols()[0], 10000)

        bars = make_nav_bars([1.0, 1.1])
        result = BacktestEngine(
            SubAlways(), {"FUND.X": bars}, instruments={"FUND.X": fund_instrument()}
        ).run()
        assert len(result.trades) == 2  # 每天都能申购

    def test_subscribe_on_stock_symbol_returns_none(self):
        class Spy(Strategy):
            def handle_data(self, ctx):
                self.res = ctx.subscribe("A.SH", 10000)

        s = Spy()
        engine = BacktestEngine(
            s,
            {"A.SH": make_nav_bars([10, 11], symbol="A.SH")},
            instruments={"A.SH": Instrument(symbol="A.SH", name="股票", market="stock")},
        )
        engine.run()
        assert s.res is None

    def test_mixed_stock_and_fund_portfolio(self):
        """股票 + 基金组合：净值曲线为两者合并值（共享 100 万初始资金）。

        d1: 股票买 1000 股 @10（费 5.1）→ 股票现金 989994.9
            基金申购 10000 → 基金现金 990000，待确认 9985 份
            d1 总资产 = (989994.9 + 10000) + (990000 + 9985) - 1000000 = 999979.9
        d2: 股票市值 11000；基金确认 9985 份 @1.1 = 10983.5
            总资产 = (989994.9 + 11000) + (990000 + 10983.5) - 1000000 = 1001978.4
        """

        class Mixed(Strategy):
            def initialize(self, ctx):
                self.started = False

            def handle_data(self, ctx):
                if not self.started:
                    ctx.order("A.SH", 1000, "buy")
                    ctx.subscribe("FUND.X", 10000)
                    self.started = True

        bars = {
            "A.SH": make_nav_bars([10, 11], symbol="A.SH", volume=1_000_000),
            "FUND.X": make_nav_bars([1.0, 1.1]),
        }
        instruments = {
            "A.SH": Instrument(symbol="A.SH", name="股票", market="stock"),
            "FUND.X": fund_instrument(),
        }
        result = BacktestEngine(Mixed(), bars, instruments=instruments).run()
        assert result.equity_curve[-1].total_value == pytest.approx(1_001_978.4, abs=1e-2)
        assert result.fund_account is not None
        # 账户终态含基金
        d = result.to_dict()
        assert "fund_account" in d
        assert len([t for t in result.trades if t.side == "subscribe"]) == 1

    def test_report_includes_fund(self):
        result = run_fund_buy_hold([1.0, 1.1, 1.2]).run()
        report = build_report(result, strategy_name="基金定投")
        assert report["fund_account"]["total_value"] == pytest.approx(
            result.equity_curve[-1].total_value, abs=1e-2
        )
        assert len(report["trades"]) == 2
        assert report["trades"][0]["side"] == "subscribe"
