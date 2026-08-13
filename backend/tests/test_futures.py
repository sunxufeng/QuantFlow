"""V1.3 期货回测测试：保证金、逐日盯市、多空净仓、强平、盈亏、引擎集成。

所有净值/盈亏断言均基于手工构造场景手工核算，防止撮合或保证金口径回归。
"""

from __future__ import annotations

import datetime as dt
from typing import List

import pytest

from app.backtest import BacktestEngine, BacktestError, CostRates, Strategy
from app.backtest.futures import FuturesAccount, FuturesPosition, FuturesTrade
from app.market import Bar


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def make_future_bars(closes: List[float], symbol: str = "TEST.FUT") -> List[Bar]:
    base = dt.date(2024, 3, 1)
    return [
        Bar(symbol=symbol, date=(base + dt.timedelta(days=i)).isoformat(),
            open=float(c), high=float(c), low=float(c), close=float(c), volume=1_000_000.0)
        for i, c in enumerate(closes)
    ]


def make_account(initial: float = 1_000_000.0, multiplier: float = 10.0) -> FuturesAccount:
    return FuturesAccount(initial, multipliers={"F": multiplier})


# --------------------------------------------------------------------------- #
# 账户：开仓 / 保证金 / 盯市
# --------------------------------------------------------------------------- #
class TestFuturesAccount:
    def test_open_long_margin_and_commission(self):
        acc = make_account()
        t = acc.order_future("F", 1, "buy", 1000.0, date="2024-03-01")
        assert t is not None and t.direction == "long" and t.contracts == 1
        assert acc.positions["F"].avg_entry == pytest.approx(1000.0)
        # 现金 = 初始 - 手续费(1手×3)
        assert acc.cash == pytest.approx(1_000_000 - 3)
        # 保证金占用 = 1×10×1000×10%
        acc.update_prices({"F": 1000.0})
        assert acc.margin_occupied() == pytest.approx(1000.0)
        assert acc.equity() == pytest.approx(1_000_000 - 3)

    def test_mark_to_market_profit(self):
        acc = make_account()
        acc.order_future("F", 1, "buy", 1000.0, date="2024-03-01")
        acc.update_prices({"F": 1010.0})
        # 浮动盈亏 = (1010-1000)×1×10 = 100；权益 = 现金 + 浮动
        assert acc.floating_pnl() == pytest.approx(100.0)
        assert acc.equity() == pytest.approx(1_000_000 - 3 + 100)

    def test_close_long_realized_pnl(self):
        acc = make_account()
        acc.order_future("F", 1, "buy", 1000.0, date="2024-03-01")
        t = acc.order_future("F", 1, "sell", 1010.0, date="2024-03-02")
        # 平仓已实现 = (1010-1000)×10 = 100；现金 = 初始 - 开仓费3 + 已实现100 - 平仓费3
        assert t is not None and t.pnl == pytest.approx(100.0)
        assert "F" not in acc.positions
        assert acc.realized_pnl == pytest.approx(100.0)
        assert acc.cash == pytest.approx(1_000_000 - 6 + 100)

    def test_short_profit_on_drop(self):
        acc = make_account()
        acc.order_future("F", 1, "sell", 1000.0, date="2024-03-01")
        acc.update_prices({"F": 990.0})
        # 空头浮动 = (990-1000)×1×10×(-1) = +100
        assert acc.floating_pnl() == pytest.approx(100.0)
        t = acc.order_future("F", 1, "buy", 990.0, date="2024-03-02")
        assert t.pnl == pytest.approx(100.0)
        assert acc.realized_pnl == pytest.approx(100.0)

    def test_netting_partial_close_then_flip(self):
        acc = make_account()
        acc.order_future("F", 2, "buy", 1000.0, date="2024-03-01")  # 开多 2
        # 平 1 手多（@1010 实现 100）
        acc.order_future("F", 1, "sell", 1010.0, date="2024-03-02")
        assert acc.positions["F"].contracts == 1
        # 再平 1 手多（@1020 实现 200）
        acc.order_future("F", 1, "sell", 1020.0, date="2024-03-03")
        assert "F" not in acc.positions
        # 已实现 = 100+200=300；手续费 = 开2(6)+平1(3)+平1(3)=12
        assert acc.realized_pnl == pytest.approx(300.0)
        assert acc.cash == pytest.approx(1_000_000 - 12 + 300)

    def test_flip_long_to_short(self):
        acc = make_account()
        acc.order_future("F", 1, "buy", 1000.0, date="d1")  # 多 1
        # 卖出 2 手：先平多 1，再开空 1
        acc.order_future("F", 2, "sell", 1050.0, date="d2")
        pos = acc.positions["F"]
        assert pos.direction == "short"
        assert pos.contracts == 1
        assert pos.avg_entry == pytest.approx(1050.0)

    def test_insufficient_margin_opens_max_affordable(self):
        acc = make_account(initial=2000.0)  # 小资金
        # 想开 100 手 @1000：保证金需 100×10×1000×10% = 100000，远超权益
        t = acc.order_future("F", 100, "buy", 1000.0, date="d1")
        assert t is not None
        # 最大可开：可用 ~1997 / (1000+3) ≈ 1 手
        assert acc.positions["F"].contracts == 1

    def test_forced_liquidation(self):
        # 初始 20000，开多 5 手 @1000（保证金 5000），价格暴跌至 640 触发强平
        acc = make_account(initial=20_000.0)
        acc.order_future("F", 5, "buy", 1000.0, date="d1")
        assert acc.positions["F"].contracts == 5
        # 日终盯市 @640：浮动 = (640-1000)×5×10 = -18000；权益 = 19985-18000=1985
        # 维持保证金 = 3200×0.75 = 2400；1985 <= 2400 → 强平
        acc.settle({"F": 640.0})
        assert acc.forced_liquidations == 1
        assert "F" not in acc.positions
        # 已实现 = -18000；现金 = 19985 -18000 - 平仓费15 = 1970
        assert acc.realized_pnl == pytest.approx(-18_000.0)
        assert acc.cash == pytest.approx(1970.0)

    def test_reject_non_integer_contracts(self):
        from app.backtest.account import OrderRejected

        acc = make_account()
        with pytest.raises(OrderRejected):
            acc.order_future("F", 1.5, "buy", 1000.0)


