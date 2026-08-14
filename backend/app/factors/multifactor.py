"""多因子组合回测闭环（V4.2）。

把多个因子表达式按权重合成为综合信号，生成仓位并回测，形成
「因子打分 → 组合权重 → 回测」的端到端闭环。纯离线（复用合成行情
+ 因子计算层 + 回测绩效层），无需券商凭证。

流程：
1. 取标的行情 → DataFrame(OHLCV + date)
2. 逐因子用 expression_factor 计算因子列（df.eval，仅用真实行情列）
3. 按权重加权合成（composite_factors：逐列 winsorize + 全局 zscore + 加权求和）
4. 综合分 > 阈值 → 满仓(1)，否则空仓(0)（阈值默认 0，无前视：用前一交易日综合分决策）
5. 用日收益按仓位模拟净值曲线 → PerformanceMetrics
6. 返回 metrics + 综合分序列(日期/综合分/仓位) + 各因子权重

后续可把 V3.2 因子排行榜选出的高分因子直接作为本接口的 factors 输入，
完成「研究 → 合成 → 回测」的闭环联动。
"""

from __future__ import annotations

import datetime as dt
from typing import Any, Dict, List, Optional

import pandas as pd

from ..backtest.engine import EquityPoint
from ..backtest.metrics import PerformanceMetrics
from ..factors.transform import composite_factors, expression_factor
from ..market.models import Bar
from ..market.service import market_service


def _bars_to_df(bars: List[Bar]) -> pd.DataFrame:
    rows = [
        {
            "date": b.date,
            "open": float(b.open),
            "high": float(b.high),
            "low": float(b.low),
            "close": float(b.close),
            "volume": float(b.volume),
        }
        for b in bars
    ]
    return pd.DataFrame(rows)


def multifactor_backtest(
    *,
    symbol: str,
    start: str,
    end: str,
    factors: List[Dict[str, Any]],
    threshold: float = 0.0,
    initial_cash: float = 1_000_000.0,
    interval: str = "daily",
) -> Dict[str, Any]:
    """对单标的做多因子组合回测。

    ``factors``：[{name, expression, weight}, ...]，weight 不要求归一化（内部归一化）。
    返回 {metrics, composite_series, factors, symbol, start, end}。
    """
    if not factors:
        raise ValueError("至少需要一个因子")
    valid = [f for f in factors if (f.get("name") and f.get("expression"))]
    if len(valid) != len(factors):
        raise ValueError("每个因子需提供 name 与 expression")

    bars = market_service.bars(symbol, start, end, interval=interval)
    if not bars:
        raise ValueError(f"标的 {symbol} 在 {start}~{end} 无行情数据")
    df = _bars_to_df(bars).sort_values("date").reset_index(drop=True)

    # 1) 逐因子计算因子列
    cols: List[str] = []
    weights: List[float] = []
    for f in valid:
        out = f"__f_{len(cols)}"
        try:
            df = expression_factor(df, f["expression"], out)
        except Exception as exc:
            raise ValueError(f"因子『{f['name']}』表达式求值失败（{f['expression']}）: {exc}") from exc
        cols.append(out)
        weights.append(float(f.get("weight") or 1.0))

    # 2) 加权合成（逐列 winsorize + 全局 zscore + 加权求和）
    composite = composite_factors(df, cols, weights, winsorize_pct=0.01)

    # 3) 仓位：用前一交易日综合分决策（无前视）
    comp_vals = composite.fillna(0.0).tolist()
    positions: List[float] = []
    for i in range(len(df)):
        if i == 0:
            positions.append(0.0)
        else:
            positions.append(1.0 if comp_vals[i - 1] > threshold else 0.0)

    # 4) 模拟净值：equity[i] = equity[i-1] * (1 + pos[i-1] * 日收益)
    closes = df["close"].tolist()
    equity = [float(initial_cash)]
    daily_rets = [0.0]
    for i in range(1, len(df)):
        ret = closes[i] / closes[i - 1] - 1.0 if closes[i - 1] else 0.0
        pnl_ret = positions[i - 1] * ret
        equity.append(equity[-1] * (1.0 + pnl_ret))
        daily_rets.append(pnl_ret)

    points = [
        EquityPoint(
            date=df["date"].iloc[i],
            cash=0.0,
            market_value=equity[i],
            total_value=equity[i],
            daily_return=daily_rets[i],
        )
        for i in range(len(df))
    ]
    pm = PerformanceMetrics(points, initial_cash=initial_cash)

    composite_series = [
        {"date": df["date"].iloc[i], "composite": round(comp_vals[i], 6), "position": positions[i]}
        for i in range(len(df))
    ]

    return {
        "symbol": symbol,
        "start": start,
        "end": end,
        "threshold": threshold,
        "factors": [{"name": f["name"], "expression": f["expression"], "weight": float(f.get("weight") or 1.0)} for f in valid],
        "metrics": pm.to_dict(),
        "composite_series": composite_series,
    }
