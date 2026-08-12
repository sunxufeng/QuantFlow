"""M2 回测引擎测试：成本模型、账户撮合、事件循环、绩效指标、报告。

对标开发计划 §4.2「回测正确性对照用例（手工 K 线）」：
本文件的净值/盈亏断言全部基于手工构造的 K 线手工核算，
防止回归（撮合逻辑或成本口径变化导致净值失真）。
"""

from __future__ import annotations

import datetime as dt
from typing import List

import pytest

from app.backtest import (
    Account,
    BacktestEngine,
    BacktestError,
    BacktestReportStore,
    BacktestResult,
    CostCalculator,
    CostRates,
    OrderRejected,
    PerformanceMetrics,
    Strategy,
    build_report,
)
from app.backtest.engine import EquityPoint
from app.market import Bar


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def make_bars(closes: List[float], symbol: str = "TEST.SH") -> List[Bar]:
    """按收盘价序列构造日线（OHLC 均等于收盘价）。"""
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
                volume=1_000_000.0,
            )
        )
    return bars


def run_buy_hold(closes: List[float], shares: int = 1000, sell_day: int = -1) -> "BacktestResult":
    """买入持有策略回测：首日买入 shares，最后一日全部卖出。"""

    class BuyHold(Strategy):
        def initialize(self, ctx):
            self.bought = False

        def handle_data(self, ctx):
            if not self.bought:
                ctx.order(ctx.symbols()[0], shares, "buy")
                self.bought = True
            elif ctx.date == ctx.calendar[sell_day]:
                pos = ctx.account.positions.get(ctx.symbols()[0])
                if pos:
                    ctx.order(ctx.symbols()[0], pos.shares, "sell")

    data = {"TEST.SH": make_bars(closes)}
    engine = BacktestEngine(BuyHold(), data)
    result = engine.run()
    return result


# --------------------------------------------------------------------------- #
# 成本模型
# --------------------------------------------------------------------------- #
class TestCosts:
    def test_commission_floor(self):
        calc = CostCalculator()
        info = calc.transaction_costs(10.0, 100, is_buy=True)
        # 成交额 1000 * 万2.5 = 0.25 < 5 → 按最低 5 元
        assert info["commission"] == 5.0

    def test_stamp_tax_sell_only(self):
        calc = CostCalculator()
        buy = calc.transaction_costs(10.0, 1000, is_buy=True)
        sell = calc.transaction_costs(10.0, 1000, is_buy=False)
        assert buy["stamp_tax"] == 0.0
        assert sell["stamp_tax"] == pytest.approx(10.0 * 1000 * 0.0005)

    def test_transfer_fee_both_sides(self):
        calc = CostCalculator()
        buy = calc.transaction_costs(10.0, 1000, is_buy=True)
        assert buy["transfer_fee"] == pytest.approx(10.0 * 1000 * 0.00001)

    def test_slippage_direction(self):
        calc = CostCalculator(CostRates(slippage=0.001))
        assert calc.execution_price(10.0, is_buy=True) == pytest.approx(10.01)
        assert calc.execution_price(10.0, is_buy=False) == pytest.approx(9.99)

    def test_load_custom_rates(self, tmp_path):
        import json

        p = tmp_path / "costs.json"
        p.write_text(json.dumps({"commission_rate": 0.001}), encoding="utf-8")
        rates = __import__("app.backtest.costs", fromlist=["load_cost_rates"]).load_cost_rates(str(p))
        assert rates.commission_rate == 0.001
        assert rates.stamp_tax_rate == 0.0005  # 其余用默认


