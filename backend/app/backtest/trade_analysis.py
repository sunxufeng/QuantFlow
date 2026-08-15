"""成交（交易）分析（V25，无凭证）。

基于回测报告中的逐笔成交（``Trade``），做交易层面统计：
- 已实现交易数、总盈亏、胜率、平均盈利/平均亏损
- 盈亏比（payoff）、盈利因子（profit factor）、期望收益（expectancy）
- 最大单笔盈利 / 最大单笔亏损
- 按标的拆分盈亏
- 逐笔成交流水（含累计盈亏），供前端绘制「交易清单（blotter）」

输入为 ``Trade`` 对象列表（或可由 dict 构造）。卖出成交带 ``pnl``（已实现盈亏）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from ..backtest.account import Trade


def _to_trades(items: Sequence[Dict[str, Any]]) -> List[Trade]:
    return [Trade(**{k: v for k, v in it.items() if k in Trade.__dataclass_fields__}) for it in items]


def analyze_trades(trades: Sequence[Trade]) -> Dict[str, Any]:
    """对成交列表做交易层面统计与逐笔流水。

    返回 { summary:{...}, by_symbol:{...}, blotter:[...] }
    """
    realized = [t for t in trades if t.pnl is not None]
    pnls = [float(t.pnl) for t in realized]
    n = len(pnls)
    wins = [p for p in pnls if p > 0]
    losses = [p for p in pnls if p < 0]

    total_pnl = sum(pnls)
    win_rate = (len(wins) / n) if n else None
    avg_win = (sum(wins) / len(wins)) if wins else None
    avg_loss = (sum(losses) / len(losses)) if losses else None
    sum_wins = sum(wins)
    sum_losses = sum(losses)
    profit_factor = (sum_wins / abs(sum_losses)) if sum_losses != 0 else (None if sum_wins == 0 else float("inf"))
    payoff_ratio = (avg_win / abs(avg_loss)) if (avg_loss not in (None, 0)) else None
    expectancy = (
        (win_rate * avg_win - (1 - win_rate) * avg_loss)
        if (win_rate is not None and avg_win is not None and avg_loss is not None)
        else None
    )
    largest_win = max(pnls) if pnls else None
    largest_loss = min(pnls) if pnls else None

    # 按标的拆分
    by_symbol: Dict[str, Dict[str, Any]] = {}
    for t in realized:
        s = t.symbol
        b = by_symbol.setdefault(s, {"symbol": s, "trades": 0, "total_pnl": 0.0, "wins": 0})
        b["trades"] += 1
        b["total_pnl"] += float(t.pnl)
        if t.pnl > 0:
            b["wins"] += 1
    for b in by_symbol.values():
        b["win_rate"] = round(b["wins"] / b["trades"], 4) if b["trades"] else None
        b["total_pnl"] = round(b["total_pnl"], 2)

    # 逐笔流水（按日期排序，附累计盈亏）
    ordered = sorted(realized, key=lambda t: (t.date, t.symbol))
    cum = 0.0
    blotter = []
    for t in ordered:
        cum += float(t.pnl or 0.0)
        blotter.append({
            "date": t.date,
            "symbol": t.symbol,
            "side": t.side,
            "shares": t.shares,
            "price": round(float(t.price), 4),
            "pnl": round(float(t.pnl), 2) if t.pnl is not None else None,
            "cumulative_pnl": round(cum, 2),
        })

    summary = {
        "total_trades": n,
        "realized_trades": n,
        "total_pnl": round(total_pnl, 2),
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "avg_win": round(avg_win, 2) if avg_win is not None else None,
        "avg_loss": round(avg_loss, 2) if avg_loss is not None else None,
        "profit_factor": round(profit_factor, 4) if isinstance(profit_factor, float) else profit_factor,
        "payoff_ratio": round(payoff_ratio, 4) if payoff_ratio is not None else None,
        "expectancy": round(expectancy, 4) if expectancy is not None else None,
        "largest_win": round(largest_win, 2) if largest_win is not None else None,
        "largest_loss": round(largest_loss, 2) if largest_loss is not None else None,
    }

    return {
        "summary": summary,
        "by_symbol": list(by_symbol.values()),
        "blotter": blotter,
    }


def analyze_from_dicts(trade_dicts: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """便捷入口：直接接收成交 dict 列表。"""
    return analyze_trades(_to_trades(trade_dicts))
