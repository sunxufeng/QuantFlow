"""V4.1 风险归因指标测试。

验证 PerformanceMetrics 在 attribution 中补齐风险层面（年化波动 / 下行波动 / 索提诺）
与交易收益分解（盈利/亏损平仓盈亏贡献、盈亏比）。
"""
from __future__ import annotations

import datetime as dt

from app.backtest.engine import EquityPoint
from app.backtest.metrics import PerformanceMetrics


def _equity(values, daily_returns=None):
    base = dt.date(2024, 1, 2)
    eq = []
    prev = values[0]
    for i, v in enumerate(values):
        dr = daily_returns[i] if daily_returns else (v / prev - 1.0 if i > 0 else 0.0)
        eq.append(
            EquityPoint(
                date=(base + dt.timedelta(days=i)).isoformat(),
                cash=0.0,
                market_value=v,
                total_value=v,
                daily_return=dr,
            )
        )
        prev = v
    return eq


class _Trade:
    def __init__(self, side, pnl):
        self.side = side
        self.pnl = pnl


def test_risk_metrics_present():
    vals = [1_000_000, 1_010_000, 990_000, 1_020_000, 980_000, 1_030_000, 1_005_000, 1_040_000]
    m = PerformanceMetrics(_equity(vals), initial_cash=1_000_000)
    risk = m.to_dict()["attribution"]["risk"]
    assert "volatility" in risk and risk["volatility"] is not None
    assert "downside_deviation" in risk and risk["downside_deviation"] is not None
    assert "sortino" in risk and risk["sortino"] is not None
    assert risk["volatility"] > 0


def test_trade_pnl_decomposition():
    vals = [1_000_000, 1_020_000, 1_010_000, 1_050_000]
    trades = [
        _Trade("sell", 20_000.0),
        _Trade("sell", -10_000.0),
        _Trade("buy", None),
    ]
    m = PerformanceMetrics(_equity(vals), initial_cash=1_000_000, trades=trades)
    trade = m.to_dict()["attribution"]["trade"]
    assert trade["win_pnl"] == 20_000.0
    assert trade["loss_pnl"] == -10_000.0
    assert trade["profit_factor"] == 2.0
    assert trade["closed_trades"] == 2