# --------------------------------------------------------------------------- #
# 账户撮合
# --------------------------------------------------------------------------- #
class TestAccount:
    def test_reject_non_lot(self):
        acc = Account()
        with pytest.raises(OrderRejected):
            acc.order("A.SH", "buy", 150, limit_price=10.0)

    def test_buy_creates_position(self):
        acc = Account()
        t = acc.order("A.SH", "buy", 1000, limit_price=10.0, date="2024-01-02")
        assert t is not None
        pos = acc.positions["A.SH"]
        assert pos.shares == 1000
        assert pos.available == 0  # T+1 冻结
        # 现金 = 100万 - 10000 - (佣金5 + 过户0.1)
        assert acc.cash == pytest.approx(1_000_000 - 10_005.1)

    def test_t_plus_1_sell_blocked_today(self):
        acc = Account()
        acc.order("A.SH", "buy", 1000, limit_price=10.0, date="2024-01-02")
        # 当日卖出被拒（T+1 冻结）
        assert acc.order("A.SH", "sell", 1000, limit_price=11.0, date="2024-01-02") is None
        acc.settle()
        # 次日可卖
        t = acc.order("A.SH", "sell", 1000, limit_price=11.0, date="2024-01-03")
        assert t is not None
        assert "A.SH" not in acc.positions

    def test_limit_up_blocks_buy(self):
        acc = Account()
        acc.set_daily_states(set(), {"A.SH"}, set())
        assert acc.order("A.SH", "buy", 1000, limit_price=10.0) is None

    def test_limit_down_blocks_sell(self):
        acc = Account()
        acc.order("A.SH", "buy", 1000, limit_price=10.0, date="2024-01-02")
        acc.settle()
        acc.set_daily_states(set(), set(), {"A.SH"})
        assert acc.order("A.SH", "sell", 1000, limit_price=10.0, date="2024-01-03") is None

    def test_suspended_blocks_trade(self):
        acc = Account()
        acc.set_daily_states({"A.SH"}, set(), set())
        assert acc.order("A.SH", "buy", 1000, limit_price=10.0) is None

    def test_insufficient_cash_buys_max_lot(self):
        acc = Account(initial_cash=10_000)
        t = acc.order("A.SH", "buy", 10_000, limit_price=10.0)  # 想买 10 万 -> 资金不足
        assert t is not None
        assert t.shares == 900  # 9000 元可买最大整手（含手续费）
        assert acc.cash >= 0

    def test_sell_no_position_returns_none(self):
        acc = Account()
        assert acc.order("A.SH", "sell", 1000, limit_price=10.0) is None

    def test_realized_pnl(self):
        acc = Account()
        acc.order("A.SH", "buy", 1000, limit_price=10.0, date="2024-01-02")
        acc.settle()
        t = acc.order("A.SH", "sell", 1000, limit_price=11.0, date="2024-01-03")
        # 已实现盈亏 = 11000 - 卖出成本 - 持仓成本(含买入费)
        expect = 11_000 - (5 + 5.5 + 0.11) - (10_000 + 5.1)
        assert t.pnl == pytest.approx(expect)
        assert acc.realized_pnl == pytest.approx(expect)

    def test_partial_sell_keeps_avg_cost(self):
        acc = Account()
        acc.order("A.SH", "buy", 1000, limit_price=10.0, date="2024-01-02")
        acc.settle()
        cost_before = acc.positions["A.SH"].cost
        acc.order("A.SH", "sell", 300, limit_price=11.0, date="2024-01-03")
        pos = acc.positions["A.SH"]
        assert pos.shares == 700
        assert pos.cost == pytest.approx(cost_before)  # 平均成本不变


# --------------------------------------------------------------------------- #
# 事件循环
# --------------------------------------------------------------------------- #
class TestEngine:
    def test_empty_data_raises(self):
        with pytest.raises(BacktestError):
            BacktestEngine(Strategy(), {})

    def test_lifecycle_order(self):
        calls = []

        class Tracked(Strategy):
            def initialize(self, ctx):
                calls.append("init")

            def before_trading(self, ctx):
                calls.append(f"before:{ctx.date}")

            def handle_data(self, ctx):
                calls.append(f"handle:{ctx.date}")

            def after_trading(self, ctx):
                calls.append(f"after:{ctx.date}")

        data = {"A.SH": make_bars([10, 11])}
        BacktestEngine(Tracked(), data).run()
        assert calls == [
            "init",
            "before:2024-01-02", "handle:2024-01-02", "after:2024-01-02",
            "before:2024-01-03", "handle:2024-01-03", "after:2024-01-03",
        ]

    def test_buy_hold_pnl(self):
        """手工核算：10 买入 1000 股 -> 14 卖出。

        买入成本 = 10000 + 佣金5 + 过户0.1 = 10005.1
        卖出费用 = 佣金5 + 印花税7 + 过户0.14 = 12.14
        已实现盈亏 = 14000 - 12.14 - 10005.1 = 3982.76
        """
        result = run_buy_hold([10, 11, 12, 13, 14])
        assert len(result.trades) == 2
        buy, sell = result.trades
        assert buy.side == "buy" and buy.shares == 1000 and buy.price == 10.0
        assert sell.side == "sell" and sell.shares == 1000 and sell.price == 14.0
        assert sell.pnl == pytest.approx(3_982.76)
        assert result.account.realized_pnl == pytest.approx(3_982.76)
        assert result.account.cash == pytest.approx(1_000_000 + 3_982.76)
        # 净值曲线 5 个点
        assert len(result.equity_curve) == 5
        assert result.equity_curve[-1].total_value == pytest.approx(1_003_982.76)

    def test_engine_limit_up_blocks_buy(self):
        """次日 +10% 涨停：买入委托被拒。"""

        class BuyOnLimitUp(Strategy):
            def handle_data(self, ctx):
                if ctx.date == ctx.calendar[1]:
                    ctx.order(ctx.symbols()[0], 1000, "buy")

        data = {"A.SH": make_bars([10, 11])}
        result = BacktestEngine(BuyOnLimitUp(), data).run()
        assert result.trades == []
        assert result.account.cash == pytest.approx(1_000_000)

    def test_engine_limit_down_blocks_sell(self):
        """次日 -10% 跌停：卖出委托被拒。"""

        class SellOnLimitDown(Strategy):
            def initialize(self, ctx):
                self.sold = False

            def handle_data(self, ctx):
                if not self.sold:
                    ctx.order(ctx.symbols()[0], 1000, "buy")
                    self.sold = True
                elif ctx.date == ctx.calendar[1]:
                    pos = ctx.account.positions.get(ctx.symbols()[0])
                    if pos:
                        ctx.order(ctx.symbols()[0], pos.shares, "sell")

        data = {"A.SH": make_bars([10, 9])}  # 次日跌停（9 = 10*0.9）
        result = BacktestEngine(SellOnLimitDown(), data).run()
        assert len(result.trades) == 1  # 只有买入
        assert result.account.positions["A.SH"].shares == 1000

    def test_context_history_and_prev_close(self):
        seen = {}

        class Spy(Strategy):
            def handle_data(self, ctx):
                seen[ctx.date] = (
                    len(ctx.history(ctx.symbols()[0], 3)),
                    ctx.prev_close(ctx.symbols()[0]),
                )

        data = {"A.SH": make_bars([10, 11, 12])}
        BacktestEngine(Spy(), data).run()
        # 历史含当日；首日无前收
        assert seen["2024-01-02"] == (1, None)
        assert seen["2024-01-03"] == (2, 10.0)
        assert seen["2024-01-04"] == (3, 11.0)

    def test_suspended_symbol_skipped(self):
        """某日停牌（volume=0）：当日无法成交。"""

        class BuySuspended(Strategy):
            def handle_data(self, ctx):
                ctx.order(ctx.symbols()[0], 1000, "buy")

        bars = make_bars([10, 11])
        bars[1].volume = 0.0  # 次日停牌
        result = BacktestEngine(BuySuspended(), {"A.SH": bars}).run()
        assert len(result.trades) == 1  # 仅首日买入成交
        assert result.trades[0].date == "2024-01-02"


