"""风险归因与因子风险模型（V77–V81）：在 risk.analytics（VaR/CVaR/回撤）之上补充
组合层面的风险分解与归因能力。

五个纯函数（输入矩阵/向量即可离线运行、可单测）：
- V77 因子风险分解：把组合方差拆为「因子风险 + 特异性风险」，并给出每个因子的风险贡献。
- V78 因子收益归因：把组合收益按因子暴露分解为各因子收益贡献 + 特异性收益。
- V79 成分 VaR / 边际风险：基于 Euler 分配把组合 CVaR 分配到各资产（成分 VaR 之和 = 组合 CVaR）。
- V80 风险分解树：按分组标签（资产/行业/因子）聚合风险贡献，形成层级视图。
- V81 尾部风险指标：Sortino / 下行半方差 / Calmar / Omega / 尾部比率等统一快照。

所有函数均为纯函数，不依赖数据库或网络；协方差保证正定、权重归一。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np


def _psd(cov: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    cov = np.asarray(cov, dtype=float)
    cov = (cov + cov.T) / 2.0
    min_eig = np.linalg.eigvalsh(cov).min()
    if min_eig < eps:
        cov = cov + (abs(min_eig) + eps) * np.eye(cov.shape[0])
    return cov


def _as_weights(x: np.ndarray) -> np.ndarray:
    x = np.asarray(x, dtype=float)
    s = float(x.sum())
    if s <= 0 or not np.isfinite(s):
        n = x.shape[0]
        return np.ones(n) / n
    return x / s


# ----------------------------- V77 因子风险分解 -----------------------------

def factor_risk_decomposition(
    weights: Sequence[float],
    factor_exposures: Sequence[Sequence[float]],
    factor_cov: Sequence[Sequence[float]],
    specific_var: Optional[Sequence[float]] = None,
    factor_names: Optional[List[str]] = None,
) -> Dict:
    """因子风险模型：组合方差 = 因子方差 + 特异性方差。

    参数
    ----
    weights : (n,) 组合权重。
    factor_exposures : (n, k) 暴露矩阵 B。
    factor_cov : (k, k) 因子协方差 F。
    specific_var : (n,) 特异性方差 diag(D)；省略则取各资产残差方差的默认值 1%。
    factor_names : (k,) 因子名。

    返回
    ----
    { "total_variance", "factor_variance", "specific_variance", "pct_factor",
      "factor_contrib", "factor_contrib_pct", "factor_names" }
    """
    w = np.asarray(weights, dtype=float)
    B = np.asarray(factor_exposures, dtype=float)
    n, k = B.shape
    if w.shape[0] != n:
        raise ValueError("weights 长度必须与暴露行数一致")
    F = np.asarray(factor_cov, dtype=float)
    if F.ndim != 2 or F.shape[0] != k or F.shape[1] != k:
        raise ValueError("factor_cov 必须为 k×k 且与因子数一致")
    F = _psd(F)
    names = list(factor_names) if factor_names else [f"F{i}" for i in range(k)]
    if len(names) != k:
        raise ValueError("factor_names 数量必须与因子数一致")

    if specific_var is None:
        D = np.diag(np.full(n, 0.01))
    else:
        sv = np.asarray(specific_var, dtype=float)
        if sv.shape[0] != n:
            raise ValueError("specific_var 长度必须与资产数一致")
        D = np.diag(np.maximum(sv, 0.0))

    # 组合因子暴露 f = Bᵀw
    f = B.T @ w  # (k,)
    factor_var = float(f @ F @ f)
    # 特异性方差 = wᵀ D w
    specific_var_total = float(w @ D @ w)
    total_var = factor_var + specific_var_total

    # 每个因子的风险贡献：对因子协方差的第 j 项，贡献 = f_j * (F f)_j / total_var（占比）
    Ff = F @ f
    contrib = f * Ff  # (k,) 各因子对因子方差的贡献
    contrib_pct = contrib / total_var if total_var > 0 else np.zeros(k)

    return {
        "total_variance": total_var,
        "factor_variance": factor_var,
        "specific_variance": specific_var_total,
        "pct_factor": (factor_var / total_var) if total_var > 0 else 0.0,
        "factor_contrib": contrib.tolist(),
        "factor_contrib_pct": contrib_pct.tolist(),
        "factor_names": names,
    }


# ----------------------------- V78 因子收益归因 -----------------------------

def factor_return_attribution(
    weights: Sequence[float],
    factor_exposures: Sequence[Sequence[float]],
    factor_returns: Sequence[Sequence[float]],
    specific_returns: Optional[Sequence[float]] = None,
    factor_names: Optional[List[str]] = None,
) -> Dict:
    """因子收益归因：把组合收益分解为各因子收益贡献 + 特异性收益。

    组合收益序列 r_t = wᵀ(B f_t + u_t)，其中 B f_t 为因子部分、u_t 为特异性。
    各因子贡献 = wᵀ B_col_j * mean(f_{j,t})（即组合对该因子的暴露 × 因子平均收益）。
    特异性贡献 = wᵀ mean(u_t)。

    参数
    ----
    weights : (n,)
    factor_exposures : (n, k) B
    factor_returns : (T, k) 因子收益
    specific_returns : (T,) 或 (n,) 特异性收益序列；省略则视为 0。
    factor_names : (k,)

    返回
    ----
    { "total_return", "factor_contrib", "specific_contrib", "factor_contrib_pct",
      "factor_names", "n_periods" }
    """
    w = np.asarray(weights, dtype=float)
    B = np.asarray(factor_exposures, dtype=float)
    Fret = np.asarray(factor_returns, dtype=float)
    n, k = B.shape
    if w.shape[0] != n:
        raise ValueError("weights 长度必须与暴露行数一致")
    if Fret.ndim != 2 or Fret.shape[1] != k:
        raise ValueError("factor_returns 列数必须等于因子数")
    names = list(factor_names) if factor_names else [f"F{i}" for i in range(k)]
    if len(names) != k:
        raise ValueError("factor_names 数量必须与因子数一致")

    f_mean = Fret.mean(axis=0)  # (k,)
    # 组合对每个因子的暴露（金额暴露）
    port_factor_exp = B.T @ w  # (k,) = Σ_i w_i B_ij
    factor_contrib = port_factor_exp * f_mean  # (k,)

    if specific_returns is not None:
        sp = np.asarray(specific_returns, dtype=float)
        if sp.ndim == 1 and sp.shape[0] == n:
            # 逐资产特异性收益 -> 组合特异性收益
            specific_contrib = float(w @ sp)
        else:
            # 视为组合层面的特异性收益序列 -> 取均值
            specific_contrib = float(np.asarray(specific_returns, dtype=float).mean())
    else:
        specific_contrib = 0.0

    total = float(factor_contrib.sum() + specific_contrib)
    contrib_pct = factor_contrib / total if abs(total) > 1e-12 else np.zeros(k)

    return {
        "total_return": total,
        "factor_contrib": factor_contrib.tolist(),
        "specific_contrib": specific_contrib,
        "factor_contrib_pct": contrib_pct.tolist(),
        "factor_names": names,
        "n_periods": int(Fret.shape[0]),
    }


# ----------------------------- V79 成分 VaR / 边际风险 -----------------------------

def component_var(
    returns: Sequence[Sequence[float]],
    weights: Optional[Sequence[float]] = None,
    alpha: float = 0.05,
) -> Dict:
    """成分 VaR（Euler 分配）：把组合 CVaR 分配到各资产。

    采用历史模拟法估计组合收益，成分 VaR_i = w_i * ∂CVaR/∂w_i，
    近似用条件期望：CVaR_i = E[r_i | r_port ≤ VaR_α] / (1-α) 的加权，
    使 Σ_i 成分VaR_i = 组合 CVaR。同时输出边际 VaR（对组合收益的敏感度）。

    参数
    ----
    returns : (T, n) 资产收益矩阵。
    weights : (n,) 组合权重（默认等权）。
    alpha : 置信水平（默认 0.05，即 95% VaR）。

    返回
    ----
    { "alpha", "portfolio_cvar", "portfolio_var", "component_var",
      "marginal_var", "component_var_pct", "n_assets" }
    """
    R = np.asarray(returns, dtype=float)
    if R.ndim != 2:
        raise ValueError("returns 必须为 (T, n) 矩阵")
    T, n = R.shape
    w = _as_weights(np.array(weights)) if weights is not None else np.ones(n) / n
    if w.shape[0] != n:
        raise ValueError("weights 长度必须等于资产数")
    if not (0 < alpha < 1):
        raise ValueError("alpha 必须落在 (0,1)")

    port = R @ w  # (T,)
    var_thr = float(np.quantile(port, alpha))
    tail = port <= var_thr
    if tail.sum() == 0:
        tail = port <= np.min(port)
    cvar_port = float(port[tail].mean())

    # 边际 VaR：组合收益对资产 i 权重的敏感度（历史组合收益对资产收益的回归系数）
    # 用协方差近似：marginal_i = Cov(r_i, r_port) / Var(r_port)
    cov_ip = R.T @ (port - port.mean()) / max(T - 1, 1)  # (n,)
    var_port = float(port.var(ddof=1)) if T > 1 else 0.0
    if var_port <= 0:
        marginal = np.zeros(n)
    else:
        marginal = cov_ip / var_port

    # 成分 VaR：在尾部条件下，资产 i 的条件期望贡献占比
    cond_mean = np.array([R[tail, i].mean() if tail.sum() > 0 else 0.0 for i in range(n)])
    comp = w * cond_mean / (1.0 - alpha) / max(abs(cvar_port), 1e-12)
    # 归一化使 Σ 成分VaR = 组合 CVaR
    comp_sum = float(comp.sum())
    if abs(comp_sum) > 1e-12:
        comp = comp * (cvar_port / comp_sum)
    else:
        comp = np.zeros(n)

    comp_pct = comp / cvar_port if abs(cvar_port) > 1e-12 else np.zeros(n)

    return {
        "alpha": alpha,
        "portfolio_var": var_thr,
        "portfolio_cvar": cvar_port,
        "component_var": comp.tolist(),
        "marginal_var": marginal.tolist(),
        "component_var_pct": comp_pct.tolist(),
        "n_assets": n,
    }


# ----------------------------- V80 风险分解树 -----------------------------

def risk_decomposition_tree(
    weights: Sequence[float],
    cov: Sequence[Sequence[float]],
    groups: Sequence[str],
    asset_names: Optional[List[str]] = None,
) -> Dict:
    """按分组标签聚合风险贡献，形成层级视图。

    单个资产的风险贡献 RC_i = w_i (Σw)_i / (wᵀΣw)；按 group 汇总得到组风险贡献。

    参数
    ----
    weights : (n,)
    cov : (n, n)
    groups : (n,) 每个资产的分组标签（如行业/因子/账户）。
    asset_names : (n,)

    返回
    ----
    { "total_variance", "per_asset", "by_group", "group_pct", "groups",
      "asset_names", "n_assets" }
    """
    w = np.asarray(weights, dtype=float)
    C = _psd(cov)
    n = w.shape[0]
    if C.shape[0] != n:
        raise ValueError("cov 维度必须与权重长度一致")
    if len(groups) != n:
        raise ValueError("groups 长度必须与资产数一致")
    names = list(asset_names) if asset_names else [f"A{i}" for i in range(n)]
    if len(names) != n:
        raise ValueError("asset_names 数量必须与资产数一致")

    sw = C @ w
    tot = float(w @ sw)
    if tot <= 0:
        rc = np.zeros(n)
    else:
        rc = w * sw / tot  # 单资产风险贡献（和为 1）

    per_asset = [{"asset": names[i], "group": groups[i], "weight": float(w[i]), "risk_contrib": float(rc[i])} for i in range(n)]

    group_map: Dict[str, float] = {}
    for i in range(n):
        group_map[groups[i]] = group_map.get(groups[i], 0.0) + float(rc[i])
    by_group = {g: v for g, v in sorted(group_map.items(), key=lambda kv: kv[1], reverse=True)}
    g_pct = {g: (v / tot if tot > 0 else 0.0) for g, v in by_group.items()}

    return {
        "total_variance": tot,
        "per_asset": per_asset,
        "by_group": by_group,
        "group_pct": g_pct,
        "groups": list(by_group.keys()),
        "asset_names": names,
        "n_assets": n,
    }


# ----------------------------- V81 尾部风险指标 -----------------------------

def tail_risk_metrics(
    returns: Sequence[float],
    risk_free: float = 0.0,
    periods_per_year: int = 252,
) -> Dict:
    """尾部风险指标统一快照：下行半方差 / Sortino / Calmar / Omega / 尾部比率 / CVaR。

    参数
    ----
    returns : 收益率序列（周期频率，如日）。
    risk_free : 周期无风险收益（默认 0）。
    periods_per_year : 年化因子（默认 252）。

    返回
    ----
    { "n", "mean", "ann_return", "ann_vol", "downside_deviation", "sortino",
      "max_drawdown", "calmar", "omega", "cvar", "tail_ratio", "var" }
    """
    r = np.asarray(returns, dtype=float)
    n = r.shape[0]
    if n < 2:
        raise ValueError("收益序列至少需 2 个观测")
    mean = float(r.mean())
    std = float(r.std(ddof=1))
    ann_ret = mean * periods_per_year
    ann_vol = std * math.sqrt(periods_per_year)

    # 下行偏差（相对无风险）
    downside = np.minimum(r - risk_free, 0.0)
    dd = math.sqrt(float((downside ** 2).mean()))
    sortino = (mean - risk_free) / dd if dd > 0 else 0.0

    # 最大回撤
    eq = np.cumprod(1 + r)
    peak = np.maximum.accumulate(eq)
    dd_series = eq / peak - 1.0
    max_dd = float(dd_series.min())

    calmar = ann_ret / abs(max_dd) if max_dd < 0 else 0.0

    # Omega = P(r > 0) 期望 / P(r < 0) 期望（阈值 0）
    above = r[r > 0]
    below = r[r < 0]
    omega = float(above.sum() / abs(below.sum())) if below.sum() != 0 else float('inf')

    # VaR / CVaR（历史）
    alpha = 0.05
    var = float(np.quantile(r, alpha))
    cvar = float(r[r <= var].mean()) if (r <= var).any() else var

    # 尾部比率 = 右尾(95%)均值 / |左尾(5%)均值|
    up = float(r[r >= np.quantile(r, 0.95)].mean()) if (r >= np.quantile(r, 0.95)).any() else 0.0
    tail_ratio = up / abs(var) if var < 0 else 0.0

    return {
        "n": n,
        "mean": mean,
        "ann_return": ann_ret,
        "ann_vol": ann_vol,
        "downside_deviation": dd,
        "sortino": sortino,
        "max_drawdown": max_dd,
        "calmar": calmar,
        "omega": omega,
        "var": var,
        "cvar": cvar,
        "tail_ratio": tail_ratio,
    }
