"""风险分析（V42–V46）：与 backtest/metrics(年化/夏普/回撤) 互补的进阶风险工具。

- V42 VaR/CVaR 与回测：历史/参数/蒙特卡洛 三种 VaR，及对收益序列的穿透率(Kupiec 思路)回测。
- V43 回撤归因：最大回撤、持续期、最差若干段回撤区间及区间内最差单日贡献。
- V44 尾部风险与极端相关：上下尾相依系数、下跌相关性（相关性破裂监测）。
- V45 流动性风险：平方根市场冲击模型估计变现成本与变现天数。
- V46 持仓集中度：HHI / 有效持仓数 / Top-N 集中度 / 熵。

纯函数，输入收益序列或权重/持仓即可离线运行、可单测。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np


# ----------------------------- V42 VaR / CVaR -----------------------------

def _var_cvar_hist(returns: np.ndarray, conf: float):
    q = np.quantile(returns, 1.0 - conf)
    tail = returns[returns <= q]
    cvar = float(tail.mean()) if len(tail) else float(q)
    return float(q), cvar


def _var_cvar_param(returns: np.ndarray, conf: float):
    mu = float(np.mean(returns))
    sigma = float(np.std(returns, ddof=0))
    z = _norm_ppf(conf)
    var = -(mu + z * sigma)
    phi = math.exp(-0.5 * z * z) / math.sqrt(2.0 * math.pi)
    cvar = -(mu + sigma * phi / (1.0 - conf))
    return var, cvar


def _norm_ppf(p: float) -> float:
    if p <= 0: return -np.inf
    if p >= 1: return np.inf
    a = [-3.969683028665376e1, 2.209460984245205e2, -2.759285104469687e2, 1.383577518672690e2, -3.066479806614716e1, 2.506628277459239]
    b = [-5.447609879822406e1, 1.615858368580409e2, -1.556989798598866e2, 6.680131188771972e1, -1.328068155288572e1]
    c = [-7.784894002430293e-3, -3.223964580411365e-1, -2.400758277161838, -2.549732539343734, 4.374664141464968, 2.938163982698783]
    d = [7.784695709041462e-3, 3.224671290700398e-1, 2.445134137142996, 3.754408661907416]
    p_low = 0.02425
    p_high = 1 - p_low
    if p < p_low:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)
    if p <= p_high:
        q = p - 0.5
        r = q * q
        return (((((a[0]*r+a[1])*r+a[2])*r+a[3])*r+a[4])*r+a[5])*q / (((((b[0]*r+b[1])*r+b[2])*r+b[3])*r+b[4])*r+1)
    q = math.sqrt(-2 * math.log(1 - p))
    return -(((((c[0]*q+c[1])*q+c[2])*q+c[3])*q+c[4])*q+c[5]) / ((((d[0]*q+d[1])*q+d[2])*q+d[3])*q+1)


def var_cvar(returns: Sequence[float], confidence: float = 0.95, method: str = "historical", n_sims: int = 10000, seed: int = 12345) -> Dict:
    """VaR / CVaR（期望损失）。method: historical | parametric | montecarlo。"""
    r = np.asarray(returns, dtype=float)
    if len(r) < 2:
        raise ValueError("收益序列长度不足")
    if not 0 < confidence < 1:
        raise ValueError("confidence 须介于 0 与 1 之间")
    if method == "historical":
        var, cvar = _var_cvar_hist(r, confidence)
    elif method == "parametric":
        var, cvar = _var_cvar_param(r, confidence)
    elif method == "montecarlo":
        rng = np.random.default_rng(seed)
        sims = rng.choice(r, size=n_sims, replace=True)
        var, cvar = _var_cvar_hist(sims, confidence)
    else:
        raise ValueError("method 须为 historical/parametric/montecarlo")
    return {
        "confidence": confidence,
        "method": method,
        "var": round(-var, 6),
        "cvar": round(-cvar, 6),
        "var_pct": round(-var * 100, 4),
        "cvar_pct": round(-cvar * 100, 4),
    }


def var_backtest(returns: Sequence[float], confidence: float = 0.95, method: str = "historical") -> Dict:
    """VaR 穿透率回测：统计实际击穿次数，与期望值比较（Kupiec 思路的覆盖检验）。"""
    r = np.asarray(returns, dtype=float)
    if len(r) < 30:
        raise ValueError("回测需至少 30 期收益")
    var_res = var_cvar(r, confidence, method)
    var_loss = var_res["var"]
    breaches = int(np.sum(r < -var_loss))
    expected = (1.0 - confidence) * len(r)
    coverage = breaches / len(r)
    tol = 2.0 * math.sqrt((1.0 - confidence) * confidence / len(r)) * 2.0
    passed = abs(coverage - (1.0 - confidence)) <= tol
    return {
        "confidence": confidence,
        "method": method,
        "n": len(r),
        "breaches": breaches,
        "expected_breaches": round(expected, 2),
        "coverage": round(coverage, 4),
        "tolerance": round(tol, 4),
        "passed": passed,
    }


# ----------------------------- V43 回撤归因 -----------------------------

def drawdown_analysis(returns: Sequence[float]) -> Dict:
    """回撤归因：最大回撤、持续期、最差若干段区间及区间内最差单日。"""
    r = np.asarray(returns, dtype=float)
    cum = np.cumprod(1.0 + r)
    peak = np.maximum.accumulate(cum)
    dd = cum / peak - 1.0
    max_dd = float(dd.min())
    underwater = dd < -1e-9
    idx = np.where(underwater)[0]
    episodes = []
    if len(idx):
        start = idx[0]
        prev = idx[0]
        for i in idx[1:]:
            if i - prev > 1:
                episodes.append((start, prev))
                start = i
            prev = i
        episodes.append((start, prev))
        top = []
        for s, e in episodes:
            seg_dd = dd[s:e + 1]
            depth = float(seg_dd.min())
            worst_day = float(r[s:e + 1].min())
            top.append({"start": int(s), "end": int(e), "depth": round(depth, 6), "duration": int(e - s + 1), "worst_single_day": round(worst_day, 6)})
        top.sort(key=lambda x: x["depth"])
        top = top[:3]
    mdd_end = int(np.argmin(dd))
    mdd_start = int(np.where(peak[:mdd_end + 1] == peak[:mdd_end + 1].max())[0][-1]) if mdd_end > 0 else 0
    return {
        "max_drawdown": round(max_dd, 6),
        "max_dd_start": mdd_start,
        "max_dd_end": mdd_end,
        "current_drawdown": round(float(dd[-1]), 6),
        "n_episodes": len(episodes),
        "worst_episodes": top,
    }


# ----------------------------- V44 尾部风险与极端相关 -----------------------------

def tail_risk(returns_a: Sequence[float], returns_b: Sequence[float], alpha: float = 0.05) -> Dict:
    """尾部风险与极端相关：上下尾相依系数 + 下跌相关性（相关性破裂监测）。"""
    a = np.asarray(returns_a, dtype=float)
    b = np.asarray(returns_b, dtype=float)
    if len(a) != len(b) or len(a) < 10:
        raise ValueError("两序列需等长且至少 10 期")
    qa = np.quantile(a, alpha)
    qb = np.quantile(b, alpha)
    qa_up = np.quantile(a, 1 - alpha)
    qb_up = np.quantile(b, 1 - alpha)
    a_low = a <= qa
    b_low = b <= qb
    a_high = a >= qa_up
    b_high = b >= qb_up
    n = len(a)
    denom_l = a_low.mean()
    lower = float((a_low & b_low).mean() / denom_l) if denom_l > 0 else 0.0
    denom_u = a_high.mean()
    upper = float((a_high & b_high).mean() / denom_u) if denom_u > 0 else 0.0
    med_a = np.median(a); med_b = np.median(b)
    down_mask = (a < med_a) & (b < med_b)
    normal_corr = float(np.corrcoef(a, b)[0, 1])
    downside_corr = float(np.corrcoef(a[down_mask], b[down_mask])[0, 1]) if down_mask.sum() > 2 else 0.0
    return {
        "alpha": alpha,
        "lower_tail_dependence": round(lower, 4),
        "upper_tail_dependence": round(upper, 4),
        "normal_correlation": round(normal_corr, 4),
        "downside_correlation": round(downside_corr, 4),
        "correlation_breakdown": round(downside_corr - normal_corr, 4),
    }


# ----------------------------- V45 流动性风险 -----------------------------

def liquidity_risk(positions: Dict[str, Dict], adv: Dict[str, float], participation: float = 0.1, impact_coef: float = 0.1) -> Dict:
    """流动性风险：平方根市场冲击模型估计变现成本与变现天数。

    positions[asset] = {quantity, price}（或 {market_value}）
    adv[asset] = 日均成交额（金额）；adv[asset+'_vol'] = 日均成交量（股）
    冲击成本 ≈ impact_coef * sqrt(trade_value / ADV_value)
    变现天数 ≈ quantity / (participation * daily_vol)
    """
    results = []
    total_value = 0.0
    total_impact = 0.0
    for asset, pos in positions.items():
        qty = float(pos.get("quantity", 0.0))
        price = float(pos.get("price", 0.0))
        mv = float(pos.get("market_value", qty * price))
        adv_val = float(adv.get(asset, 0.0))
        daily_vol = float(adv.get(asset + "_vol", 0.0))
        impact_pct = 0.0
        days = None
        if adv_val > 0 and mv > 0:
            impact_pct = impact_coef * math.sqrt(min(mv / adv_val, 1.0))
            total_impact += impact_pct * mv
        if daily_vol > 0 and qty > 0:
            days = qty / (participation * daily_vol)
        total_value += mv
        results.append({
            "asset": asset,
            "market_value": round(mv, 2),
            "impact_cost_pct": round(impact_pct, 4),
            "impact_cost": round(impact_pct * mv, 2),
            "liquidation_days": round(days, 2) if days is not None else None,
        })
    return {
        "participation": participation,
        "impact_coef": impact_coef,
        "total_market_value": round(total_value, 2),
        "total_impact_cost": round(total_impact, 2),
        "total_impact_pct": round(total_impact / total_value, 4) if total_value > 0 else 0.0,
        "positions": results,
    }


# ----------------------------- V46 持仓集中度 -----------------------------

def concentration(weights: Dict[str, float]) -> Dict:
    """持仓集中度：HHI / 有效持仓数 / Top-N 集中度 / 熵。"""
    w = np.array([float(x) for x in weights.values()], dtype=float)
    s = w.sum()
    if s <= 0:
        raise ValueError("weights 之和须为正")
    w = w / s
    hhi = float(np.sum(w ** 2))
    eff_n = 1.0 / hhi if hhi > 0 else 0.0
    order = np.sort(w)[::-1]
    entropy = float(-np.sum(w * np.log(w + 1e-12)))
    return {
        "n_assets": len(w),
        "hhi": round(hhi, 6),
        "effective_n": round(eff_n, 4),
        "top1": round(float(order[0]), 4) if len(order) else 0.0,
        "top3": round(float(order[:3].sum()), 4),
        "top5": round(float(order[:5].sum()), 4),
        "entropy": round(entropy, 4),
        "interpretation": "HHI 越高越集中；有效持仓数越小越集中",
    }