# --------------------------------------------------------------------------- #
# 绩效指标
# --------------------------------------------------------------------------- #
class TestMetrics:
    def _curve(self, values, initial=1_000_000):
        prev = initial
        pts = []
        for i, v in enumerate(values):
            pts.append(
                EquityPoint(
                    date=f"d{i}",
                    cash=v,
                    market_value=0.0,
                    total_value=v,
                    daily_return=v / prev - 1.0 if i else 0.0,
                )
            )
            prev = v
        return pts

    def test_total_return_and_drawdown(self):
        m = PerformanceMetrics(self._curve([100, 120, 90], initial=100), 100)
        assert m.total_return == pytest.approx(-0.1)
        assert m.max_drawdown == pytest.approx(-0.25)  # 90/120 - 1
        assert m.days == 3

    def test_win_rate(self):
        class T:
            side = "sell"
            pnl = 100.0

        class T2:
            side = "sell"
            pnl = -50.0

        class T3:
            side = "buy"  # 买入不计入胜率
            pnl = None

        m = PerformanceMetrics(self._curve([100, 110]), 100, trades=[T(), T2(), T3()])
        assert m.win_rate == pytest.approx(0.5)

    def test_turnover(self):
        acc = Account()
        acc.order("A.SH", "buy", 1000, limit_price=10.0, date="d1")
        acc.settle()
        acc.order("A.SH", "sell", 1000, limit_price=14.0, date="d2")
        m = PerformanceMetrics(self._curve([100, 110]), 1_000_000, trades=acc.trades)
        # (10000 + 14000) / 100万
        assert m.turnover == pytest.approx(0.024)

    def test_sharpe_nonzero(self):
        # 日收益有波动且为正 → 夏普 > 0、年化 > 0
        m = PerformanceMetrics(self._curve([100, 101, 103]), 100)
        assert m.sharpe > 0
        assert m.annual_return > 0

    def test_empty_curve(self):
        m = PerformanceMetrics([], 100)
        assert m.days == 0
        assert m.total_return == 0.0
        assert m.max_drawdown == 0.0


# --------------------------------------------------------------------------- #
# 报告
# --------------------------------------------------------------------------- #
class TestReport:
    def test_build_report(self):
        result = run_buy_hold([10, 11, 12])
        report = build_report(result, strategy_name="买入持有", strategy_config={"shares": 1000})
        assert report["type"] == "backtest_report"
        assert report["strategy"] == "买入持有"
        assert len(report["equity_curve"]) == 3
        assert len(report["trades"]) == 2
        assert report["metrics"]["total_return"] == pytest.approx(
            report["account"]["total_value"] / 1_000_000 - 1, abs=5e-5
        )
        assert report["start_date"] == "2024-01-02"

    def test_report_store_roundtrip(self, tmp_path):
        store = BacktestReportStore(report_dir=str(tmp_path))
        result = run_buy_hold([10, 11, 12])
        report = build_report(result, strategy_name="买入持有")
        path = store.save(report)
        loaded = store.load(report["run_id"])
        assert loaded["run_id"] == report["run_id"]
        assert loaded["metrics"] == report["metrics"]
        assert report["run_id"] in store.list()
        assert path.endswith(f"{report['run_id']}.json")
