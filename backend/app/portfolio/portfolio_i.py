"""组合层面增强（V72–V76）：在 V32–V36 风险/分散度优化之上补充组合级运营能力。

提供五个互补的纯函数（输入矩阵/向量即可离线运行、可单测）：
- V72 Black-Litterman：把市场均衡收益与投资者主观观点融合，输出后验收益与组合权重。
- V73 因子组合构建：以目标因子暴露为约束，求最优主动权重（因子中性 / 因子倾斜）。
- V74 组合压力测试：把情景冲击（预设/自定义/因子冲击）映射到组合 P&L 影响。
- V75 带约束再平衡：当前→目标权重，受换手率上限/最小交易量/个股权重上限/不交易带约束。
- V76 多账户聚合：把多个子账户持仓合并为统一组合，输出资产权重/账户占比/集中度。

所有函数均为纯函数，不依赖数据库或网络；数值上保证协方差正定、权重归一。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np


# ----------------------------- 数值工具 -----------------------------

def _psd(cov: np.ndarray, eps: float = 1e-10) -> np.ndarray:
    """保证对称正定：对称化 + 抬高最小特征值，避免 BL / 优化出现奇异。"""
    cov = np.asarray(cov, dtype=float)
    cov = (cov + cov.T) / 2.0
    min_eig = np.linalg.eigvalsh(cov).min()
    if min_eig < eps:
        cov = cov + (abs(min_eig) + eps) * np.eye(cov.shape[0])
    return cov


def _as_weights(x: np.ndarray) -> np.ndarray:
    """归一化为和为 1 的非负权重；全零时退化为等权。"""
    x = np.asarray(x, dtype=float)
    s = float(x.sum())
    if s <= 0 or not np.isfinite(s):
        n = x.shape[0]
        return np.ones(n) / n
    return x / s


# ----------------------------- V72 Black-Litterman -----------------------------

def black_litterman(
    cov: Sequence[Sequence[float]],
    prior_weights: Optional[Sequence[float]] = None,
    views: Optional[List[Dict]] = None,
    risk_aversion: float = 2.5,
    tau: float = 0.05,
    asset_names: Optional[List[str]] = None,
) -> Dict:
    """Black-Litterman 后验收益与组合权重。

    参数
    ----
    cov : (n, n) 资产收益协方差矩阵。
    prior_weights : (n,) 市场均衡权重（默认等权）；其反优化得到均衡收益 Π = δ Σ w。
    views : 观点列表，每条 { "assets": [idx...], "coefs": [...], "q": 预期值,
            "confidence": 0~1（越高越自信，越大 omega 越小）}。省略 coefs 视为等权。
    risk_aversion : 风险厌恶系数 δ。
    tau : 先验不确定性缩放（通常 0.02~0.1）。

    返回
    ----
    {
      "assets", "prior_weights", "equilibrium_returns",
      "posterior_returns", "posterior_cov", "bl_weights", "views_processed",
    }
    """
    Sigma = _psd(cov)
    n = Sigma.shape[0]
    names = list(asset_names) if asset_names else [f"A{i}" for i in range(n)]
    if len(names) != n:
        raise ValueError("asset_names 数量必须与协方差维度一致")
    w_mkt = _as_weights(np.array(prior_weights)) if prior_weights is not None else np.ones(n) / n
    if w_mkt.shape[0] != n:
        raise ValueError("prior_weights 长度必须与协方差维度一致")

    delta = float(risk_aversion)
    tau = float(tau)
    if tau <= 0:
        raise ValueError("tau 必须为正数")
    Pi = delta * (Sigma @ w_mkt)  # 均衡（超额）收益

    # 处理观点 -> P (k, n), Q (k,), Omega (k, k)
    k = 0
    P_rows: List[np.ndarray] = []
    Q: List[float] = []
    Omega_diag: List[float] = []
    if views:
        for v in views:
            idxs = v.get("assets")
            if not idxs:
                raise ValueError("每条 view 必须包含 assets")
            coefs = v.get("coefs")
            if coefs is None:
                coefs = [1.0] * len(idxs)
            if len(coefs) != len(idxs):
                raise ValueError("view 的 coefs 长度必须与 assets 一致")
            row = np.zeros(n)
            s = sum(abs(c) for c in coefs) or 1.0
            for a, c in zip(idxs, coefs):
                row[a] += c / s
            p_sigma_p = float(row @ Sigma @ row)
            if p_sigma_p <= 0:
                p_sigma_p = 1e-6
            conf = v.get("confidence", 0.5)
            if not (0.0 < conf <= 1.0):
                raise ValueError("view 的 confidence 需落在 (0, 1]")
            # Idzorek 风格：confidence=1 -> omega→0；confidence=0.5 -> omega = tau * pΣp
            omega = tau * p_sigma_p * (1.0 / conf - 1.0)
            P_rows.append(row)
            Q.append(float(v.get("q", 0.0)))
            Omega_diag.append(omega)
            k += 1

    if k == 0:
        # 无观点：后验退化为均衡，组合退化为均衡权重
        return {
            "assets": names,
            "prior_weights": w_mkt.tolist(),
            "equilibrium_returns": Pi.tolist(),
            "posterior_returns": Pi.tolist(),
            "posterior_cov": Sigma.tolist(),
            "bl_weights": w_mkt.tolist(),
            "views_processed": 0,
        }

    P = np.array(P_rows)  # (k, n)
    Qv = np.array(Q)
    Omega = np.diag(Omega_diag)  # (k, k)
    tauS = tau * Sigma

    # 后验均值: ((τΣ)^-1 + PᵀΩ⁻¹P)^-1 ((τΣ)^-1 Π + PᵀΩ⁻¹Q)
    inv_tauS = np.linalg.inv(tauS)
    inv_Omega = np.linalg.inv(Omega)
    M = np.linalg.inv(inv_tauS + P.T @ inv_Omega @ P)
    post_mean = M @ (inv_tauS @ Pi + P.T @ inv_Omega @ Qv)
    # 后验组合权重: w* = (δ Σ)^-1 E[R] （均值-方差最优）
    bl_w = np.linalg.solve(delta * Sigma, post_mean)
    bl_w = _as_weights(bl_w)

    return {
        "assets": names,
        "prior_weights": w_mkt.tolist(),
        "equilibrium_returns": Pi.tolist(),
        "posterior_returns": post_mean.tolist(),
        "posterior_cov": M.tolist(),
        "bl_weights": bl_w.tolist(),
        "views_processed": k,
    }


# ----------------------------- V73 因子组合构建 -----------------------------

def factor_portfolio(
    factor_exposures: Sequence[Sequence[float]],
    target_bets: Optional[Sequence[float]] = None,
    base_weights: Optional[Sequence[float]] = None,
    asset_names: Optional[List[str]] = None,
    method: str = "tilt",
    max_active: float = 0.5,
    long_only: bool = True,
    cov: Optional[Sequence[Sequence[float]]] = None,
) -> Dict:
    """按目标因子暴露构建组合（主动权重）。

    在基准权重 w0 上叠加主动权重 x（Σx=0），使 Bᵀ(w0+x) 逼近目标暴露，
    同时最小化主动暴露偏差；可施加个股权重上下限。

    参数
    ----
    factor_exposures : (n, k) 因子暴露矩阵 B（每列一个因子）。
    target_bets : (k,) 目标因子暴露；省略则取基准暴露（因子中性）。
    base_weights : (n,) 基准权重（默认等权）。
    method : "tilt"（按目标倾斜）或 "neutral"（中性化偏离）。
    max_active : 单只主动权重绝对值上限。
    long_only : True 时 w0+x ≥ 0。
    cov : 可选 (n,n) 协方差，用于计算主动跟踪误差。

    返回
    ----
    { "base_weights", "active_weights", "new_weights", "base_exposure",
      "target_exposure", "achieved_exposure", "tracking_error", "method" }
    """
    B = np.asarray(factor_exposures, dtype=float)
    if B.ndim != 2:
        raise ValueError("factor_exposures 必须是二维矩阵 (n, k)")
    n, k = B.shape
    names = list(asset_names) if asset_names else [f"A{i}" for i in range(n)]
    if len(names) != n:
        raise ValueError("asset_names 数量必须与因子暴露行数一致")
    w0 = _as_weights(np.array(base_weights)) if base_weights is not None else np.ones(n) / n
    if w0.shape[0] != n:
        raise ValueError("base_weights 长度必须与资产数一致")

    base_exp = B.T @ w0  # (k,)
    target = np.array(target_bets, dtype=float) if target_bets is not None else base_exp.copy()
    if target.shape[0] != k:
        raise ValueError("target_bets 长度必须等于因子数")

    # 待实现的主动暴露目标
    d = target - base_exp

    try:
        from scipy.optimize import least_squares
    except Exception:
        # 无 scipy：闭式最小二乘（忽略边界）
        x, *_ = np.linalg.lstsq(B.T, d, rcond=None)
    else:
        lo = -max_active
        hi = max_active
        if long_only:
            # 主动权重下限 = -w0（不允许负权重）
            lo = np.maximum(lo, -w0)
        res = least_squares(lambda x: B.T @ x - d, np.zeros(n), bounds=(lo, hi))
        x = res.x

    x = np.asarray(x, dtype=float)
    new_w = w0 + x
    if long_only:
        new_w = np.maximum(new_w, 0.0)
    new_w = _as_weights(new_w)

    achieved = B.T @ new_w
    tracking_error = None
    if cov is not None:
        C = _psd(cov)
        te = math.sqrt(max(float((new_w - w0) @ C @ (new_w - w0)), 0.0))
        tracking_error = te

    return {
        "assets": names,
        "base_weights": w0.tolist(),
        "active_weights": (new_w - w0).tolist(),
        "new_weights": new_w.tolist(),
        "base_exposure": base_exp.tolist(),
        "target_exposure": target.tolist(),
        "achieved_exposure": achieved.tolist(),
        "tracking_error": tracking_error,
        "method": method,
    }


# ----------------------------- V74 组合压力测试 -----------------------------

_PRESET_SCENARIOS = {
    "gfc_2008": {"股票": -0.50, "权益": -0.50, "成长": -0.55, "价值": -0.45, "小盘": -0.55,
                 "债券": 0.05, "利率债": 0.05, "信用债": -0.10, "黄金": 0.12, "商品": -0.30,
                 "原油": -0.55, "美元": 0.08, "REITs": -0.60, "现金": 0.0, "外汇": -0.05},
    "covid_2020": {"股票": -0.34, "权益": -0.34, "成长": -0.30, "价值": -0.38, "小盘": -0.40,
                   "债券": 0.03, "利率债": 0.06, "信用债": -0.08, "黄金": 0.08, "商品": -0.25,
                   "原油": -0.65, "美元": 0.06, "REITs": -0.42, "现金": 0.0, "外汇": -0.04},
    "rate_hike": {"股票": -0.10, "权益": -0.10, "成长": -0.18, "价值": -0.04, "小盘": -0.12,
                  "债券": -0.08, "利率债": -0.10, "信用债": -0.05, "黄金": -0.06, "商品": 0.04,
                  "原油": 0.02, "美元": 0.05, "REITs": -0.15, "现金": 0.0, "外汇": 0.03},
    "inflation_spike": {"股票": -0.08, "权益": -0.08, "成长": -0.12, "价值": -0.03, "小盘": -0.10,
                        "债券": -0.10, "利率债": -0.12, "信用债": -0.06, "黄金": 0.15, "商品": 0.18,
                        "原油": 0.20, "美元": 0.0, "REITs": -0.05, "现金": 0.0, "外汇": -0.02},
    "liquidity_crunch": {"股票": -0.22, "权益": -0.22, "成长": -0.25, "价值": -0.20, "小盘": -0.28,
                         "债券": 0.02, "利率债": 0.04, "信用债": -0.12, "黄金": -0.04, "商品": -0.18,
                         "原油": -0.30, "美元": 0.10, "REITs": -0.30, "现金": 0.0, "外汇": -0.03},
}


def stress_test(
    weights: Sequence[float],
    asset_names: Optional[List[str]] = None,
    shocks: Optional[Dict[str, float]] = None,
    scenario: Optional[str] = None,
    factor_exposures: Optional[Sequence[Sequence[float]]] = None,
    factor_shocks: Optional[Dict[str, float]] = None,
) -> Dict:
    """组合压力测试：把冲击映射到组合层面的 P&L 影响。

    优先级：显式 shocks > 因子冲击（factor_exposures × factor_shocks）> 预设 scenario。

    参数
    ----
    weights : (n,) 组合权重。
    asset_names : (n,) 资产名称；用于匹配 shocks/scenario 关键字。
    shocks : { 资产名: 冲击百分比 }，直接给出每只资产损益。
    scenario : 预设情景名（gfc_2008/covid_2020/rate_hike/inflation_spike/liquidity_crunch）。
    factor_exposures : (n, k) 因子暴露矩阵，配合 factor_shocks 计算资产冲击 = B·fs。
    factor_shocks : { 因子名: 冲击 }。

    返回
    ----
    { "scenario", "portfolio_pnl_pct", "per_asset_pnl", "worst_asset", "best_asset",
      "shocks_applied" }
    """
    w = _as_weights(np.array(weights))
    n = w.shape[0]
    names = list(asset_names) if asset_names else [f"A{i}" for i in range(n)]
    if len(names) != n:
        raise ValueError("asset_names 数量必须与权重长度一致")

    applied = np.zeros(n)
    used_scenario = scenario or "custom"

    if shocks:
        for i, nm in enumerate(names):
            if nm in shocks:
                applied[i] = float(shocks[nm])
        used_scenario = "custom"
    elif factor_shocks and factor_exposures is not None:
        B = np.asarray(factor_exposures, dtype=float)
        if B.shape[0] != n:
            raise ValueError("factor_exposures 行数必须与权重长度一致")
        fs = np.zeros(B.shape[1])
        for j, _ in enumerate(range(B.shape[1])):
            pass
        # 用列名映射：factor_exposures 可能以 dict 描述，但这里以序号映射；
        # factor_shocks key 可传 "factor_0".. 或直接按列序
        for key, val in factor_shocks.items():
            if key.startswith("factor_"):
                idx = int(key.split("_")[1])
            else:
                idx = int(key)
            fs[idx] = float(val)
        applied = B @ fs
        used_scenario = "factor_shock"
    elif scenario:
        if scenario not in _PRESET_SCENARIOS:
            raise ValueError(f"未知情景 {scenario}，可选：{list(_PRESET_SCENARIOS)}")
        presets = _PRESET_SCENARIOS[scenario]
        for i, nm in enumerate(names):
            # 名称包含关键字即应用对应冲击（取最匹配）
            best = 0.0
            matched = False
            for kw, val in presets.items():
                if kw != "现金" and kw in nm:
                    best = val
                    matched = True
            if matched:
                applied[i] = best
        used_scenario = scenario
    else:
        raise ValueError("必须提供 shocks / scenario / factor_shocks 之一")

    per_asset = w * applied
    total = float(per_asset.sum())
    idx_sorted = np.argsort(per_asset)
    worst_idx = int(idx_sorted[0])
    best_idx = int(idx_sorted[-1])

    return {
        "scenario": used_scenario,
        "portfolio_pnl_pct": total,
        "per_asset_pnl": {nm: float(per_asset[i]) for i, nm in enumerate(names)},
        "shocks_applied": {nm: float(applied[i]) for i, nm in enumerate(names)},
        "worst_asset": names[worst_idx],
        "best_asset": names[best_idx],
        "n_assets": n,
    }


# ----------------------------- V75 带约束再平衡 -----------------------------

def constrained_rebalance(
    current_weights: Sequence[float],
    target_weights: Sequence[float],
    turnover_limit: Optional[float] = None,
    min_trade: float = 0.0,
    max_weight: Optional[float] = None,
    long_only: bool = True,
    no_trade_band: float = 0.0,
) -> Dict:
    """带约束的再平衡：当前→目标权重，受多重约束生成调仓单。

    约束顺序：
    1) 不交易带：|target_i - current_i| ≤ band → 维持 current_i（不调）。
    2) 最小交易量：|target_i - current_i| < min_trade → 维持 current_i。
    3) 个股权重上限：adjusted_i ≤ max_weight。
    4) 换手率上限：Σ|adjusted_i - current_i| ≤ turnover_limit，超限按交易规模等比收缩。
    5) 多空约束：long_only 时权重 ≥ 0。
    最终归一化为和为 1。

    返回
    ----
    { "current_weights", "target_weights", "adjusted_weights", "trades",
      "turnover", "constrained", "n_trades" }
    """
    cur = _as_weights(np.array(current_weights))
    tgt = _as_weights(np.array(target_weights))
    n = cur.shape[0]
    if tgt.shape[0] != n:
        raise ValueError("current/target 权重长度必须一致")

    adj = cur.copy()
    for i in range(n):
        if no_trade_band > 0 and abs(tgt[i] - cur[i]) <= no_trade_band:
            adj[i] = cur[i]
            continue
        if min_trade > 0 and abs(tgt[i] - cur[i]) < min_trade:
            adj[i] = cur[i]
            continue
        adj[i] = tgt[i]

    if max_weight is not None:
        cap = float(max_weight)
        over = adj > cap
        adj = np.where(over, cap, adj)
        # 把被截断释放出的权重按比例重分配给未触顶的资产，避免全局归一化把上限抬高
        excess = 1.0 - float(adj.sum())
        below = adj < cap - 1e-12
        if excess > 1e-12 and below.any():
            wbelow = adj[below]
            s = float(wbelow.sum())
            if s > 0:
                adj[below] = adj[below] + excess * wbelow / s
            else:
                adj[below] = adj[below] + excess / max(int(below.sum()), 1)

    # 换手率约束：等比收缩交易
    constrained = False
    if turnover_limit is not None:
        limit = float(turnover_limit)
        trades = adj - cur
        to = float(np.abs(trades).sum())
        if to > limit and to > 0:
            scale = limit / to
            adj = cur + trades * scale
            constrained = True

    if long_only:
        adj = np.maximum(adj, 0.0)
    adj = _as_weights(adj)

    trades = []
    for i in range(n):
        delta = float(adj[i] - cur[i])
        if abs(delta) > 1e-9:
            trades.append({
                "index": i,
                "current": float(cur[i]),
                "target": float(tgt[i]),
                "adjusted": float(adj[i]),
                "delta": delta,
            })

    return {
        "current_weights": cur.tolist(),
        "target_weights": tgt.tolist(),
        "adjusted_weights": adj.tolist(),
        "trades": trades,
        "turnover": float(np.abs(adj - cur).sum()),
        "constrained": constrained,
        "n_trades": len(trades),
    }


# ----------------------------- V76 多账户聚合 -----------------------------

def aggregate_accounts(
    accounts: List[Dict],
    cash_label: str = "现金",
) -> Dict:
    """多账户聚合：合并若干子账户持仓为统一组合。

    每个账户：{ "name": str, "positions": { 资产: 市值 } 或 [ {asset,value} ],
                "cash": float（可选） }。

    返回
    ----
    { "accounts", "total_value", "asset_weights", "asset_values",
      "account_values", "account_weights", "top_positions", "concentration_hhi",
      "n_assets", "n_accounts" }
    """
    if not accounts:
        raise ValueError("accounts 不能为空")

    asset_total: Dict[str, float] = {}
    account_values: Dict[str, float] = {}
    for acc in accounts:
        name = acc.get("name") or "账户"
        positions = acc.get("positions") or {}
        total = 0.0
        if isinstance(positions, dict):
            for asset, val in positions.items():
                v = float(val)
                asset_total[asset] = asset_total.get(asset, 0.0) + v
                total += v
        else:
            for p in positions:
                asset = p.get("asset")
                v = float(p.get("value", 0.0))
                if asset is None:
                    continue
                asset_total[asset] = asset_total.get(asset, 0.0) + v
                total += v
        cash = float(acc.get("cash", 0.0) or 0.0)
        if cash > 0:
            asset_total[cash_label] = asset_total.get(cash_label, 0.0) + cash
            total += cash
        account_values[name] = total

    grand = sum(asset_total.values())
    if grand <= 0:
        raise ValueError("所有账户市值之和为 0，无法聚合")

    asset_weights = {a: v / grand for a, v in asset_total.items()}
    account_weights = {a: v / grand for a, v in account_values.items()}

    top = sorted(asset_total.items(), key=lambda kv: kv[1], reverse=True)[:10]
    top_positions = [{"asset": a, "value": v, "weight": v / grand} for a, v in top]

    hhi = sum((w * w) for w in asset_weights.values())

    return {
        "accounts": list(account_values.keys()),
        "total_value": grand,
        "asset_weights": asset_weights,
        "asset_values": asset_total,
        "account_values": account_values,
        "account_weights": account_weights,
        "top_positions": top_positions,
        "concentration_hhi": hhi,
        "n_assets": len(asset_total),
        "n_accounts": len(accounts),
    }
