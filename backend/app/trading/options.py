"""期权定价与希腊值计算器（V109，Black-Scholes 欧式期权）。

纯数学、零依赖，可作为量化工具集的独立计算器使用，弥补 quantflow 此前
只覆盖股票/期货模拟而缺期权分析能力的不足。

覆盖：
- 欧式看涨/看跌期权理论价（Black-Scholes）；
- 五大希腊值：Delta / Gamma / Vega / Theta / Rho；
- 由市场期权价反解隐含波动率（二分法）。

单位约定（与业界一致）：
- Vega 以「波动率变动 1.00（即 100%）」为基准返回，并额外给出 per_1pct（每 1%）；
- Theta 以「年」为基准返回，并额外给出 per_day（每年 365 天）；
- Rho 以「利率变动 1.00（100%）」为基准。
"""

from __future__ import annotations

import math
from typing import Dict, Optional


def _norm_cdf(x: float) -> float:
    """标准正态分布累积分布函数。"""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """标准正态分布概率密度函数。"""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


class InvalidOptionInput(Exception):
    """期权输入非法。"""


def bs_price(s: float, k: float, t: float, r: float, sigma: float, option_type: str = "call") -> float:
    """Black-Scholes 欧式期权理论价。

    :param s: 标的现价
    :param k: 行权价
    :param t: 到期时间（年，如 0.25=3 个月）
    :param r: 无风险利率（年化连续复利，如 0.03）
    :param sigma: 波动率（年化，如 0.2 表示 20%）
    :param option_type: ``call`` 或 ``put``
    """
    if s <= 0 or k <= 0 or sigma <= 0:
        raise InvalidOptionInput("标的价格、行权价、波动率必须为正数")
    if t < 0:
        raise InvalidOptionInput("到期时间不能为负")
    option_type = (option_type or "call").lower()
    if option_type not in ("call", "put"):
        raise InvalidOptionInput("option_type 必须为 call 或 put")

    if t == 0:
        # 到期：内在价值
        return max(0.0, s - k) if option_type == "call" else max(0.0, k - s)

    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc = math.exp(-r * t)
    if option_type == "call":
        return s * _norm_cdf(d1) - k * disc * _norm_cdf(d2)
    return k * disc * _norm_cdf(-d2) - s * _norm_cdf(-d1)


def bs_greeks(s: float, k: float, t: float, r: float, sigma: float, option_type: str = "call") -> Dict[str, float]:
    """计算期权的五大希腊值（原始单位）。"""
    if s <= 0 or k <= 0 or sigma <= 0:
        raise InvalidOptionInput("标的价格、行权价、波动率必须为正数")
    if t < 0:
        raise InvalidOptionInput("到期时间不能为负")
    option_type = (option_type or "call").lower()
    if option_type not in ("call", "put"):
        raise InvalidOptionInput("option_type 必须为 call 或 put")

    if t == 0:
        # 到期：希腊值退化（Gamma/Vega/Theta 归零，Delta 为阶跃）
        delta = 1.0 if (s > k if option_type == "call" else s < k) else 0.0
        return {
            "delta": delta,
            "gamma": 0.0,
            "vega": 0.0,
            "theta": 0.0,
            "rho": 0.0,
            "theta_per_day": 0.0,
            "vega_per_1pct": 0.0,
        }

    sqrt_t = math.sqrt(t)
    d1 = (math.log(s / k) + (r + 0.5 * sigma * sigma) * t) / (sigma * sqrt_t)
    d2 = d1 - sigma * sqrt_t
    disc = math.exp(-r * t)
    pdf_d1 = _norm_pdf(d1)

    if option_type == "call":
        delta = _norm_cdf(d1)
        rho = k * t * disc * _norm_cdf(d2)
        theta = -(s * pdf_d1 * sigma) / (2.0 * sqrt_t) - r * k * disc * _norm_cdf(d2)
    else:
        delta = _norm_cdf(d1) - 1.0
        rho = -k * t * disc * _norm_cdf(-d2)
        theta = -(s * pdf_d1 * sigma) / (2.0 * sqrt_t) + r * k * disc * _norm_cdf(-d2)

    gamma = pdf_d1 / (s * sigma * sqrt_t)
    vega = s * pdf_d1 * sqrt_t  # 波动率每变动 1.00（100%）

    return {
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "rho": rho,
        "theta_per_day": theta / 365.0,
        "vega_per_1pct": vega / 100.0,
    }


def implied_vol(price: float, s: float, k: float, t: float, r: float,
                option_type: str = "call", lo: float = 1e-6, hi: float = 5.0,
                tol: float = 1e-8, max_iter: int = 200) -> Optional[float]:
    """由市场期权价反解隐含波动率（二分法）。

    若市场价低于内在价值（无套利边界），返回 ``None``。
    """
    if price is None:
        return None
    option_type = (option_type or "call").lower()
    if t <= 0:
        return None
    intrinsic = max(0.0, s - k) if option_type == "call" else max(0.0, k - s)
    if price < intrinsic - 1e-9:
        return None

    def f(sigma: float) -> float:
        return bs_price(s, k, t, r, sigma, option_type) - price

    # 边界检查：确保存在符号变化
    flo, fhi = f(lo), f(hi)
    if flo * fhi > 0:
        # 在高波动端仍低于市价（深度实值等极端情形），放宽上界
        hi2 = hi * 4
        fhi2 = f(hi2)
        if flo * fhi2 > 0:
            return None
        hi = hi2
        fhi = fhi2
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        fm = f(mid)
        if abs(fm) < tol:
            return mid
        if flo * fm < 0:
            hi, fhi = mid, fm
        else:
            lo, flo = mid, fm
    return 0.5 * (lo + hi)


def compute_options(s: float, k: float, t: float, r: float, sigma: float,
                    option_type: str = "call",
                    market_price: Optional[float] = None) -> Dict:
    """一站式计算：理论价 + 希腊值 + （可选）隐含波动率。"""
    s = float(s)
    k = float(k)
    t = float(t)
    r = float(r)
    sigma = float(sigma)
    option_type = (option_type or "call").lower()

    price = bs_price(s, k, t, r, sigma, option_type)
    greeks = bs_greeks(s, k, t, r, sigma, option_type)
    iv = implied_vol(market_price, s, k, t, r, option_type) if market_price is not None else None

    return {
        "option_type": option_type,
        "inputs": {
            "spot": s,
            "strike": k,
            "maturity": t,
            "rate": r,
            "volatility": sigma,
            "market_price": market_price,
        },
        "price": round(price, 6),
        "greeks": {kk: round(vv, 8) for kk, vv in greeks.items()},
        "implied_volatility": round(iv, 6) if iv is not None else None,
    }
