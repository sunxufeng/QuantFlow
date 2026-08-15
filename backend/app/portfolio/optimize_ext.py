"""组合优化增强（V32–V36）：与 backtest/portfolio_opt 的均值-方差优化互补。

提供四类「风险/分散度驱动」的权重求解，以及两个组合运营工具：
- V32 风险平价（Equal Risk Contribution, ERC）：各资产风险贡献相等。
- V33 最大分散化（Maximum Diversification）：最大化分散化比率 (w·σ)/√(wᵀΣw)。
- V34 层次风险平价（HRP, López de Prado）：相关性聚类 → 递归二分风险平价。
- V35 组合再平衡引擎：按漂移阈值生成调仓交易单（含不交易带判断）。
- V36 风格因子暴露归因：把组合权重映射到价值/成长/规模/动量/波动等风格暴露。

所有函数均为纯函数，输入协方差矩阵（或收益矩阵）即可离线运行、可单测。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np

from ..market import synthetic

STYLE_FACTORS = ["value", "growth", "size", "momentum", "volatility"]


# ----------------------------- 输入解析工具 -----------------------------

def resolve_returns(
    assets: Optional[List[str]] = None,
    returns: Optional[Sequence[Sequence[float]]] = None,
    universe: Optional[List[str]] = None,
    start: str = "2023-01-01",
    end: str = "2023-12-31",
    source: str = "synthetic",
    seed: int = 12345,
) -> (List[str], np.ndarray):
    """统一解析资产收益矩阵。

    优先使用显式 ``returns``（行为时间、列为资产）；否则用合成 GBM 生成。
    返回 (assets, R)，R 为 (T, n) 收益矩阵。
    """
    if returns is not None and assets is not None:
        R = np.array(returns, dtype=float)
        if R.ndim != 2 or R.shape[1] != len(assets):
            raise ValueError("returns 的列数必须与 assets 数量一致")
        return list(assets), R
    syms = list(universe or assets or [])
    if not syms:
        raise ValueError("需提供 assets+returns，或 universe+start+end 以合成行情")
    if source == "synthetic":
        data = synthetic.generate_universe(syms, start, end, seed=seed)
    else:
        from ..market.service import market_service
        data = {}
        for sym in syms:
            bars = market_service.bars(sym, start=start, end=end, interval="daily")
            if not bars:
                raise ValueError(f"标的 {sym} 无行情（live 模式需先入库，或用 source=synthetic）")
            data[sym] = bars
    # 对齐公共交易日并计算当日收益
    date_sets = [set(str(b["date"] if isinstance(b, dict) else getattr(b, "date")) for b in bars) for bars in data.values()]
    common = sorted(set.intersection(*date_sets)) if date_sets else []
    if len(common) < 3:
        raise ValueError("公共交易日不足，无法估计协方差")
    cols = []
    for sym in syms:
        bars = data[sym]
        df = [{ "date": (b["date"] if isinstance(b, dict) else getattr(b, "date")), "close": float(b["close"] if isinstance(b, dict) else getattr(b, "close")) } for b in bars]
        df = sorted(df, key=lambda x: x["date"])
        closes = [x["close"] for x in df if x["date"] in common]
        rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
        cols.append(rets)
    R = np.array(cols, dtype=float).T  # (T-1, n)
    R = R[~np.any(np.isnan(R), axis=1)]
    return syms, R


def _cov_from_returns(R: np.ndarray, shrinkage: float = 0.0) -> np.ndarray:
    """样本协方差 + 可选收缩（Ledoit-Wolf 风格对角收缩）以 stabilizer 非正定。"""
    if R.shape[0] < 2:
        raise ValueError("收益样本不足，无法估计协方差")
    cov = np.cov(R, rowvar=False)
    cov = np.atleast_2d(cov)
    if shrinkage > 0:
        cov = (1 - shrinkage) * cov + shrinkage * np.diag(np.diag(cov))
    # 数值稳定：确保对称正定
    cov = (cov + cov.T) / 2.0
    min_eig = np.linalg.eigvalsh(cov).min()
    if min_eig < 1e-12:
        cov = cov + (abs(min_eig) + 1e-10) * np.eye(cov.shape[0])
    return cov


# ----------------------------- V32 风险平价 (ERC) -----------------------------

def risk_parity_weights(
    cov: np.ndarray,
    budgets: Optional[Sequence[float]] = None,
    max_iter: int = 5000,
    tol: float = 1e-12,
) -> np.ndarray:
    """风险预算（Risk Budgeting）权重；budgets 均等即 ERC 风险平价。

    采用 Spinu (2013) 循环坐标下降（CCD）：逐资产更新
    w_i = b_i / (Σw)_i（其余权重固定），单调收敛到唯一 ERC 解，
    不会像「同时更新不动点」那样塌缩到角点解。
    """
    cov = np.asarray(cov, dtype=float)
    n = cov.shape[0]
    if budgets is None:
        budgets = np.ones(n) / n
    else:
        budgets = np.asarray(budgets, dtype=float)
        s = budgets.sum()
        if s <= 0:
            raise ValueError("budgets 之和必须为正数")
        budgets = budgets / s
    w = np.ones(n) / n
    sw = cov @ w
    for _ in range(max_iter):
        max_delta = 0.0
        for i in range(n):
            a = cov[i, i]
            bcoef = sw[i] - a * w[i]  # (Σw)_i 中不含 w_i 自身的部分
            if a > 1e-14:
                disc = bcoef ** 2 + 4.0 * a * budgets[i]
                w_new = (-bcoef + math.sqrt(max(disc, 0.0))) / (2.0 * a)
            else:
                denom = bcoef if abs(bcoef) > 1e-14 else 1e-14
                w_new = budgets[i] / denom
            w_new = max(w_new, 0.0)
            delta = abs(w_new - w[i])
            if delta > max_delta:
                max_delta = delta
            sw = sw + cov[:, i] * (w_new - w[i])
            w[i] = w_new
        if max_delta < tol:
            break
    s = w.sum()
    if s <= 0:
        return np.ones(n) / n
    return w / s


def risk_contributions(weights: np.ndarray, cov: np.ndarray) -> np.ndarray:
    """各资产的风险贡献 RC_i = w_i (Σw)_i / (wᵀΣw)。"""
    w = np.asarray(weights, dtype=float)
    sw = cov @ w
    tot = float(w @ sw)
    if tot <= 0:
        return np.zeros_like(w)
    return w * sw / tot


# ----------------------------- V33 最大分散化 -----------------------------

def max_diversification_weights(cov: np.ndarray) -> np.ndarray:
    """最大分散化组合：最大化 DR(w) = (w·σ)/√(wᵀΣw)，w≥0，Σw=1。

    用 scipy SLSQP 求解（无解析闭式）；退化时回退逆波动组合。
    """
    try:
        from scipy.optimize import minimize
    except Exception:
        return inverse_volatility_weights(cov)
    cov = np.asarray(cov, dtype=float)
    n = cov.shape[0]
    sigma = np.sqrt(np.diag(cov))
    sigma = np.where(sigma < 1e-12, 1e-12, sigma)

    def neg_dr(w):
        s = float(w @ sigma)
        q = math.sqrt(max(float(w @ cov @ w), 1e-18))
        return -s / q

    x0 = sigma ** -1
    x0 = x0 / x0.sum()
    cons = [{"type": "eq", "fun": lambda w: w.sum() - 1.0}]
    bounds = [(0.0, 1.0)] * n
    res = minimize(neg_dr, x0, method="SLSQP", bounds=bounds, constraints=cons,
                   options={"maxiter": 500, "ftol": 1e-12})
    w = res.x if res.success else x0
    w = np.maximum(w, 0.0)
    return w / w.sum()


def inverse_volatility_weights(cov: np.ndarray) -> np.ndarray:
    sigma = np.sqrt(np.diag(np.asarray(cov, dtype=float)))
    sigma = np.where(sigma < 1e-12, 1e-12, sigma)
    w = 1.0 / sigma
    return w / w.sum()


def diversification_ratio(weights: np.ndarray, cov: np.ndarray) -> float:
    w = np.asarray(weights, dtype=float)
    sigma = np.sqrt(np.diag(np.asarray(cov, dtype=float)))
    s = float(w @ sigma)
    q = math.sqrt(max(float(w @ cov @ w), 1e-18))
    return s / q


# ----------------------------- V34 层次风险平价 (HRP) -----------------------------

def hierarchical_risk_parity(cov: np.ndarray) -> np.ndarray:
    """层次风险平价（López de Prado 2016）：相关性聚类 → 递归二分风险平价。"""
    try:
        from scipy.cluster.hierarchy import linkage, leaves_list
        from scipy.spatial.distance import squareform, pdist
    except Exception:
        return risk_parity_weights(cov)
    cov = np.asarray(cov, dtype=float)
    n = cov.shape[0]
    if n == 1:
        return np.array([1.0])
    sigma = np.sqrt(np.diag(cov))
    sigma = np.where(sigma < 1e-12, 1e-12, sigma)
    corr = cov / np.outer(sigma, sigma)
    corr = np.clip(corr, -0.999, 0.999)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0, 2))
    condensed = squareform(dist, checks=False)
    condensed = np.nan_to_num(condensed, nan=0.0)
    try:
        Z = linkage(condensed, method="single")
        order = leaves_list(Z)
    except Exception:
        order = list(range(n))
    # 按聚类顺序重排协方差，对重排后的序列做递归二分风险平价
    seriated_cov = cov[np.ix_(order, order)]
    seriated_var = np.diag(seriated_cov)

    def _rec(i, j):
        if j - i == 1:
            return np.array([1.0])
        mid = (i + j) // 2
        var_l = float(np.sum(seriated_var[i:mid])) if mid > i else 1e-12
        var_r = float(np.sum(seriated_var[mid:j])) if j > mid else 1e-12
        total = var_l + var_r
        if total <= 0:
            wl = wr = 0.5
        else:
            wl = (1.0 / var_l) / (1.0 / var_l + 1.0 / var_r)
            wr = 1.0 - wl
        wl = max(wl, 0.0); wr = max(wr, 0.0)
        s = wl + wr
        wl /= s; wr /= s
        left = _rec(i, mid) * wl
        right = _rec(mid, j) * wr
        return np.concatenate([left, right])
    w_ordered = _rec(0, n)
    w = np.empty(n)
    w[order] = w_ordered
    return np.maximum(w, 0.0) / np.maximum(w.sum(), 1e-18)


# ----------------------------- V35 组合再平衡引擎 -----------------------------

def rebalance_plan(
    current_weights: Dict[str, float],
    target_weights: Dict[str, float],
    threshold: float = 0.0,
    base_value: float = 1_000_000.0,
) -> Dict:
    """根据当前权重与目标权重生成调仓计划。

    - ``threshold``：单边漂移阈值（占比）；超过阈值才调仓（不交易带）。
    - 返回：每资产漂移、是否越界、交易单（买/卖、金额、目标权重）、汇总。
    """
    if not target_weights:
        raise ValueError("target_weights 不能为空")
    assets = list(dict.fromkeys(list(current_weights.keys()) + list(target_weights.keys())))
    cur = {a: float(current_weights.get(a, 0.0)) for a in assets}
    tgt = {a: float(target_weights.get(a, 0.0)) for a in assets}
    tgt_sum = sum(tgt.values())
    if abs(tgt_sum - 1.0) > 1e-6:
        # 归一化目标
        if tgt_sum <= 0:
            raise ValueError("target_weights 之和必须为正数")
        tgt = {a: v / tgt_sum for a, v in tgt.items()}
    trades = []
    breaches = []
    for a in assets:
        c = cur[a]; t = tgt[a]
        drift = c - t
        breached = abs(drift) > threshold + 1e-9
        if breached:
            side = "sell" if drift > 0 else "buy"
            trades.append({
                "asset": a,
                "side": side,
                "current_weight": round(c, 6),
                "target_weight": round(t, 6),
                "drift": round(drift, 6),
                "trade_value": round(-drift * base_value, 2),
            })
            breaches.append(a)
    # 汇总：买/卖总额、需要再平衡的资产数
    buy = sum(x["trade_value"] for x in trades if x["side"] == "buy")
    sell = sum(-x["trade_value"] for x in trades if x["side"] == "sell")
    return {
        "base_value": base_value,
        "threshold": threshold,
        "n_assets": len(assets),
        "n_breached": len(breaches),
        "breached_assets": breaches,
        "trades": trades,
        "summary": {
            "total_buy": round(buy, 2),
            "total_sell": round(sell, 2),
            "net_cash": round(sell - buy, 2),
        },
    }


# ----------------------------- V36 风格因子暴露归因 -----------------------------

def style_exposure(
    weights: Dict[str, float],
    factor_betas: Dict[str, Dict[str, float]],
    factors: Optional[List[str]] = None,
) -> Dict:
    """把组合权重映射到风格因子暴露（默认价值/成长/规模/动量/波动）。

    factor_betas[asset] = {value:.., growth:.., size:.., momentum:.., volatility:..}
    返回每因子组合暴露、各资产对因子暴露的贡献度。
    """
    factors = list(factors or STYLE_FACTORS)
    assets = list(weights.keys())
    wsum = sum(weights.values())
    if wsum <= 0:
        raise ValueError("weights 之和必须为正数")
    norm = {a: weights[a] / wsum for a in assets}
    expo: Dict[str, float] = {f: 0.0 for f in factors}
    contributions = []
    for a in assets:
        beta = factor_betas.get(a, {})
        w = norm[a]
        contrib = {f: round(w * float(beta.get(f, 0.0)), 6) for f in factors}
        for f in factors:
            expo[f] += contrib[f]
        contributions.append({
            "asset": a,
            "weight": round(w, 6),
            "exposure": contrib,
        })
    return {
        "factors": factors,
        "portfolio_exposure": {f: round(expo[f], 6) for f in factors},
        "contributions": contributions,
    }
