"""市场状态与择时（V47–V51）：与 backtest/metrics、risk/analytics 互补的市场态识别工具。

- V47 市场状态检测：基于趋势(MA 多空) + 波动率状态的区制判别（牛市/熊市/震荡/高波动），含逐期滚动序列。
- V48 波动率预测：EWMA(RiskMetrics) 与 GARCH(1,1) 多步向前方差预测 + 长期方差。
- V49 板块轮动信号：相对强度/动量口径的板块排序与超配/低配信号。
- V50 相关性聚类网络：相关性→距离→层次聚类，输出聚类与板块内外相关。
- V51 ETF 动量轮动回测：Top-N 动量轮动策略的净值与基准对比及每期持仓。

纯函数，输入收益序列 / 收益矩阵即可离线运行、可单测；可选合成行情回退。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np

from ..market import synthetic


# ----------------------------- 输入解析工具 -----------------------------

def resolve_returns(
    assets: Optional[List[str]] = None,
    returns: Optional[Sequence[Sequence[float]]] = None,
    universe: Optional[List[str]] = None,
    start: str = "2023-01-01",
    end: str = "2023-12-31",
    source: str = "synthetic",
    seed: int = 12345,
) -> Tuple[List[str], np.ndarray]:
    """统一解析资产收益矩阵（行为时间、列为资产）。

    优先使用显式 ``returns``；否则用合成 GBM 生成。返回 (assets, R)（T×n）。
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
    date_sets = [set(str(b["date"] if isinstance(b, dict) else getattr(b, "date")) for b in bars) for bars in data.values()]
    common = sorted(set.intersection(*date_sets)) if date_sets else []
    if len(common) < 3:
        raise ValueError("公共交易日不足，无法估计协方差")
    cols = []
    for sym in syms:
        bars = data[sym]
        df = sorted(
            (
                {"date": (b["date"] if isinstance(b, dict) else getattr(b, "date")),
                 "close": float(b["close"] if isinstance(b, dict) else getattr(b, "close"))}
                for b in bars
            ),
            key=lambda x: x["date"],
        )
        closes = [x["close"] for x in df if x["date"] in common]
        rets = [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]
        cols.append(rets)
    R = np.array(cols, dtype=float).T  # (T, n)
    return list(syms), R


# ----------------------------- V47 市场状态检测 -----------------------------

REGIME_LABELS = {
    "bull": "牛市",
    "volatile_up": "高波动上行",
    "sideways": "震荡",
    "volatile_down": "高波动下行",
    "bear": "熊市",
}
_REGIME_SCORE = {"bull": 1.0, "volatile_up": 0.5, "sideways": 0.0, "volatile_down": -0.5, "bear": -1.0}


