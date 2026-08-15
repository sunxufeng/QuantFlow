"""策略库扩展（V52–V56）：与 backtest/strategies 单标的策略互补的进阶策略分析工具。

- V52 协整配对交易：Engle-Granger 协整检验 + 价差 z-score 配对回测。
- V53 期权定价与 Greeks：Black-Scholes 价格 / Delta-Gamma-Vega-Theta-Rho / 隐含波动率。
- V54 网格交易回测：等距网格的无限网格模拟（目标持仓随价格自适应）。
- V55 定投(DCA)回测：定期定额 vs 一次性投入的收益/成本对比。
- V56 多资产趋势跟随：跨资产均线信号的多头/空仓组合回测（vs 等权基准）。

纯函数，输入价格/收益序列即可离线运行、可单测。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np
from numpy.linalg import inv


# ----------------------------- V52 协整配对交易 -----------------------------

def _ols(X: np.ndarray, y: np.ndarray):
    xtx_inv = inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    resid = y - X @ beta
    n, k = X.shape
    sigma2 = float(resid @ resid) / max(1, n - k)
    se = np.sqrt(np.diag(sigma2 * xtx_inv))
    return beta, se


def pairs_cointegration(y: Sequence[float], x: Sequence[float]) -> Dict:
    """Engle-Granger 协整检验（含 1 阶滞后 ADF 于残差）。"""
    yy = np.asarray(y, dtype=float)
    xx = np.asarray(x, dtype=float)
    if len(yy) != len(xx) or len(yy) < 30:
        raise ValueError("两价格序列需等长且至少 30 期")
    # 第一步：y 对 x 的 OLS
    X = np.column_stack([xx, np.ones(len(xx))])
    beta, _ = _ols(X, yy)
    hedge_ratio, alpha = float(beta[0]), float(beta[1])
    spread = yy - (alpha + hedge_ratio * xx)
    # 第二步：对 spread 做 ADF（含 1 阶滞后差分 + 常数项）
    e = spread
    de = np.diff(e)
    n = len(de)
    elag = e[:-2]
    delag = de[:-1]
    Xa = np.column_stack([elag, delag, np.ones(len(elag))])
    Ya = de[1:]
    b, se = _ols(Xa, Ya)
    gamma = float(b[0])
    gamma_se = float(se[0])
    adf = gamma / gamma_se if gamma_se > 0 else 0.0
    # MacKinnon 近似临界值（大样本）
    cv = {"p01": -3.43, "p05": -2.86, "p10": -2.57}
    is_coint = adf < cv["p05"]
    p_val = 0.01 if adf < cv["p01"] else (0.05 if adf < cv["p05"] else (0.10 if adf < cv["p10"] else 0.20))
    half_life = (-math.log(2) / gamma) if gamma < 0 else None
    return {
        "hedge_ratio": round(hedge_ratio, 4),
        "alpha": round(alpha, 4),
        "adf_stat": round(adf, 4),
        "adf_critical": cv,
        "p_value": p_val,
        "is_cointegrated": bool(is_coint),
        "half_life": round(half_life, 2) if half_life else None,
    }


def pairs_backtest(y: Sequence[float], x: Sequence[float], entry_z: float = 2.0, exit_z: float = 0.5, window: int = 60) -> Dict:
    """配对交易回测：滚动 z-score 信号（z<-entry 做多价差，z>entry 做空，回中平仓）。"""
    yy = np.asarray(y, dtype=float)
    xx = np.asarray(x, dtype=float)
    if len(yy) != len(xx) or len(yy) < window + 5:
        raise ValueError(f"两序列需等长且至少 {window + 5} 期")
    coint = pairs_cointegration(yy, xx)
    beta = coint["hedge_ratio"]; alpha = coint["alpha"]
    spread = yy - (alpha + beta * xx)
    T = len(spread)
    z = np.full(T, np.nan)
    for t in range(window, T):
        seg = spread[t - window:t]
        m = seg.mean(); s = seg.std(ddof=0)
        z[t] = (spread[t] - m) / s if s > 0 else 0.0
    pos = 0
    pnl = [0.0]
    trades = 0
    for t in range(1, T):
        zt = z[t]
        if not np.isnan(zt):
            if zt < -entry_z:
                target = 1
            elif zt > entry_z:
                target = -1
            elif abs(zt) < exit_z:
                target = 0
            else:
                target = pos
            if target != pos:
                trades += 1
            pos = target
        daily = pos * (spread[t] - spread[t - 1])
        pnl.append(daily)
    pnl_arr = np.array(pnl)
    eq = np.cumsum(pnl_arr)
    std = pnl_arr.std(ddof=0)
    sharpe = float(pnl_arr.mean() / std * math.sqrt(252)) if std > 0 else 0.0
    peak = np.maximum.accumulate(eq)
    dd = np.where(peak > 0, eq / peak - 1.0, 0.0)
    mdd = float(dd.min())
    return {
        "hedge_ratio": round(beta, 4),
        "is_cointegrated": coint["is_cointegrated"],
        "adf_stat": coint["adf_stat"],
        "entry_z": entry_z,
        "exit_z": exit_z,
        "window": window,
        "n_trades": trades,
        "total_pnl": round(float(eq[-1]), 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "equity_curve": [round(float(v), 4) for v in eq],
    }


# ----------------------------- V53 期权定价与 Greeks -----------------------------

def _norm_cdf(x):
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x):
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def bs_price(S: float, K: float, T: float, r: float, sigma: float, option: str = "call") -> float:
    if T <= 0 or sigma <= 0 or S <= 0 or K <= 0:
        return max(0.0, (S - K) if option == "call" else (K - S))
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    if option == "call":
        return S * _norm_cdf(d1) - K * math.exp(-r * T) * _norm_cdf(d2)
    return K * math.exp(-r * T) * _norm_cdf(-d2) - S * _norm_cdf(-d1)


def bs_greeks(S: float, K: float, T: float, r: float, sigma: float, option: str = "call") -> Dict:
    if T <= 0 or sigma <= 0:
        return {"delta": 0.0, "gamma": 0.0, "vega": 0.0, "theta": 0.0, "rho": 0.0}
    d1 = (math.log(S / K) + (r + 0.5 * sigma * sigma) * T) / (sigma * math.sqrt(T))
    d2 = d1 - sigma * math.sqrt(T)
    gamma = _norm_pdf(d1) / (S * sigma * math.sqrt(T))
    vega = S * _norm_pdf(d1) * math.sqrt(T) / 100.0  # 每 1 vol 点
    if option == "call":
        delta = _norm_cdf(d1)
        theta = (-S * _norm_pdf(d1) * sigma / (2 * math.sqrt(T)) - r * K * math.exp(-r * T) * _norm_cdf(d2)) / 365.0
        rho = K * T * math.exp(-r * T) * _norm_cdf(d2) / 100.0
    else:
        delta = _norm_cdf(d1) - 1.0
        theta = (-S * _norm_pdf(d1) * sigma / (2 * math.sqrt(T)) + r * K * math.exp(-r * T) * _norm_cdf(-d2)) / 365.0
        rho = -K * T * math.exp(-r * T) * _norm_cdf(-d2) / 100.0
    return {
        "delta": round(delta, 4), "gamma": round(gamma, 4), "vega": round(vega, 4),
        "theta": round(theta, 4), "rho": round(rho, 4),
    }


def implied_vol(price: float, S: float, K: float, T: float, r: float, option: str = "call", tol: float = 1e-6, max_iter: int = 100) -> float:
    """二分法求解隐含波动率。"""
    if price <= 0:
        return 0.0
    lo, hi = 1e-4, 5.0
    for _ in range(max_iter):
        mid = 0.5 * (lo + hi)
        val = bs_price(S, K, T, r, mid, option)
        if abs(val - price) < tol:
            return round(mid, 4)
        if val > price:
            hi = mid
        else:
            lo = mid
    return round(0.5 * (lo + hi), 4)


# ----------------------------- V54 网格交易回测 -----------------------------

def grid_backtest(prices: Sequence[float], lower: float, upper: float, n_grid: int = 10, lot: float = 1.0, initial_cash: float = 1_000_000.0) -> Dict:
    """等距网格的无限网格模拟：目标持仓 = 价格下方网格线数 × lot，随价格自适应再平衡。"""
    P = np.asarray(prices, dtype=float)
    if len(P) < 2:
        raise ValueError("价格序列需至少 2 期")
    if upper <= lower or n_grid < 2:
        raise ValueError("需 upper>lower 且 n_grid>=2")
    lines = np.linspace(lower, upper, n_grid)
    cash = float(initial_cash)
    pos = 0.0
    equity = [cash]
    n_trades = 0
    for t in range(1, len(P)):
        price = float(P[t])
        target = float(np.sum(lines < price)) * lot
        delta = target - pos
        if delta != 0:
            cash -= delta * price
            n_trades += abs(int(round(delta / lot))) if lot else 0
            pos = target
        equity.append(cash + pos * price)
    eq = np.array(equity)
    ret = float(eq[-1] / eq[0] - 1.0)
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min())
    return {
        "lower": lower, "upper": upper, "n_grid": n_grid, "lot": lot,
        "n_trades": int(n_trades),
        "final_equity": round(float(eq[-1]), 2),
        "total_return": round(ret, 4),
        "max_drawdown": round(mdd, 4),
        "equity_curve": [round(float(v), 2) for v in eq],
    }


# ----------------------------- V55 定投(DCA)回测 -----------------------------

def dca_backtest(prices: Sequence[float], dates: Optional[List[str]] = None, periodic_investment: float = 10_000.0, freq: str = "M", initial_cash: float = 0.0) -> Dict:
    """定期定额(DCA)回测：每期投入固定金额，对比一次性投入(lump-sum)。"""
    P = np.asarray(prices, dtype=float)
    if len(P) < 2:
        raise ValueError("价格序列需至少 2 期")
    if dates is None:
        dates = [f"d{i}" for i in range(len(P))]
    keyfn = _period_key(freq)
    shares = 0.0
    invested = float(initial_cash)
    if invested > 0:
        shares += invested / float(P[0])
    dca_curve = [invested]
    lump_invested = 0.0
    lump_shares = 0.0
    lump_started = False
    n_periods = 0
    prev_key = None
    for t in range(len(P)):
        k = keyfn(dates[t])
        if k != prev_key:
            # 新周期：DCA 投入
            shares += periodic_investment / float(P[t])
            invested += periodic_investment
            n_periods += 1
            # lump-sum：仅在首个周期一次性投入等价总本金
            if not lump_started:
                lump_invested = periodic_investment * _estimate_periods(dates, freq)
                lump_shares = lump_invested / float(P[t])
                lump_started = True
            prev_key = k
        dca_curve.append(shares * float(P[t]))
    final_price = float(P[-1])
    dca_value = shares * final_price
    lump_value = lump_shares * final_price
    avg_cost = (invested / shares) if shares > 0 else 0.0
    return {
        "freq": freq,
        "periodic_investment": periodic_investment,
        "n_periods": n_periods,
        "estimated_periods": _estimate_periods(dates, freq),
        "dca_shares": round(shares, 4),
        "dca_invested": round(invested, 2),
        "dca_value": round(dca_value, 2),
        "dca_avg_cost": round(avg_cost, 2),
        "dca_return": round(float(dca_value / invested - 1.0), 4) if invested > 0 else 0.0,
        "lump_invested": round(lump_invested, 2),
        "lump_value": round(lump_value, 2),
        "lump_return": round(float(lump_value / lump_invested - 1.0), 4) if lump_invested > 0 else 0.0,
        "dca_minus_lump": round(float(dca_value - lump_value), 2),
        "dca_curve": [round(float(v), 2) for v in dca_curve],
    }


def _estimate_periods(dates: List[str], freq: str) -> int:
    keys = {_period_key(freq)(d) for d in dates}
    return max(1, len(keys))


def _period_key(freq: str):
    if freq == "D":
        return lambda d: d
    if freq == "W":
        def kw(d):
            try:
                from datetime import date

                y, m, day = int(d[:4]), int(d[5:7]), int(d[8:10])
                return date(y, m, day).isocalendar()[1]
            except Exception:
                return d[:7]  # 退化：按月份（或原串）分桶
        return kw
    return lambda d: d[:7]  # M 月


# ----------------------------- V56 多资产趋势跟随 -----------------------------

def multi_trend_backtest(returns: Sequence[Sequence[float]], assets: List[str], prices: Optional[Sequence[Sequence[float]]] = None, fast: int = 20, slow: int = 60, rebalance: str = "M", initial_cash: float = 1_000_000.0) -> Dict:
    """多资产趋势跟随：各资产 fast/slow 均线信号（快>慢 看多，否则空仓），再平衡期等权配置看多资产。"""
    R = np.asarray(returns, dtype=float)
    if R.ndim != 2 or R.shape[1] != len(assets):
        raise ValueError("returns 的列数须与 assets 数量一致")
    T, n = R.shape
    if T <= slow:
        raise ValueError(f"收益序列需超过 slow({slow}) 期")
    if prices is None:
        prices = np.cumprod(1.0 + R, axis=0)
    P = np.asarray(prices, dtype=float)
    signals = np.zeros((T, n))  # 1=看多, 0=空仓
    for j in range(n):
        pj = P[:, j]
        for t in range(slow, T):
            fast_ma = pj[t - fast + 1: t + 1].mean()
            slow_ma = pj[t - slow + 1: t + 1].mean()
            signals[t, j] = 1.0 if fast_ma > slow_ma else 0.0
    dates = [str(i) for i in range(T)]
    reb = _rebal_indices_mt(dates, rebalance)
    weights = np.zeros(n)
    equity = [initial_cash]
    port_rets = []
    started = False
    weight_history = []
    for t in range(T):
        if (t in reb) and t >= slow:
            longs = [j for j in range(n) if signals[t, j] > 0]
            if longs:
                w = np.zeros(n)
                w[longs] = 1.0 / len(longs)
                weights = w
                started = True
            else:
                weights = np.zeros(n)
            weight_history.append({"date": dates[t], "longs": [assets[j] for j in longs]})
        pr = float(np.dot(weights, R[t])) if started else 0.0
        port_rets.append(pr)
        equity.append(equity[-1] * (1.0 + pr))
    eq = np.array(equity)
    bench_w = np.ones(n) / n
    bench_eq = [initial_cash]
    for t in range(T):
        bench_eq.append(bench_eq[-1] * (1.0 + float(np.dot(bench_w, R[t]))))
    bench_eq = np.array(bench_eq)
    total = float(eq[-1] / eq[0] - 1.0)
    bench_total = float(bench_eq[-1] / bench_eq[0] - 1.0)
    pr_arr = np.array(port_rets)
    sharpe = float(pr_arr.mean() / (pr_arr.std(ddof=0) + 1e-12) * math.sqrt(252)) if started else 0.0
    peak = np.maximum.accumulate(eq)
    mdd = float((eq / peak - 1.0).min())
    return {
        "fast": fast, "slow": slow, "rebalance": rebalance,
        "total_return": round(total, 4),
        "benchmark_total_return": round(bench_total, 4),
        "excess_return": round(total - bench_total, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "n_rebalances": len(weight_history),
        "equity_curve": [round(float(v), 2) for v in eq],
        "benchmark_curve": [round(float(v), 2) for v in bench_eq],
        "weight_history": weight_history,
    }


def _rebal_indices_mt(dates: List[str], rebalance: str) -> set:
    if rebalance.isdigit():
        return set(range(0, len(dates), int(rebalance)))
    if rebalance == "D":
        return set(range(len(dates)))
    keyfn = _period_key(rebalance)
    prev = None
    out = set()
    for i, d in enumerate(dates):
        k = keyfn(d)
        if k != prev:
            out.add(i); prev = k
    return out
