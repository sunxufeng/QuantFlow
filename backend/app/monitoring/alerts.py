"""组合监控与预警（V87–V91）：把组合层面的「监控 + 阈值告警」能力做成离线纯函数。

注意：集中度(HHI/Top-N) 与 流动性冲击 已在 risk 模块（V45/V46）实现，此处不再重复；
本模块聚焦以下 5 个新增监控维度：

- V87 持仓偏离监控：实际权重 vs 目标权重，drift 超阈值 → 再平衡交易清单。
- V88 收益质量监控：胜率 / 盈亏比 / 最大连胜连亏 / 偏度，低于阈值告警。
- V89 跟踪误差监控：组合 vs 基准滚动跟踪误差，超限告警。
- V90 行业敞口监控：分组（行业）权重 vs 上限，超限告警。
- V91 风险预算监控：各资产边际风险贡献 vs 目标风险预算偏差告警。

所有函数均为纯函数，不依赖数据库或网络；数值上保证无 NaN。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np


# ----------------------------- V87 持仓偏离监控 -----------------------------

def drift_monitor(
    weights: Sequence[float],
    target: Sequence[float],
    asset_names: Optional[Sequence[str]] = None,
    threshold: float = 0.05,
) -> Dict:
    """实际权重 vs 目标权重，drift 超阈值触发再平衡。

    返回 { "drift", "flagged", "trades", "max_drift", "n_flagged" }。
    trades: 需买卖的权重差（正=买入，负=卖出）。
    """
    w = np.asarray(weights, dtype=float)
    t = np.asarray(target, dtype=float)
    if w.shape[0] != t.shape[0]:
        raise ValueError("weights 与 target 长度必须一致")
    if abs(w.sum() - 1.0) > 1e-6 or abs(t.sum() - 1.0) > 1e-6:
        raise ValueError("weights 与 target 必须归一化为 1")
    names = list(asset_names) if asset_names is not None else [f"A{i}" for i in range(len(w))]
    drift = (w - t).tolist()
    flagged = []
    trades = []
    for i, d in enumerate(drift):
        if abs(d) > threshold:
            side = "BUY" if d > 0 else "SELL"
            flagged.append(names[i])
            trades.append({"asset": names[i], "side": side, "weight_delta": float(d)})
    return {
        "drift": drift,
        "flagged": flagged,
        "trades": trades,
        "max_drift": float(np.max(np.abs(drift))),
        "n_flagged": len(flagged),
    }


# ----------------------------- V88 收益质量监控 -----------------------------

def return_quality_monitor(
    returns: Sequence[float],
    hit_rate_limit: float = 0.45,
    payoff_ratio_limit: float = 0.8,
) -> Dict:
    """胜率 / 盈亏比 / 最大连胜连亏 / 偏度，低于阈值告警。

    返回 { "hit_rate", "avg_win", "avg_loss", "payoff_ratio", "max_win_streak",
           "max_loss_streak", "skew", "breaches" }。
    """
    r = np.asarray(returns, dtype=float)
    if r.shape[0] < 2:
        raise ValueError("returns 长度至少为 2")
    wins = r[r > 0]
    losses = r[r < 0]
    hit_rate = float(len(wins) / len(r))
    avg_win = float(np.mean(wins)) if len(wins) else 0.0
    avg_loss = float(np.mean(losses)) if len(losses) else 0.0
    payoff_ratio = float(avg_win / abs(avg_loss)) if avg_loss != 0 else (float("inf") if avg_win > 0 else 0.0)

    # 连胜 / 连亏
    max_win_streak = max_loss_streak = cur_win = cur_loss = 0
    for x in r:
        if x > 0:
            cur_win += 1; cur_loss = 0; max_win_streak = max(max_win_streak, cur_win)
        elif x < 0:
            cur_loss += 1; cur_win = 0; max_loss_streak = max(max_loss_streak, cur_loss)
        else:
            cur_win = cur_loss = 0

    n = len(r)
    skew = float(np.mean((r - r.mean()) ** 3) / (np.std(r) ** 3)) if n >= 3 and np.std(r) > 0 else 0.0

    breaches = []
    if hit_rate < hit_rate_limit:
        breaches.append(f"胜率 {hit_rate:.0%} 低于 {hit_rate_limit:.0%}")
    if math.isfinite(payoff_ratio) and payoff_ratio < payoff_ratio_limit:
        breaches.append(f"盈亏比 {payoff_ratio:.2f} 低于 {payoff_ratio_limit:.2f}")

    return {
        "hit_rate": hit_rate,
        "avg_win": avg_win,
        "avg_loss": avg_loss,
        "payoff_ratio": payoff_ratio,
        "max_win_streak": max_win_streak,
        "max_loss_streak": max_loss_streak,
        "skew": skew,
        "breaches": breaches,
    }


# ----------------------------- V89 跟踪误差监控 -----------------------------

def tracking_error_monitor(
    returns_port: Sequence[float],
    returns_bench: Sequence[float],
    window: int = 20,
    limit: float = 0.05,
) -> Dict:
    """组合 vs 基准滚动跟踪误差，超限告警。

    返回 { "rolling_te", "mean_te", "max_te", "breaches", "n_breaches" }。
    rolling_te 为每个窗口末点的年化（sqrt(252)）跟踪误差。
    """
    rp = np.asarray(returns_port, dtype=float)
    rb = np.asarray(returns_bench, dtype=float)
    if rp.shape[0] != rb.shape[0] or rp.shape[0] < window:
        raise ValueError("收益序列长度必须一致且不小于 window")
    diff = rp - rb
    rolling_te = []
    breaches = []
    for i in range(window, len(diff) + 1):
        seg = diff[i - window: i]
        te = float(np.std(seg, ddof=1) * math.sqrt(252))
        rolling_te.append(te)
        if te > limit:
            breaches.append({"index": i - 1, "te": te})
    arr = np.array(rolling_te) if rolling_te else np.array([0.0])
    return {
        "rolling_te": rolling_te,
        "mean_te": float(np.mean(arr)),
        "max_te": float(np.max(arr)),
        "breaches": breaches,
        "n_breaches": len(breaches),
    }


# ----------------------------- V90 行业敞口监控 -----------------------------

def sector_exposure_monitor(
    group_weights: Dict[str, float],
    limit: float = 0.6,
    asset_names: Optional[Dict[str, str]] = None,
) -> Dict:
    """分组（行业）权重 vs 上限，超限告警。

    group_weights: 分组名 -> 权重（合计应为 1）。
    返回 { "exposures", "over_limit", "max_exposure", "breaches" }。
    """
    if not group_weights:
        raise ValueError("group_weights 不能为空")
    total = sum(group_weights.values())
    if abs(total - 1.0) > 1e-6:
        raise ValueError("group_weights 必须归一化为 1")
    over = {g: w for g, w in group_weights.items() if w > limit}
    breaches = []
    for g, w in over.items():
        breaches.append({"group": g, "weight": w})
    return {
        "exposures": group_weights,
        "over_limit": over,
        "max_exposure": float(max(group_weights.values())),
        "breaches": breaches,
    }


# ----------------------------- V91 风险预算监控 -----------------------------

def risk_budget_monitor(
    weights: Sequence[float],
    cov: Sequence[Sequence[float]],
    target_budget: Optional[Sequence[float]] = None,
    asset_names: Optional[Sequence[str]] = None,
) -> Dict:
    """各资产边际风险贡献 vs 目标风险预算偏差告警。

    组合方差 = w' Σ w；资产 i 的风险贡献 = w_i * (Σw)_i / 组合方差。
    返回 { "risk_contrib", "risk_contrib_pct", "budget_deviation",
           "max_deviation", "breaches" }。
    """
    w = np.asarray(weights, dtype=float)
    C = np.asarray(cov, dtype=float)
    if C.ndim != 2 or C.shape[0] != C.shape[1] or C.shape[0] != len(w):
        raise ValueError("cov 必须为 n×n 且与 weights 长度一致")
    if abs(w.sum() - 1.0) > 1e-6:
        raise ValueError("weights 必须归一化为 1")
    # 保证半正定
    C = (C + C.T) / 2.0
    try:
        eig = np.linalg.eigvalsh(C)
        if eig.min() < 0:
            C = C + (-eig.min() + 1e-10) * np.eye(len(w))
    except np.linalg.LinAlgError:
        pass
    port_var = float(w @ C @ w)
    if port_var <= 0:
        raise ValueError("组合方差必须为正数")
    marginal = C @ w
    contrib = w * marginal
    contrib_pct = (contrib / port_var).tolist()
    names = list(asset_names) if asset_names is not None else [f"A{i}" for i in range(len(w))]

    budget_dev = [0.0] * len(w)
    breaches = []
    if target_budget is not None:
        tb = np.asarray(target_budget, dtype=float)
        if abs(tb.sum() - 1.0) > 1e-6:
            raise ValueError("target_budget 必须归一化为 1")
        for i in range(len(w)):
            dev = contrib_pct[i] - float(tb[i])
            budget_dev[i] = float(dev)
            if abs(dev) > 0.1:
                breaches.append({"asset": names[i], "deviation": float(dev)})

    return {
        "risk_contrib": contrib.tolist(),
        "risk_contrib_pct": contrib_pct,
        "budget_deviation": budget_dev,
        "max_deviation": float(max(abs(d) for d in budget_dev)) if budget_dev else 0.0,
        "breaches": breaches,
    }