def detect_regime(
    returns: Sequence[float],
    dates: Optional[List[str]] = None,
    short_ma: int = 20,
    long_ma: int = 60,
    vol_window: int = 20,
    sideways_band: float = 0.02,
    vol_mult: float = 1.2,
    annualize: int = 252,
) -> Dict:
    """市场状态检测：趋势(短/长均线的多空) + 波动率状态，逐期滚动判别。

    返回最新状态、关键指标、以及逐期滚动序列（用于可视化状态切换）。
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < long_ma + 1:
        raise ValueError(f"收益序列需至少 {long_ma + 1} 期")
    prices = np.cumprod(1.0 + r)
    T = len(r)
    short_ma_s = np.concatenate([[np.nan] * (short_ma - 1), _rolling_mean(prices, short_ma)])
    long_ma_s = np.concatenate([[np.nan] * (long_ma - 1), _rolling_mean(prices, long_ma)])
    vol_s = np.concatenate([[np.nan] * (vol_window - 1), _rolling_std(r, vol_window)]) * math.sqrt(annualize)
    med_vol = float(np.nanmedian(vol_s))
    series = []
    cur_label = "sideways"
    cur_score = 0.0
    for t in range(T):
        if np.isnan(short_ma_s[t]) or np.isnan(long_ma_s[t]) or np.isnan(vol_s[t]):
            label = "sideways"
            score = 0.0
        else:
            spread = short_ma_s[t] / long_ma_s[t] - 1.0
            high_vol = vol_s[t] > med_vol * vol_mult
            if abs(spread) < sideways_band:
                label = "sideways"
            elif spread > 0:
                label = "volatile_up" if high_vol else "bull"
            else:
                label = "volatile_down" if high_vol else "bear"
            score = float(np.clip(spread / (sideways_band * 2.5), -1.0, 1.0))
        cur_label, cur_score = label, score
        series.append({
            "index": t,
            "date": dates[t] if dates and t < len(dates) else str(t),
            "regime": label,
            "regime_cn": REGIME_LABELS[label],
            "score": round(score, 4),
            "trend_spread": round(float(short_ma_s[t] / long_ma_s[t] - 1.0) if (not np.isnan(short_ma_s[t]) and not np.isnan(long_ma_s[t])) else 0.0, 4),
            "ann_vol": round(float(vol_s[t]) if not np.isnan(vol_s[t]) else 0.0, 4),
        })
    # 计数各状态占比
    counts: Dict[str, int] = {}
    for s in series:
        counts[s["regime"]] = counts.get(s["regime"], 0) + 1
    latest = series[-1]
    return {
        "regime": cur_label,
        "regime_cn": REGIME_LABELS[cur_label],
        "score": round(cur_score, 4),
        "trend_spread": latest["trend_spread"],
        "ann_vol": latest["ann_vol"],
        "median_ann_vol": round(med_vol, 4),
        "params": {"short_ma": short_ma, "long_ma": long_ma, "vol_window": vol_window, "sideways_band": sideways_band},
        "regime_counts": {REGIME_LABELS[k]: v for k, v in counts.items()},
        "series": series,
    }


# ----------------------------- V48 波动率预测 -----------------------------

def forecast_volatility(
    returns: Sequence[float],
    method: str = "ewma",
    lam: float = 0.94,
    horizon: int = 21,
    garch_omega: float = 1e-5,
    garch_alpha: float = 0.08,
    garch_beta: float = 0.90,
    annualize: int = 252,
) -> Dict:
    """波动率预测：EWMA(RiskMetrics) 或 GARCH(1,1) 的多步向前方差。

    EWMA 预测为常数（最新方差）；GARCH 多步期望方差按 (α+β)^h 衰减到长期方差。
    """
    r = np.asarray(returns, dtype=float)
    if len(r) < 30:
        raise ValueError("波动率预测需至少 30 期收益")
    if horizon < 1:
        raise ValueError("horizon 须 ≥ 1")
    var0 = float(np.var(r, ddof=0))
    if method == "ewma":
        sig2 = var0
        series_s = [sig2]
        for x in r:
            sig2 = lam * sig2 + (1.0 - lam) * (x ** 2)
            series_s.append(sig2)
        last_var = float(series_s[-1])
        forecasts = [{"horizon": h, "variance": round(last_var, 8), "annualized_vol": round(math.sqrt(last_var) * math.sqrt(annualize), 4)} for h in range(1, horizon + 1)]
        long_run = math.sqrt(last_var) * math.sqrt(annualize)
    elif method == "garch":
        ab = garch_alpha + garch_beta
        sig2 = var0
        series_s = [sig2]
        for x in r:
            sig2 = garch_omega + garch_alpha * (x ** 2) + garch_beta * series_s[-1]
            series_s.append(sig2)
        last_var = float(series_s[-1])
        if ab < 1.0:
            long_var = garch_omega / (1.0 - ab)
            forecasts = []
            for h in range(1, horizon + 1):
                ev = long_var * (1.0 - ab ** h) / (1.0 - ab) + (ab ** h) * last_var
                forecasts.append({"horizon": h, "variance": round(ev, 8), "annualized_vol": round(math.sqrt(ev) * math.sqrt(annualize), 4)})
            long_run = math.sqrt(long_var) * math.sqrt(annualize)
        else:
            # 非平稳：退化为最新方差常数预测
            forecasts = [{"horizon": h, "variance": round(last_var, 8), "annualized_vol": round(math.sqrt(last_var) * math.sqrt(annualize), 4)} for h in range(1, horizon + 1)]
            long_run = math.sqrt(last_var) * math.sqrt(annualize)
    else:
        raise ValueError("method 须为 ewma 或 garch")
    return {
        "method": method,
        "latest_annualized_vol": round(math.sqrt(last_var) * math.sqrt(annualize), 4),
        "long_run_annualized_vol": round(long_run, 4),
        "horizon": horizon,
        "params": {"lambda": lam, "omega": garch_omega, "alpha": garch_alpha, "beta": garch_beta} if method == "garch" else {"lambda": lam},
        "forecasts": forecasts,
    }


# ----------------------------- V49 板块轮动信号 -----------------------------

def sector_rotation(
    sector_returns: Dict[str, Sequence[float]],
    window: int = 60,
    method: str = "relative_strength",
) -> Dict:
    """板块轮动信号：对各板块计算动量( trailing return)，排序给出超配/低配信号。

    method: relative_strength（相对强度=区间累计收益）/ momentum_z（截面 z 分位动量）。
    """
    if not sector_returns:
        raise ValueError("sector_returns 不能为空")
    rows = []
    for name, rets in sector_returns.items():
        rr = np.asarray(rets, dtype=float)
        if len(rr) == 0:
            continue
        w = min(window, len(rr))
        mom = float(np.prod(1.0 + rr[-w:]) - 1.0)
        rows.append({"sector": name, "momentum": round(mom, 6), "n": len(rr)})
    if not rows:
        raise ValueError("无有效板块收益序列")
    moms = np.array([x["momentum"] for x in rows])
    order = np.argsort(moms)[::-1]
    n = len(rows)
    thirds = max(1, n // 3)
    signals = {}
    for rank, idx in enumerate(order):
        if rank < thirds:
            sig = "overweight"
        elif rank >= n - thirds:
            sig = "underweight"
        else:
            sig = "hold"
        signals[rows[idx]["sector"]] = sig
    # 截面 z 分位（method == momentum_z 时更看重相对排位）
    if method == "momentum_z" and n > 1:
        z = (moms - moms.mean()) / (moms.std(ddof=0) + 1e-12)
        for i, x in enumerate(rows):
            x["zscore"] = round(float(z[i]), 4)
    ranked = [dict(r, rank=i + 1, signal=signals[r["sector"]]) for i, r in enumerate(sorted(rows, key=lambda x: -x["momentum"]))]
    # 合成轮动组合权重：超配 +1、低配 -1、持有 0，再归一（仅正权部分等权）
    tilt = np.array([1.0 if signals[x["sector"]] == "overweight" else (-1.0 if signals[x["sector"]] == "underweight" else 0.0) for x in ranked])
    pos = tilt[tilt > 0]
    if pos.sum() > 0:
        weights = {x["sector"]: (1.0 if signals[x["sector"]] == "overweight" else 0.0) for x in ranked}
        tot = sum(weights.values())
        weights = {k: v / tot for k, v in weights.items()} if tot > 0 else weights
    else:
        weights = {x["sector"]: round(1.0 / n, 4) for x in ranked}
    return {
        "method": method,
        "window": window,
        "ranked": ranked,
        "signals": signals,
        "tilt_weights": {k: round(v, 4) for k, v in weights.items()},
        "n_sectors": n,
    }


# ----------------------------- V50 相关性聚类网络 -----------------------------

def correlation_network(
    returns: Sequence[Sequence[float]],
    assets: List[str],
    method: str = "average",
    n_clusters: Optional[int] = None,
) -> Dict:
    """相关性聚类网络：相关性→距离→层次聚类，输出聚类与板块内外相关系数。

    距离 d = sqrt(0.5*(1-corr))（相关性 1→距离 0）。无 scipy 时退化为阈值分块仍可用，
    但默认用 scipy.cluster.hierarchy 做层次聚类。
    """
    R = np.asarray(returns, dtype=float)
    if R.ndim != 2 or R.shape[1] != len(assets):
        raise ValueError("returns 的列数须与 assets 数量一致")
    n = len(assets)
    if n < 2:
        raise ValueError("至少 2 个资产")
    corr = np.corrcoef(R, rowvar=False)
    corr = np.nan_to_num(corr, nan=0.0)
    corr = np.clip(corr, -1.0, 1.0)
    dist = np.sqrt(np.clip(0.5 * (1.0 - corr), 0.0, 1.0))
    if n_clusters is None:
        n_clusters = max(2, round(math.sqrt(n)))
    n_clusters = min(n_clusters, n)
    try:
        from scipy.cluster.hierarchy import linkage, fcluster
        from scipy.spatial.distance import squareform

        condensed = squareform(dist, checks=False)
        Z = linkage(condensed, method=method)
        labels = fcluster(Z, t=n_clusters, criterion="maxclust")
    except Exception:
        # 退化为相关阈值分块：按相关>0.5 贪心合并
        labels = _greedy_clusters(corr, threshold=0.5)
    clusters: Dict[int, List[str]] = {}
    asset_cluster = {}
    for a, lab in zip(assets, labels):
        asset_cluster[a] = int(lab)
        clusters.setdefault(int(lab), []).append(a)
    # 板块内外相关
    intra = []
    inter = []
    for i in range(n):
        for j in range(i + 1, n):
            c = float(corr[i, j])
            if labels[i] == labels[j]:
                intra.append(c)
            else:
                inter.append(c)
    avg_intra = float(np.mean(intra)) if intra else 0.0
    avg_inter = float(np.mean(inter)) if inter else 0.0
    return {
        "method": method,
        "n_clusters": len(clusters),
        "assets": assets,
        "correlation": [[round(float(corr[i, j]), 4) for j in range(n)] for i in range(n)],
        "asset_cluster": asset_cluster,
        "clusters": {str(k): v for k, v in sorted(clusters.items())},
        "avg_intra_cluster_corr": round(avg_intra, 4),
        "avg_inter_cluster_corr": round(avg_inter, 4),
    }


def _greedy_clusters(corr: np.ndarray, threshold: float = 0.5) -> List[int]:
    n = corr.shape[0]
    labels = [-1] * n
    nxt = 0
    for i in range(n):
        if labels[i] != -1:
            continue
        labels[i] = nxt
        for j in range(i + 1, n):
            if labels[j] == -1 and corr[i, j] > threshold:
                labels[j] = nxt
        nxt += 1
    return labels


# ----------------------------- V51 ETF 动量轮动回测 -----------------------------

def etf_momentum_rotation(
    returns: Sequence[Sequence[float]],
    assets: List[str],
    dates: Optional[List[str]] = None,
    lookback: int = 20,
    hold_top: int = 1,
    rebalance: str = "M",
    initial_cash: float = 1_000_000.0,
    annualize: int = 252,
) -> Dict:
    """ETF 动量轮动回测：每期按过去 lookback 收益排序，持有 Top-N，等权。

    rebalance: M(月)/W(周)/D(日)/或整数(每 k 个交易日)。
    返回组合净值曲线、等权基准、绩效指标与每期持仓。
    """
    R = np.asarray(returns, dtype=float)
    if R.ndim != 2 or R.shape[1] != len(assets):
        raise ValueError("returns 的列数须与 assets 数量一致")
    T, n = R.shape
    if T <= lookback:
        raise ValueError(f"收益序列需超过 lookback({lookback}) 期")
    hold_top = max(1, min(hold_top, n))
    if dates is None:
        dates = [str(i) for i in range(T)]
    rb = list(rebalance)
    # 复权：build equity
    weights = np.zeros(n)
    equity = [initial_cash]
    port_rets = []
    holdings = []
    reb_indices = _rebalance_indices(dates, rebalance)
    # 先在首个 >= lookback 的 rebalance 点建仓
    started = False
    for t in range(T):
        if (t in reb_indices) and t >= lookback:
            # 计算各资产 trailing return
            trail = np.prod(1.0 + R[t - lookback: t], axis=0) - 1.0
            order = np.argsort(trail)[::-1]
            pick = order[:hold_top]
            w = np.zeros(n)
            w[pick] = 1.0 / hold_top
            weights = w
            started = True
            holdings.append({
                "date": dates[t],
                "assets": [assets[i] for i in pick],
                "weights": {assets[i]: round(1.0 / hold_top, 4) for i in pick},
                "trailing_return": {assets[i]: round(float(trail[i]), 4) for i in pick},
            })
        if started:
            pr = float(np.dot(weights, R[t]))
        else:
            pr = 0.0
        port_rets.append(pr)
        equity.append(equity[-1] * (1.0 + pr))
    eq = np.array(equity)
    # 基准：买入持有等权
    bench_w = np.ones(n) / n
    bench_eq = [initial_cash]
    for t in range(T):
        bench_eq.append(bench_eq[-1] * (1.0 + float(np.dot(bench_w, R[t]))))
    bench_eq = np.array(bench_eq)
    pr_arr = np.array(port_rets)
    # 指标
    total_return = float(eq[-1] / eq[0] - 1.0)
    bench_total = float(bench_eq[-1] / bench_eq[0] - 1.0)
    n_years = (T - 1) / annualize
    annual = float((eq[-1] / eq[0]) ** (1.0 / n_years) - 1.0) if n_years > 0 else 0.0
    sharpe = float(pr_arr.mean() / (pr_arr.std(ddof=0) + 1e-12) * math.sqrt(annualize)) if started else 0.0
    mdd = _max_drawdown_from_equity(eq)
    # 持有期胜率：每期相对基准的超额
    excess = eq[1:] / eq[:-1] - bench_eq[1:] / bench_eq[:-1]
    win_rate = float((excess > 0).mean()) if len(excess) else 0.0
    return {
        "lookback": lookback,
        "hold_top": hold_top,
        "rebalance": rebalance,
        "initial_cash": initial_cash,
        "total_return": round(total_return, 4),
        "benchmark_total_return": round(bench_total, 4),
        "excess_return": round(total_return - bench_total, 4),
        "annual_return": round(annual, 4),
        "sharpe": round(sharpe, 4),
        "max_drawdown": round(mdd, 4),
        "win_rate": round(win_rate, 4),
        "n_rebalances": len(holdings),
        "equity_curve": [round(float(x), 2) for x in eq],
        "benchmark_curve": [round(float(x), 2) for x in bench_eq],
        "dates": dates,
        "holdings": holdings,
    }


# ----------------------------- 内部工具 -----------------------------

def _rolling_mean(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) < w:
        return np.array([])
    csum = np.cumsum(x)
    out = np.empty(len(x) - w + 1)
    out[0] = csum[w - 1] / w
    for i in range(1, len(out)):
        out[i] = (csum[i + w - 1] - csum[i - 1]) / w
    return out


def _rolling_std(x: np.ndarray, w: int) -> np.ndarray:
    if len(x) < w:
        return np.array([])
    out = np.empty(len(x) - w + 1)
    for i in range(len(out)):
        out[i] = float(np.std(x[i:i + w], ddof=0))
    return out


def _rebalance_indices(dates: List[str], rebalance: str) -> set:
    idx = set()
    if rebalance.isdigit():
        k = int(rebalance)
        idx = set(range(0, len(dates), k))
        return idx
    if rebalance == "D":
        return set(range(len(dates)))
    keyfn = None
    if rebalance == "M":
        keyfn = lambda d: d[:7]  # YYYY-MM
    elif rebalance == "W":
        keyfn = lambda d: _iso_week(d)
    else:
        keyfn = lambda d: d[:7]
    prev = None
    for i, d in enumerate(dates):
        k = keyfn(d)
        if k != prev:
            idx.add(i)
            prev = k
    return idx


def _iso_week(d: str) -> str:
    try:
        from datetime import date

        y, m, day = int(d[:4]), int(d[5:7]), int(d[8:10])
        return str(date(y, m, day).isocalendar()[1])
    except Exception:
        return d[:7]


def _max_drawdown_from_equity(eq: np.ndarray) -> float:
    peak = np.maximum.accumulate(eq)
    dd = eq / peak - 1.0
    return float(dd.min())
