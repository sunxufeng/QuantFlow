"""蒙特卡洛鲁棒性模拟（V15）。

对一次已完成的回测（净值曲线）做日收益的**自助重采样（bootstrap）**，
生成 N 条等长的合成净值路径，用于评估策略表现的统计稳健性：

- 结果分布：终值 / 总收益 / 最大回撤 / 夏普比率 的分位数分布
- 净值置信带：每条交易日上的低~高分位区间（P5~P95 / P25~P75）+ 中位路径
- 终值直方图：终值分布的分箱统计

方法：对日收益做有放回的自助抽样（i.i.d. bootstrap）。``block_size > 1`` 时
使用块自助（block bootstrap），以保留短期自相关 / 波动聚集特征。
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, List, Optional, Sequence

TRADING_DAYS_PER_YEAR = 252


def _get(point: Any, key: str, default: Any = 0.0) -> Any:
    """兼容 EquityPoint 对象与已序列化的 dict。"""
    if isinstance(point, dict):
        return point.get(key, default)
    return getattr(point, key, default)


def _daily_returns(equity: Sequence[Any]) -> List[float]:
    """从净值曲线还原日收益序列（去掉首日 0 收益点）。"""
    rets = [float(_get(p, "daily_return", 0.0) or 0.0) for p in equity]
    if rets and rets[0] == 0.0:
        rets = rets[1:]
    return rets


def _max_drawdown(values: Sequence[float]) -> float:
    peak = values[0] if values else 0.0
    mdd = 0.0
    for v in values:
        peak = max(peak, v)
        if peak:
            mdd = min(mdd, v / peak - 1.0)
    return mdd


def _sharpe(returns: Sequence[float]) -> float:
    if len(returns) < 2:
        return 0.0
    mean_r = sum(returns) / len(returns)
    var = sum((r - mean_r) ** 2 for r in returns) / (len(returns) - 1)
    std = math.sqrt(var)
    if std <= 1e-12:
        return 0.0
    return mean_r / std * math.sqrt(TRADING_DAYS_PER_YEAR)


def _percentile(sorted_vals: List[float], q: float) -> float:
    """线性插值分位数（q in [0, 1]）。"""
    if not sorted_vals:
        return 0.0
    n = len(sorted_vals)
    if n == 1:
        return sorted_vals[0]
    rank = q * (n - 1)
    lo = int(math.floor(rank))
    hi = int(math.ceil(rank))
    if lo == hi:
        return sorted_vals[lo]
    frac = rank - lo
    return sorted_vals[lo] * (1.0 - frac) + sorted_vals[hi] * frac


def _bootstrap_indices(n: int, size: int, rng: random.Random, block_size: int) -> List[int]:
    """生成长度为 size 的自助抽样下标（支持块自助）。"""
    if block_size <= 1:
        return [rng.randrange(n) for _ in range(size)]
    idx: List[int] = []
    while len(idx) < size:
        start = rng.randrange(max(1, n - block_size + 1))
        for j in range(block_size):
            if len(idx) >= size:
                break
            idx.append(min(start + j, n - 1))
    return idx


def monte_carlo(
    equity_curve: Sequence[Any],
    initial_cash: float,
    n_sims: int = 200,
    seed: Optional[int] = 42,
    confidence: float = 0.9,
    block_size: int = 1,
) -> Dict[str, Any]:
    """对净值曲线做蒙特卡洛自助重采样，返回稳健性统计。

    参数
    ----
    equity_curve: 形如 [EquityPoint] 或 [dict]，需含 date / total_value / daily_return
    initial_cash: 初始资金（建议与曲线首点 total_value 一致）
    n_sims: 模拟路径条数
    seed: 随机种子（固定可复现）
    confidence: 置信带水平（0.9 -> P5~P95）
    block_size: 块自助块大小（1=普通自助）

    返回
    ----
    { dates, actual, summary, bands, histogram, n_sims, confidence, block_size }
    """
    if n_sims <= 0:
        raise ValueError("n_sims 必须为正")
    if not 0.0 < confidence < 1.0:
        raise ValueError("confidence 需介于 0 与 1 之间")

    rets = _daily_returns(equity_curve)
    dates = [_get(p, "date", i) for i, p in enumerate(equity_curve)]
    if len(rets) < 2:
        raise ValueError("净值曲线日收益不足 2 个，无法进行自助重采样")

    actual_values = [float(_get(p, "total_value", 0.0) or 0.0) for p in equity_curve]
    start_cash = float(initial_cash) if initial_cash else (actual_values[0] if actual_values else 1.0)
    actual_final = actual_values[-1] if actual_values else start_cash
    actual_total_return = actual_final / start_cash - 1.0 if start_cash else 0.0
    actual_mdd = _max_drawdown(actual_values)
    actual_sharpe = _sharpe(rets)

    rng = random.Random(seed)
    n = len(rets)
    size = n  # 每条模拟路径与原始等长

    sim_final: List[float] = []
    sim_total_return: List[float] = []
    sim_mdd: List[float] = []
    sim_sharpe: List[float] = []
    per_date: List[List[float]] = [[] for _ in range(len(dates))]

    for _ in range(n_sims):
        idx = _bootstrap_indices(n, size, rng, max(1, block_size))
        sampled = [rets[i] for i in idx]
        path = [start_cash]
        for r in sampled:
            path.append(path[-1] * (1.0 + r))
        # 与 dates 对齐（path[0] 对应 dates[0]）
        aligned = path[: len(dates)]
        while len(aligned) < len(dates):
            aligned.append(aligned[-1])
        for t, v in enumerate(aligned):
            per_date[t].append(v)
        fin = aligned[-1]
        sim_final.append(fin)
        sim_total_return.append(fin / start_cash - 1.0 if start_cash else 0.0)
        sim_mdd.append(_max_drawdown(aligned))
        sim_sharpe.append(_sharpe(sampled))

    def _summary(vals: List[float]) -> Dict[str, float]:
        s = sorted(vals)
        return {
            "p5": round(_percentile(s, 0.05), 4),
            "p25": round(_percentile(s, 0.25), 4),
            "p50": round(_percentile(s, 0.50), 4),
            "p75": round(_percentile(s, 0.75), 4),
            "p95": round(_percentile(s, 0.95), 4),
            "mean": round(sum(vals) / len(vals), 4),
        }

    lower = (1.0 - confidence) / 2.0
    upper = 1.0 - lower

    bands = []
    for t in range(len(dates)):
        s = sorted(per_date[t])
        bands.append({
            "date": dates[t],
            "p_low": round(_percentile(s, lower), 2),
            "p25": round(_percentile(s, 0.25), 2),
            "p50": round(_percentile(s, 0.50), 2),
            "p75": round(_percentile(s, 0.75), 2),
            "p_high": round(_percentile(s, upper), 2),
        })

    # 终值直方图
    fmin = min(sim_final)
    fmax = max(sim_final)
    nbins = min(20, max(5, n_sims // 10))
    width = (fmax - fmin) / nbins if fmax > fmin else 1.0
    edges = [fmin + i * width for i in range(nbins + 1)]
    counts = [0] * nbins
    for v in sim_final:
        bi = int((v - fmin) / width) if width > 0 else 0
        bi = min(max(bi, 0), nbins - 1)
        counts[bi] += 1
    histogram = {
        "bin_edges": [round(e, 2) for e in edges],
        "bin_centers": [round((edges[i] + edges[i + 1]) / 2.0, 2) for i in range(nbins)],
        "counts": counts,
    }

    return {
        "dates": list(dates),
        "actual": {
            "final_value": round(actual_final, 2),
            "total_return": round(actual_total_return, 6),
            "max_drawdown": round(actual_mdd, 6),
            "sharpe": round(actual_sharpe, 4),
        },
        "summary": {
            "final_equity": _summary(sim_final),
            "total_return": _summary(sim_total_return),
            "max_drawdown": _summary(sim_mdd),
            "sharpe": _summary(sim_sharpe),
        },
        "bands": bands,
        "histogram": histogram,
        "n_sims": n_sims,
        "confidence": confidence,
        "block_size": max(1, block_size),
    }
