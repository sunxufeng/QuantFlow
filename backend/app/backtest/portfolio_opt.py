"""投资组合优化（V23，无凭证）。

基于多资产日收益率序列，用 scipy SLSQP 求解 Markowitz 均值-方差框架下的：
- 最小方差组合（min_variance_portfolio）
- 最大夏普组合（max_sharpe_portfolio，含无风险利率 rf）
- 有效前沿（efficient_frontier：在 [最小收益, 最大收益] 区间扫描目标收益，
  逐点求最小方差权重）

权重可约束为多头（long_only，默认）或允许卖空。所有计算仅依赖 numpy / scipy，
无需任何外部行情凭证；端点层负责把 synthetic / live 行情转成收益矩阵后传入。
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy.optimize import minimize


def _to_matrix(assets_returns: Sequence[Sequence[float]]) -> np.ndarray:
    """把「每资产一条收益序列」转成 (T, N) 矩阵（T=期数, N=资产数）。"""
    ar = [np.asarray(list(r), dtype=float) for r in assets_returns]
    lengths = {len(r) for r in ar}
    if len(lengths) != 1:
        raise ValueError(f"各资产收益序列长度需一致，当前: {sorted(lengths)}")
    if not ar or ar[0].size < 2:
        raise ValueError("至少需要 2 期收益与 1 个资产")
    return np.stack(ar, axis=1)  # (T, N)


def _solve(
    mu: np.ndarray,
    cov: np.ndarray,
    long_only: bool,
    target_return: Optional[float] = None,
    rf: float = 0.0,
    kind: str = "min_var",
) -> Dict[str, object]:
    """SLSQP 求解单点组合优化。

    - kind="min_var"（且 target_return 为 None）：最小方差（无收益约束）
    - kind="max_sharpe"（且 target_return 为 None）：最大化 (μ-rf)/σ
    - target_return 给定：在「收益≈目标」约束下最小方差（前沿点）
    返回 { weights, expected_return, expected_vol, sharpe }
    """
    n = len(mu)
    bounds = [(0.0, 1.0) if long_only else (-1.0, 1.0) for _ in range(n)]
    x0 = np.full(n, 1.0 / n)

    def variance(w):
        return float(w @ cov @ w)

    def neg_sharpe(w):
        ret = float(w @ mu)
        vol = float(np.sqrt(max(w @ cov @ w, 1e-18)))
        return -(ret - rf) / vol

    constraints = [{"type": "eq", "fun": lambda w: float(np.sum(w)) - 1.0}]
    if target_return is not None:
        constraints.append(
            {"type": "eq", "fun": lambda w: float(w @ mu) - target_return}
        )

    if target_return is not None:
        objective = variance
    elif kind == "max_sharpe":
        objective = neg_sharpe
    else:
        objective = variance
    res = minimize(
        objective, x0, method="SLSQP", bounds=bounds, constraints=constraints,
        options={"maxiter": 200, "ftol": 1e-12},
    )
    w = res.x if res.success else x0
    w = np.clip(w, -(1e-9 if not long_only else 0.0), None)
    # 重新归一化（数值误差修正）
    s = w.sum()
    if abs(s) > 1e-12:
        w = w / s
    exp_ret = float(w @ mu)
    exp_vol = float(np.sqrt(max(w @ cov @ w, 0.0)))
    sharpe = (exp_ret - rf) / exp_vol if exp_vol > 1e-12 else 0.0
    return {
        "weights": [round(float(x), 6) for x in w],
        "expected_return": round(exp_ret, 6),
        "expected_vol": round(exp_vol, 6),
        "sharpe": round(sharpe, 6),
    }


def min_variance_portfolio(
    assets_returns: Sequence[Sequence[float]],
    long_only: bool = True,
    rf: float = 0.0,
) -> Dict[str, object]:
    """最小方差组合（无目标收益约束）。"""
    mat = _to_matrix(assets_returns)
    mu = mat.mean(axis=0)
    cov = np.cov(mat, rowvar=False)
    return _solve(mu, cov, long_only, target_return=None, rf=rf, kind="min_var")


def max_sharpe_portfolio(
    assets_returns: Sequence[Sequence[float]],
    long_only: bool = True,
    rf: float = 0.0,
) -> Dict[str, object]:
    """最大夏普组合（在收益目标解中自然得到，等价于最大化 (μ-rf)/σ）。"""
    mat = _to_matrix(assets_returns)
    mu = mat.mean(axis=0)
    cov = np.cov(mat, rowvar=False)
    return _solve(mu, cov, long_only, target_return=None, rf=rf, kind="max_sharpe")


def efficient_frontier(
    assets_returns: Sequence[Sequence[float]],
    n_points: int = 20,
    long_only: bool = True,
    rf: float = 0.0,
) -> Dict[str, object]:
    """有效前沿：在 [最小资产收益, 最大资产收益] 区间均匀取目标收益，逐点求最小方差组合。

    返回 { assets, n_assets, n_periods, min_variance, max_sharpe,
           frontier:[{target_return, expected_return, expected_vol, sharpe, weights}],
           equal_weight:{...} }
    """
    mat = _to_matrix(assets_returns)
    n, t = mat.shape[1], mat.shape[0]
    mu = mat.mean(axis=0)
    cov = np.cov(mat, rowvar=False)

    lo = float(mu.min())
    hi = float(mu.max())
    if hi - lo < 1e-12:
        targets = [lo]
    else:
        targets = [lo + (hi - lo) * i / max(n_points - 1, 1) for i in range(n_points)]

    frontier = []
    for tr in targets:
        p = _solve(mu, cov, long_only, target_return=tr, rf=rf)
        p["target_return"] = round(tr, 6)
        frontier.append(p)

    mv = min_variance_portfolio(assets_returns, long_only=long_only, rf=rf)
    ms = max_sharpe_portfolio(assets_returns, long_only=long_only, rf=rf)
    eq = _solve(mu, cov, long_only, target_return=None, rf=rf)  # 等权仅作参考在端点层构造
    # 等权组合的绩效（直接按 1/n 计算）
    w_eq = np.full(n, 1.0 / n)
    eq_ret = float(w_eq @ mu)
    eq_vol = float(np.sqrt(max(w_eq @ cov @ w_eq, 0.0)))
    eq_sharpe = (eq_ret - rf) / eq_vol if eq_vol > 1e-12 else 0.0
    equal_weight = {
        "weights": [round(float(x), 6) for x in w_eq],
        "expected_return": round(eq_ret, 6),
        "expected_vol": round(eq_vol, 6),
        "sharpe": round(eq_sharpe, 6),
    }

    return {
        "n_assets": n,
        "n_periods": t,
        "min_variance": mv,
        "max_sharpe": ms,
        "equal_weight": equal_weight,
        "frontier": frontier,
    }
