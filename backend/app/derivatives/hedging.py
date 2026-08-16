"""衍生品策略与对冲（V82–V86）：在 E（期权定价/Greeks）之上补充策略层面的
盈亏、对冲、保险与风险聚合能力。

五个纯函数（输入标量/向量即可离线运行、可单测）：
- V82 期权盈亏图：多腿期权组合在到期日的损益曲线 + 盈亏平衡 + 最大盈亏。
- V83 Delta 对冲模拟：对空头期权做动态 Delta 对冲，输出对冲损益与对冲误差。
- V84 组合保险：保护看跌（protective put）/ 领口（collar）/ CPPI 三种保险路径。
- V85 组合 Greeks：把一本期权持仓的希腊字母按 Black-Scholes 聚合为净 Greek。
- V86 隐含波动率曲面：把 (行权价 × 期限) 的 IV 报价组织成曲面并抽取 ATM/偏度。

所有函数均为纯函数，不依赖数据库或网络；数值上保证 t>0、σ>0、无 NaN。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np


# ----------------------------- Black-Scholes 基础 -----------------------------

def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def _bs_d1(s: float, k: float, t: float, r: float, sigma: float) -> float:
    return (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * math.sqrt(t))


def bs_price(opt_type: str, s: float, k: float, t: float, r: float, sigma: float) -> float:
    if t <= 0 or sigma <= 0 or s <= 0 or k <= 0:
        # 退化：按内在价值
        if opt_type == "call":
            return max(s - k, 0.0)
        return max(k - s, 0.0)
    d1 = _bs_d1(s, k, t, r, sigma)
    d2 = d1 - sigma * math.sqrt(t)
    if opt_type == "call":
        return s * _norm_cdf(d1) - k * math.exp(-r * t) * _norm_cdf(d2)
    return k * math.exp(-r * t) * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def bs_delta(opt_type: str, s: float, k: float, t: float, r: float, sigma: float) -> float:
    if t <= 0 or sigma <= 0:
        if opt_type == "call":
            return 1.0 if s > k else 0.0
        return -1.0 if s < k else 0.0
    d1 = _bs_d1(s, k, t, r, sigma)
    if opt_type == "call":
        return _norm_cdf(d1)
    return _norm_cdf(d1) - 1.0


def bs_greeks(opt_type: str, s: float, k: float, t: float, r: float, sigma: float) -> Dict[str, float]:
    """返回 call/put 的 delta/gamma/vega/theta/rho。vega/theta 以「每 1.0 单位」计。"""
    if t <= 0 or sigma <= 0:
        d = bs_delta(opt_type, s, k, t, r, sigma)
        return {"delta": d, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1 = _bs_d1(s, k, t, r, sigma)
    d2 = d1 - sigma * math.sqrt(t)
    sqrt_t = math.sqrt(t)
    gamma = _norm_pdf(d1) / (s * sigma * sqrt_t)
    vega = s * _norm_pdf(d1) * sqrt_t
    if opt_type == "call":
        theta = -(s * _norm_pdf(d1) * sigma) / (2 * sqrt_t) - r * k * math.exp(-r * t) * _norm_cdf(d2)
        rho = k * t * math.exp(-r * t) * _norm_cdf(d2)
        delta = _norm_cdf(d1)
    else:
        theta = -(s * _norm_pdf(d1) * sigma) / (2 * sqrt_t) + r * k * math.exp(-r * t) * _norm_cdf(-d2)
        rho = -k * t * math.exp(-r * t) * _norm_cdf(-d2)
        delta = _norm_cdf(d1) - 1.0
    return {"delta": delta, "gamma": gamma, "vega": vega, "theta": theta, "rho": rho}


# ----------------------------- V82 期权盈亏图 -----------------------------

def option_payoff(
    legs: Sequence[Dict],
    spot_min: Optional[float] = None,
    spot_max: Optional[float] = None,
    n_points: int = 101,
) -> Dict:
    """多腿期权组合到期损益曲线。

    legs: 每条 { "type": "call"|"put", "side": "long"|"short",
            "strike": float, "premium": float, "qty": int }。

    返回 { "spots", "pnl", "breakeven", "max_profit", "max_loss" }。
    """
    if not legs:
        raise ValueError("legs 不能为空")
    strikes = [float(l["strike"]) for l in legs]
    if spot_max is None:
        spot_max = max(strikes) * 1.5 + 1.0
    if spot_min is None:
        spot_min = max(min(strikes) * 0.5 - 1.0, 0.01)
    if spot_min >= spot_max:
        raise ValueError("spot_min 必须小于 spot_max")
    spots = np.linspace(spot_min, spot_max, n_points)

    def leg_pnl(s: float, leg: Dict) -> float:
        typ = leg["type"]
        side = 1.0 if leg.get("side", "long") == "long" else -1.0
        k = float(leg["strike"])
        prem = float(leg.get("premium", 0.0))
        qty = float(leg.get("qty", 1))
        if typ == "call":
            intrinsic = max(s - k, 0.0)
        else:
            intrinsic = max(k - s, 0.0)
        return side * qty * (intrinsic - prem)

    pnl = [sum(leg_pnl(s, l) for l in legs) for s in spots]

    # 盈亏平衡：pnl 符号变化处（线性插值）
    breakeven = []
    arr = np.array(pnl)
    for i in range(len(arr) - 1):
        if arr[i] == 0:
            breakeven.append(float(spots[i]))
        elif arr[i] * arr[i + 1] < 0:
            s0, s1 = spots[i], spots[i + 1]
            p0, p1 = arr[i], arr[i + 1]
            be = s0 - p0 * (s1 - s0) / (p1 - p0)
            breakeven.append(float(be))
    breakeven = sorted(set(round(b, 6) for b in breakeven))

    fp = float(np.max(arr))
    fl = float(np.min(arr))
    max_profit = fp
    max_loss = fl
    return {
        "spots": spots.tolist(),
        "pnl": arr.tolist(),
        "breakeven": breakeven,
        "max_profit": max_profit,
        "max_loss": max_loss,
    }


# ----------------------------- V83 Delta 对冲模拟 -----------------------------

def delta_hedge(
    path: Sequence[float],
    strike: float,
    r: float = 0.0,
    sigma: float = 0.2,
    rebalance_every: int = 1,
    option_type: str = "call",
    premium: Optional[float] = None,
    T: float = 1.0,
) -> Dict:
    """对「空头期权」做动态 Delta 对冲，输出对冲损益与误差。

    path: 标的现货路径（长度 T_steps+1），首点为 S0。
    采用 Black-Scholes delta，在每 rebalance_every 步调整持仓，现金按无风险利率增值。
    最终对冲损益 = 期末现金 - 期权到期内在价值（空头需赔付）。

    返回 { "times", "spot_path", "delta_path", "cash_path", "hedge_pnl",
           "option_payoff", "hedge_error", "n_rebalances" }。
    """
    S = np.asarray(path, dtype=float)
    if S.ndim != 1 or S.shape[0] < 2:
        raise ValueError("path 长度至少为 2")
    if strike <= 0 or sigma <= 0:
        raise ValueError("strike / sigma 必须为正数")
    steps = S.shape[0] - 1
    dt = T / steps

    if premium is None:
        premium = bs_price(option_type, float(S[0]), strike, T, r, sigma)
    # 初始：卖出 1 张期权收到 premium；按初始 delta 买入股票
    cash = premium
    delta = bs_delta(option_type, float(S[0]), strike, T, r, sigma)
    shares = delta
    cash -= delta * float(S[0])
    n_reb = 0
    times = [0.0]
    spot_path = [float(S[0])]
    delta_path = [float(delta)]
    cash_path = [float(cash)]
    t_elapsed = 0.0
    for i in range(1, S.shape[0]):
        t_elapsed += dt
        # 现金增值
        cash = cash * math.exp(r * dt)
        if (i % rebalance_every) == 0:
            t_rem = max(T - t_elapsed, 1e-9)
            new_delta = bs_delta(option_type, float(S[i]), strike, t_rem, r, sigma)
            trade = new_delta - shares
            cash -= trade * float(S[i])
            shares = new_delta
            n_reb += 1
        spot_path.append(float(S[i]))
        delta_path.append(float(shares))
        cash_path.append(float(cash))
        times.append(float(t_elapsed))

    # 期末：按市价平仓股票，支付期权内在价值
    final_spot = float(S[-1])
    if option_type == "call":
        payoff = max(final_spot - strike, 0.0)
    else:
        payoff = max(strike - final_spot, 0.0)
    cash += shares * final_spot
    hedge_pnl = cash - payoff  # 空头对冲者：期初收 premium，期末现金覆盖赔付后剩余
    return {
        "times": times,
        "spot_path": spot_path,
        "delta_path": delta_path,
        "cash_path": cash_path,
        "hedge_pnl": float(hedge_pnl),
        "option_payoff": float(payoff),
        "hedge_error": float(abs(hedge_pnl)),
        "n_rebalances": n_reb,
    }


# ----------------------------- V84 组合保险 -----------------------------

def portfolio_insurance(
    risky_path: Sequence[float],
    method: str = "put",
    floor: float = 0.8,
    put_strike: Optional[float] = None,
    put_premium: Optional[float] = None,
    collar_cap: Optional[float] = None,
    cppi_multiplier: float = 3.0,
    r: float = 0.0,
) -> Dict:
    """组合保险：把风险资产路径「保底」。

    method:
    - "put"：保护看跌，保险价值 = max(风险路径, floor*V0)；成本 = put_premium。
    - "collar"：领口，上限封顶（collar_cap*V0），保险价值被上限限制。
    - "cppi"：固定比例组合保险，敞口 = m*(V - floor*V0)，动态再平衡。

    risky_path: 全仓风险资产时的组合价值路径（首点 V0）。
    返回 { "method", "insured_value", "floor_value", "cost", "min_value",
           "n_breaches" }。
    """
    V = np.asarray(risky_path, dtype=float)
    if V.ndim != 1 or V.shape[0] < 2:
        raise ValueError("risky_path 长度至少为 2")
    if floor <= 0 or floor >= 1.0:
        raise ValueError("floor 应落在 (0,1)")
    V0 = float(V[0])
    floor_value = floor * V0

    if method == "put":
        insured = np.maximum(V, floor_value)
        cost = float(put_premium) if put_premium is not None else 0.0
    elif method == "collar":
        cap = (collar_cap if collar_cap is not None else 1.2) * V0
        insured = np.minimum(np.maximum(V, floor_value), cap)
        cost = float(put_premium) if put_premium is not None else 0.0
    elif method == "cppi":
        # 风险敞口 = m*(V - floor)，剩余买无风险
        insured = [V0]
        cur = V0
        for i in range(1, V.shape[0]):
            ret = V[i] / V[i - 1] - 1.0
            exposure = cppi_multiplier * (cur - floor_value)
            exposure = max(exposure, 0.0)
            cur = cur + exposure * ret + (cur - exposure) * (math.exp(r * (1.0 / (V.shape[0] - 1))) - 1.0)
            cur = max(cur, floor_value)
            insured.append(cur)
        insured = np.array(insured)
        cost = 0.0
    else:
        raise ValueError("method 须为 put / collar / cppi")

    min_value = float(np.min(insured))
    n_breaches = int(np.sum(V < floor_value))
    return {
        "method": method,
        "insured_value": insured.tolist(),
        "floor_value": float(floor_value),
        "cost": cost,
        "min_value": min_value,
        "n_breaches": n_breaches,
    }


# ----------------------------- V85 组合 Greeks -----------------------------

def portfolio_greeks(
    positions: Sequence[Dict],
    spot: float,
    r: float = 0.0,
) -> Dict:
    """聚合一本期权持仓的希腊字母。

    positions: 每条 { "type", "strike", "t", "sigma", "qty", "side"("long"/"short") }。
    返回净 { "delta","gamma","vega","theta","rho" }。
    """
    if not positions:
        raise ValueError("positions 不能为空")
    if spot <= 0:
        raise ValueError("spot 必须为正数")
    net = {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    per_position = []
    for p in positions:
        typ = p["type"]
        k = float(p["strike"])
        t = float(p["t"])
        sigma = float(p["sigma"])
        qty = float(p.get("qty", 1))
        side = 1.0 if p.get("side", "long") == "long" else -1.0
        g = bs_greeks(typ, spot, k, t, r, sigma)
        for key in net:
            net[key] += side * qty * g[key]
        per_position.append({"type": typ, "strike": k, "t": t, "greeks": g})
    return {k: float(v) for k, v in net.items()}


# ----------------------------- V86 隐含波动率曲面 -----------------------------

def implied_vol_surface(
    strikes: Sequence[float],
    maturities: Sequence[float],
    iv: Sequence[Sequence[float]],
    spot: Optional[float] = None,
) -> Dict:
    """组织隐含波动率曲面，抽取 ATM 期限结构与偏度。

    iv: (n_strikes × n_maturities) 矩阵，行对应 strikes、列对应 maturities。
    返回 { "strikes", "maturities", "surface", "atm_term_structure",
           "skew_by_maturity", "spot" }。
    """
    K = np.asarray(strikes, dtype=float)
    M = np.asarray(maturities, dtype=float)
    IV = np.asarray(iv, dtype=float)
    if IV.ndim != 2 or IV.shape[0] != len(K) or IV.shape[1] != len(M):
        raise ValueError("iv 必须为 len(strikes) × len(maturities) 矩阵")
    if spot is None:
        spot = float(np.median(K))

    # ATM：每个期限下，取行权价最接近 spot 的 IV
    atm = []
    skew = []
    for j, _ in enumerate(M):
        col = IV[:, j]
        idx = int(np.argmin(np.abs(K - spot)))
        atm.append(float(col[idx]))
        # 偏度：虚值看跌(低行权价) - 虚值看涨(高行权价)
        skew.append(float(col[0] - col[-1]))

    return {
        "strikes": K.tolist(),
        "maturities": M.tolist(),
        "surface": IV.tolist(),
        "atm_term_structure": atm,
        "skew_by_maturity": skew,
        "spot": float(spot),
    }
