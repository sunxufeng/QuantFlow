"""因子工程深化（V37–V41）：与 factors/analyzer(IC/衰减) 与 factors/backtest(多空回测) 互补。

- V37 因子正交化：把一个因子对其余因子做回归取残差（去冗余），或全体 Gram-Schmidt 正交基。
- V38 因子择时：波动率择时（Barroso-Santa-Clara）按 1/vol 缩放暴露，对比择时 vs 静态夏普。
- V39 因子拥挤度：自相关 + 波动构造拥挤指数（高自相关≈趋势拥挤）。
- V40 多因子合成：等权 / 逆波动 / 正交 三种合成方式，输出合成收益与指标。
- V41 因子换手率与稳定性：横截面排名换手率（Kahn）与排名自相关（稳定性）。

所有函数均为纯函数，输入因子收益序列（dict 因子名→序列）或因子值矩阵即可离线运行。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np


# ----------------------------- 工具 -----------------------------

def _align(factor_returns: Dict[str, Sequence[float]]):
    names = list(factor_returns.keys())
    if not names:
        raise ValueError("factor_returns 不能为空")
    arrs = [np.asarray(v, dtype=float) for v in factor_returns.values()]
    minlen = min(len(a) for a in arrs)
    if minlen < 3:
        raise ValueError("因子序列长度不足（至少 3 期）")
    M = np.column_stack([a[-minlen:] for a in arrs])
    return names, M


def _sharpe(r: np.ndarray) -> float:
    r = np.asarray(r, dtype=float)
    if len(r) < 2:
        return 0.0
    sd = float(np.std(r, ddof=0))
    if sd < 1e-12:
        return 0.0
    return float(np.mean(r) * 252 / (sd * math.sqrt(252)))


def _max_drawdown(cum: Sequence[float]) -> float:
    peak = -1e9
    mdd = 0.0
    for v in cum:
        if v > peak:
            peak = v
        mdd = min(mdd, v - peak)
    return mdd


def _composite_result(names, comp, method, weights=None):
    comp = np.asarray(comp, dtype=float)
    ann = float(np.mean(comp) * 252) if len(comp) else 0.0
    sd = float(np.std(comp, ddof=0)) if len(comp) > 1 else 0.0
    sharpe = ann / sd / math.sqrt(252) if sd > 1e-12 else 0.0
    mdd = _max_drawdown(list(np.cumprod(1.0 + comp)))
    out = {
        "method": method,
        "composite_returns": [round(float(x), 6) for x in comp],
        "metrics": {
            "ann_return": round(ann, 6),
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(mdd, 6),
            "n": len(comp),
        },
    }
    if weights is not None:
        out["weights"] = weights
    return out


# ----------------------------- V37 因子正交化 -----------------------------

def orthogonalize_factor(target: str, factor_returns: Dict[str, Sequence[float]]) -> Dict:
    """把目标因子对其余因子做 OLS 回归取残差（去除与其他因子的线性冗余）。

    返回正交化序列（默认标准化）及与原序列的相关性（应接近 0，说明冗余已剔除）。
    """
    if target not in factor_returns:
        raise ValueError(f"target 因子 {target} 不在 factor_returns 中")
    if len(factor_returns) < 2:
        raise ValueError("正交化需要至少 2 个因子（目标 + 控制变量）")
    names, M = _align(factor_returns)
    idx = names.index(target)
    y = M[:, idx]
    others = np.delete(M, idx, axis=1)
    X = np.column_stack([np.ones(others.shape[0]), others])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    sd = float(np.std(resid, ddof=0)) or 1.0
    resid = resid / sd
    corr = float(np.corrcoef(resid, y)[0, 1]) if (np.std(resid) > 0 and np.std(y) > 0) else 0.0
    return {
        "target": target,
        "controls": [n for n in names if n != target],
        "orthogonal_series": [round(float(x), 6) for x in resid],
        "corr_with_original": round(corr, 4),
    }


def orthogonalize_all(factor_returns: Dict[str, Sequence[float]]) -> Dict:
    """全体因子 Gram-Schmidt 正交化，得到互不相关的正交因子基。"""
    names, M = _align(factor_returns)
    n = M.shape[1]
    orth = np.zeros_like(M)
    for i in range(n):
        v = M[:, i].copy().astype(float)
        for j in range(i):
            denom = float(np.dot(orth[:, j], orth[:, j]))
            if denom > 1e-18:
                v = v - (np.dot(orth[:, j], M[:, i]) / denom) * orth[:, j]
        norm = np.linalg.norm(v)
        orth[:, i] = v / norm if norm > 1e-12 else np.zeros_like(v)
    return {
        "names": names,
        "orthogonal_factors": {names[i]: [round(float(x), 6) for x in orth[:, i]] for i in range(n)},
    }


# ----------------------------- V38 因子择时 -----------------------------

def factor_timing(factor_returns: Dict[str, Sequence[float]], method: str = "vol", halflife: int = 21) -> Dict:
    """波动率择时（Barroso-Santa-Clara）：权重 w_t = 1/EWMA-vol_t，对比择时与静态夏普。

    高波动期自动降仓，降低回撤、提升风险调整收益。
    """
    if method != "vol":
        raise ValueError("目前仅支持 method='vol'（波动率择时）")
    names, M = _align(factor_returns)
    r = M[:, 0]
    var = np.zeros(len(r))
    var[0] = r[0] ** 2
    alpha = 1.0 - math.exp(-1.0 / max(halflife, 1))
    for t in range(1, len(r)):
        var[t] = (1.0 - alpha) * var[t - 1] + alpha * r[t - 1] ** 2
    vol = np.sqrt(np.maximum(var, 1e-12))
    w = 1.0 / vol
    w = w / float(w.mean())
    timed = r * w
    return {
        "method": method,
        "halflife": halflife,
        "weights": [round(float(x), 4) for x in w],
        "timed_returns": [round(float(x), 6) for x in timed],
        "static_sharpe": round(_sharpe(r), 4),
        "timed_sharpe": round(_sharpe(timed), 4),
        "avg_weight": round(float(w.mean()), 4),
        "weight_std": round(float(w.std()), 4),
    }


# ----------------------------- V39 因子拥挤度 -----------------------------

def factor_crowding(factor_returns: Dict[str, Sequence[float]], lags: Sequence[int] = (1, 2)) -> Dict:
    """因子拥挤度：以收益自相关（lag1/lag2）+ 波动构造 0–100 拥挤指数。

    自相关越高（趋势追随型资金扎堆）越拥挤；指数越高风险越大。
    """
    names, M = _align(factor_returns)
    r = M[:, 0]
    ac = {}
    for L in lags:
        if len(r) > L + 1:
            ac[f"autocorr_lag{L}"] = round(float(np.corrcoef(r[:-L], r[L:])[0, 1]), 4)
        else:
            ac[f"autocorr_lag{L}"] = None
    vol = float(np.std(r, ddof=0))
    ac1 = ac.get("autocorr_lag1") or 0.0
    crowding = round(min(abs(ac1), 1.0) * 100, 2)
    mdd = _max_drawdown(list(np.cumprod(1.0 + r)))
    return {
        "autocorr": ac,
        "volatility": round(vol, 6),
        "crowding_index": crowding,
        "max_drawdown": round(mdd, 4),
        "interpretation": "高拥挤(>60)：趋势追随资金扎堆，警惕反转；低拥挤(<30)：因子较分散",
    }


# ----------------------------- V40 多因子合成 -----------------------------

def combine_factors(factor_returns: Dict[str, Sequence[float]], method: str = "equal", weights: Optional[Sequence[float]] = None) -> Dict:
    """多因子合成：等权 / 逆波动 / 正交。

    - equal：简单等权平均
    - vol_inverse：按历史波动倒数加权（低风险因子权重高）
    - orthogonal：先 Gram-Schmidt 正交化再等权合成（剔除共线、降低集中度）
    """
    names, M = _align(factor_returns)
    n = M.shape[1]
    if method == "equal":
        w = np.ones(n) / n
        return _composite_result(names, M @ w, method, {nm: round(float(x), 4) for nm, x in zip(names, w)})
    if method == "vol_inverse":
        vols = np.std(M, axis=0, ddof=0)
        vols = np.where(vols < 1e-12, 1e-12, vols)
        w = (1.0 / vols)
        w = w / w.sum()
        return _composite_result(names, M @ w, method, {nm: round(float(x), 4) for nm, x in zip(names, w)})
    if method == "orthogonal":
        orth_res = orthogonalize_all(factor_returns)
        O = np.column_stack([np.asarray(v, dtype=float) for v in orth_res["orthogonal_factors"].values()])
        comp = O.mean(axis=1)
        return _composite_result(names, comp, method)
    if method == "custom":
        if weights is None or len(weights) != n:
            raise ValueError("custom 需提供与因子数一致的 weights")
        w = np.asarray(weights, dtype=float)
        s = w.sum()
        if s <= 0:
            raise ValueError("weights 之和须为正")
        w = w / s
        return _composite_result(names, M @ w, method, {nm: round(float(x), 4) for nm, x in zip(names, w)})
    raise ValueError("method 须为 equal/vol_inverse/orthogonal/custom")


# ----------------------------- V41 因子换手率与稳定性 -----------------------------

def factor_turnover(factor_values: Dict[str, Sequence[float]]) -> Dict:
    """因子换手率与稳定性：基于横截面排名。

    - 换手率：相邻期排名绝对差之和 / n^2（Kahn 定义，0–1），越低越稳。
    - 稳定性：相邻期排名向量的相关系数，越高说明因子排序越持久。
    """
    assets = list(factor_values.keys())
    if len(assets) < 2:
        raise ValueError("factor_values 至少需 2 个资产")
    arrs = [np.asarray(v, dtype=float) for v in factor_values.values()]
    minlen = min(len(a) for a in arrs)
    if minlen < 3:
        raise ValueError("因子值序列长度不足（至少 3 期）")
    M = np.column_stack([a[-minlen:] for a in arrs])  # (T, n)
    T, n = M.shape
    ranks = np.vstack([np.argsort(np.argsort(M[t])) for t in range(T)])
    turnovers = []
    corrs = []
    for t in range(1, T):
        turnovers.append(float(np.abs(ranks[t] - ranks[t - 1]).sum()) / (n * n))
        c = np.corrcoef(ranks[t - 1], ranks[t])[0, 1]
        corrs.append(0.0 if np.isnan(c) else float(c))
    return {
        "n_assets": n,
        "avg_turnover": round(float(np.mean(turnovers)), 4),
        "turnover_series": [round(x, 4) for x in turnovers],
        "stability": round(float(np.mean(corrs)), 4),
    }
