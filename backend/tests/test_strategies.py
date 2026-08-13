"""内置回测策略测试（M2 交易 API）。"""

from __future__ import annotations

import datetime as dt
from typing import List

import pytest

from app.backtest import (
    BacktestEngine,
    FundTrade,
    Strategy,
    get_strategy,
)
from app.backtest.strategies import STRATEGY_REGISTRY
from app.market import Bar, Instrument


def make_bars(closes: List[float], symbol: str = "TEST.SH", volume: float = 1e6) -> List[Bar]:
    base = dt.date(2024, 1, 2)
    bars = []
    for i, c in enumerate(closes):
        d = (base + dt.timedelta(days=i)).isoformat()
        bars.append(
            Bar(symbol=symbol, date=d, open=float(c), high=float(c), low=float(c),
                close=float(c), volume=float(volume))
        )
    return bars


def run(strategy: Strategy, closes: List[float], *, instruments=None, symbol="TEST.SH"):
    data = {symbol: make_bars(closes, symbol=symbol)}
    return BacktestEngine(strategy, data, instruments=instruments).run()


class TestRegistry:
    def test_known_strategies(self):
        assert set(STRATEGY_REGISTRY) == {"buy_hold", "ma_cross", "fund_dingtou", "fund_value_avg"}

    def test_unknown_strategy_raises(self):
        with pytest.raises(KeyError):
            get_strategy("no_such")


class TestBuyHold:
    def test_default_all_in(self):
        result = run(get_strategy("buy_hold")({}), [10, 11, 12, 13])
        assert len(result.trades) == 2
        buy, sell = result.trades
        assert buy.side == "buy"
        assert buy.shares == 99_900  # 全仓最大整手（100 万/手成本 1000.26 元）
        assert sell.side == "sell" and sell.shares == buy.shares
        assert sell.date == "2024-01-05"

    def test_fixed_shares(self):
        result = run(get_strategy("buy_hold")({"shares": 1000}), [10, 11])
        assert result.trades[0].shares == 1000
        assert len(result.trades) == 2


class TestMaCross:
    def test_golden_and_death_cross(self):
        # 前 20 日横盘 10，随后缓涨（每日 ≤4% 避免涨停）再回落（每日 ≤9% 避免跌停）
        closes = [10.0] * 20 + [10.4, 10.8, 11.2, 11.6, 12.0] + [11.2, 10.4, 9.6, 8.8, 8.0]
        result = run(get_strategy("ma_cross")({}), closes)
        assert len(result.trades) == 2
        buy, sell = result.trades
        assert buy.side == "buy"
        assert buy.date == "2024-01-22"   # 金叉日
        assert sell.side == "sell"
        assert sell.date == "2024-01-31"  # 死叉日

    def test_no_cross_no_trade(self):
        closes = [10.0] * 30
        result = run(get_strategy("ma_cross")({}), closes)
        assert result.trades == []


class TestFundDingTou:
    def test_monthly_subscriptions(self):
        """2024-01-02 起连续 60 天：每月首个交易日申购。"""
        closes = [1.0 + i * 0.001 for i in range(60)]
        inst = {"FUND.X": Instrument(symbol="FUND.X", name="基金", market="fund", exchange="")}
        result = run(
            get_strategy("fund_dingtou")({"amount": 1000}),
            closes,
            instruments=inst,
            symbol="FUND.X",
        )
        subs = [t for t in result.trades if isinstance(t, FundTrade) and t.side == "subscribe"]
        assert len(subs) == 3  # 1月/2月/3月
        assert [t.date for t in subs] == ["2024-01-02", "2024-02-01", "2024-03-01"]
        assert all(t.amount == pytest.approx(1000) for t in subs)

    def test_dingtou_requires_fund_symbol(self):
        """股票标的上调用定投策略：订阅被拒，无成交。"""
        result = run(get_strategy("fund_dingtou")({}), [10.0] * 40)
        assert result.trades == []