# --------------------------------------------------------------------------- #
# 引擎集成：期货策略 + 多空净仓 + 净值聚合
# --------------------------------------------------------------------------- #
class TestFuturesEngine:
    def _run(self, closes, strategy="futures_ma_cross", contracts=1, fast=3, slow=6):
        from app.backtest.strategies import STRATEGY_REGISTRY
        from app.market.models import Instrument

        data = {"TEST.FUT": make_future_bars(closes)}
        instruments = {
            "TEST.FUT": Instrument(
                symbol="TEST.FUT", name="x", exchange="CFFEX",
                market="future", contract_multiplier=10.0,
            )
        }
        engine = BacktestEngine(
            STRATEGY_REGISTRY[strategy]({"contracts": contracts, "fast": fast, "slow": slow}),
            data, instruments=instruments,
        )
        return engine.run()

    def test_futures_account_created(self):
        closes = list(range(100, 111)) + list(range(109, 98, -1))
        result = self._run(closes)
        assert result.futures_account is not None
        assert "TEST.FUT" in result.engine._future_symbols
        # 净值曲线长度 = 交易日数
        assert len(result.equity_curve) == len(closes)

    def test_stock_order_rejected_on_future(self):
        # 在期货标的上下股票单返回 None（必须用 order_future）
        from app.backtest.strategies import STRATEGY_REGISTRY
        from app.market.models import Instrument

        data = {"TEST.FUT": make_future_bars([10, 11, 12])}
        instruments = {"TEST.FUT": Instrument(symbol="TEST.FUT", name="x", market="future", contract_multiplier=10.0)}
        engine = BacktestEngine(
            STRATEGY_REGISTRY["buy_hold"]({}), data, instruments=instruments
        )
        result = engine.run()
        # buy_hold 用 ctx.order（股票单）→ 对期货标的返回 None，无成交
        assert result.trades == []

    def test_futures_ma_cross_trades(self):
        # 先涨后跌，触发死叉做空（至少一笔成交）
        closes = list(range(100, 111)) + list(range(109, 98, -1))
        result = self._run(closes, contracts=1)
        # 至少发生开仓/平仓，且全部为期货成交（含方向）
        assert len(result.trades) >= 1
        assert all(getattr(t, "contracts", 0) >= 1 for t in result.trades)
        # 报告携带 futures_account
        from app.backtest.report import build_report

        report = build_report(result, strategy_name="futures_ma_cross")
        assert "futures_account" in report
        assert report["futures_account"]["initial_cash"] == pytest.approx(1_000_000)

    def test_equity_contains_floating_pnl(self):
        # 先跌后涨，触发金叉做多；末点权益应包含正浮动盈利（> 初始）
        closes = [110, 109, 108, 107, 106, 105, 104, 103, 102, 101, 100,
                  102, 104, 106, 108, 110, 112, 114, 116, 118, 120]
        result = self._run(closes, contracts=2)
        last = result.equity_curve[-1]
        # 金叉后开多，末端上涨 → 权益 > 初始
        assert last.total_value > result.engine.initial_cash


# --------------------------------------------------------------------------- #
# 组合回测支持期货标的
# --------------------------------------------------------------------------- #
class TestFuturesPortfolio:
    def test_portfolio_with_future_leg(self):
        from app.backtest.portfolio import PortfolioBacktest

        closes = [100, 101, 102, 103, 104, 105, 104, 103, 102, 101]
        legs = [{
            "strategy": "futures_ma_cross",
            "params": {"contracts": 1},
            "symbols": ["TEST.FUT"],
            "asset_types": {"TEST.FUT": "future"},
            "multipliers": {"TEST.FUT": 10.0},
            "interval": "daily",
            "weight": 1.0,
        }]
        pb = PortfolioBacktest(
            legs=legs, initial_cash=1_000_000.0,
            start="2024-03-01", end="2024-03-12",
        )
        # 直接喂数据：monkey 掉 market_service.bars
        import app.backtest.portfolio as P

        orig = P.market_service.bars
        P.market_service.bars = lambda s, st, en, interval="daily": make_future_bars(closes) if s == "TEST.FUT" else []
        try:
            report = pb.run()
        finally:
            P.market_service.bars = orig
        assert report["type"] == "portfolio"
        assert len(report["equity_curve"]) >= 1
