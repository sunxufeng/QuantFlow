"""报告与运维增强（V67–V71）。

纯函数：综合绩效报告 / 快照对比 / 多策略对比 / 周期报告 / 风险看板。
复用 risk.analytics 的 var_cvar / drawdown_analysis，聚焦「聚合与对比」而非重算风险数学。
"""
from __future__ import annotations

from typing import Dict, Any, List, Optional

import numpy as np

from app.risk.analytics import var_cvar, drawdown_analysis


def _ann_factor(periods_per_year: int) -> int:
    return max(1, int(periods_per_year))


def _perf_block(r: np.ndarray, ppy: int) -> Dict[str, float]:
    r = np.asarray(r, dtype=float)
    n = len(r)
    if n == 0:
        return {}
    mu = float(r.mean())
    sd = float(r.std(ddof=0)) + 1e-12
    ann_ret = float((1 + mu) ** ppy - 1.0) if mu > -1 else -1.0
    ann_vol = float(sd * np.sqrt(ppy))
    sharpe = float(mu / sd * np.sqrt(ppy))
    downside = r[r < 0]
    dd_dev = float(downside.std(ddof=0)) + 1e-12
    sortino = float(mu / dd_dev * np.sqrt(ppy))
    win_rate = float((r > 0).mean())
    from scipy import stats as _stats
    skew = float(_stats.skew(r)) if n >= 3 else 0.0
    kurt = float(_stats.kurtosis(r)) if n >= 4 else 0.0
    return {
        "total_return": round(float(np.prod(1 + r) - 1.0), 4),
        "ann_return": round(ann_ret, 4),
        "ann_vol": round(ann_vol, 4),
        "sharpe": round(sharpe, 4),
        "sortino": round(sortino, 4),
        "win_rate": round(win_rate, 4),
        "skew": round(skew, 4),
        "kurtosis": round(kurt, 4),
    }


def build_performance_report(
    returns: List[float],
    equity: Optional[List[float]] = None,
    benchmark: Optional[List[float]] = None,
    periods_per_year: int = 252,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """综合绩效报告：单调用下聚合收益/风险/回撤/（基准）对比。"""
    r = np.asarray(returns, dtype=float).ravel()
    if len(r) < 2:
        raise ValueError("returns 至少 2 个样本")
    ppy = _ann_factor(periods_per_year)
    perf = _perf_block(r, ppy)
    vc = var_cvar(r.tolist(), confidence=confidence, method="historical")
    dd = drawdown_analysis(r.tolist())
    report = {
        "periods_per_year": ppy,
        "n_observations": int(len(r)),
        "performance": perf,
        "risk": {
            "var": vc["var"],
            "cvar": vc["cvar"],
            "var_pct": vc["var_pct"],
            "cvar_pct": vc["cvar_pct"],
            "max_drawdown": dd["max_drawdown"],
            "max_drawdown_start": dd.get("max_drawdown_start"),
            "max_drawdown_end": dd.get("max_drawdown_end"),
        },
        "calmar": round(perf["ann_return"] / abs(dd["max_drawdown"]), 4) if dd["max_drawdown"] < 0 else 0.0,
    }
    if benchmark is not None:
        b = np.asarray(benchmark, dtype=float).ravel()
        m = min(len(r), len(b))
        if m >= 2:
            rb = b[-m:]
            rr = r[-m:]
            cov = np.cov(rr, rb)[0, 1]
            var_b = float(rb.var(ddof=0)) + 1e-12
            beta = float(cov / var_b)
            corr = float(np.corrcoef(rr, rb)[0, 1])
            alpha = float(perf["ann_return"] - beta * ((1 + rb.mean()) ** ppy - 1.0))
            tracking_err = float((rr - rb).std(ddof=0) * np.sqrt(ppy))
            report["benchmark"] = {
                "beta": round(beta, 4),
                "correlation": round(corr, 4),
                "alpha": round(alpha, 4),
                "tracking_error": round(tracking_err, 4),
                "information_ratio": round(alpha / tracking_err, 4) if tracking_err > 1e-9 else 0.0,
            }
    if equity is not None:
        eq = np.asarray(equity, dtype=float).ravel()
        if len(eq) > 1:
            report["equity_stats"] = {
                "final": round(float(eq[-1]), 4),
                "peak": round(float(eq.max()), 4),
                "min": round(float(eq.min()), 4),
            }
    return report


def compare_reports(
    report_a: Dict[str, Any],
    report_b: Dict[str, Any],
    name_a: str = "A",
    name_b: str = "B",
) -> Dict[str, Any]:
    """快照对比：逐指标比较两份报告（支持嵌套 performance/risk）。"""
    flat_a = _flatten(report_a)
    flat_b = _flatten(report_b)
    keys = sorted(set(flat_a) & set(flat_b))
    diffs = []
    for k in keys:
        va, vb = flat_a[k], flat_b[k]
        if isinstance(va, (int, float)) and isinstance(vb, (int, float)):
            delta = va - vb
            diffs.append({
                "metric": k,
                name_a: round(float(va), 4),
                name_b: round(float(vb), 4),
                "delta": round(float(delta), 4),
                "improved": _is_better(k, delta),
            })
    return {
        "name_a": name_a,
        "name_b": name_b,
        "n_metrics": len(diffs),
        "comparisons": diffs,
        "improved_count": sum(1 for d in diffs if d["improved"]),
    }


def _flatten(d: Dict[str, Any], prefix: str = "") -> Dict[str, float]:
    out: Dict[str, float] = {}
    for k, v in d.items():
        key = f"{prefix}.{k}" if prefix else k
        if isinstance(v, dict):
            out.update(_flatten(v, key))
        elif isinstance(v, (int, float)):
            out[key] = float(v)
    return out


def _is_better(metric: str, delta: float) -> bool:
    # 默认：值增大为优；以下指标数值越大越差（注意 max_drawdown 为负，越接近 0 越好=值更大）。
    worse_if_up = ("var", "cvar", "tracking_error", "vol", "kurtosis")
    if any(w in metric for w in worse_if_up):
        return delta < 0
    return delta > 0


def multi_compare(
    curves: Dict[str, List[float]],
    periods_per_year: int = 252,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """多策略对比看板：对每个序列出报告并排名（按 Sharpe）。"""
    if not curves:
        raise ValueError("curves 不能为空")
    rows = []
    for name, rets in curves.items():
        rep = build_performance_report(rets, periods_per_year=periods_per_year, confidence=confidence)
        rows.append({"name": name, "report": rep})
    rows.sort(key=lambda x: x["report"]["performance"]["sharpe"], reverse=True)
    ranking = [r["name"] for r in rows]
    return {
        "n_strategies": len(rows),
        "ranking_by_sharpe": ranking,
        "rows": rows,
    }


def periodic_report(
    returns: List[float],
    dates: List[str],
    freq: str = "M",
    periods_per_year: int = 252,
) -> Dict[str, Any]:
    """周期报告：按 freq(M 月 / W 周 / Q 季 / Y 年) 分组，输出各期绩效。"""
    r = np.asarray(returns, dtype=float).ravel()
    if len(dates) != len(r):
        raise ValueError("dates 与 returns 长度须一致")
    if len(r) < 2:
        raise ValueError("returns 至少 2 个样本")
    ppy = _ann_factor(periods_per_year)
    groups: Dict[str, List[float]] = {}
    for d, v in zip(dates, r):
        key = _period_key(d, freq)
        groups.setdefault(key, []).append(float(v))
    periods_out = []
    for k in sorted(groups):
        sub = np.array(groups[k])
        blk = _perf_block(sub, ppy)
        periods_out.append({"period": k, "n": int(len(sub)), **blk})
    overall = _perf_block(r, ppy)
    return {
        "freq": freq,
        "n_periods": len(periods_out),
        "periods": periods_out,
        "overall": overall,
    }


def _period_key(d: str, freq: str) -> str:
    d = str(d)
    if freq == "Y":
        return d[:4]
    if freq == "Q":
        import math
        m = int(d[5:7]) if len(d) >= 7 else 1
        return f"{d[:4]}-Q{(m - 1) // 3 + 1}"
    if freq == "W":
        try:
            from datetime import date
            y, m, day = int(d[:4]), int(d[5:7]), int(d[8:10])
            return f"{d[:4]}-W{date(y, m, day).isocalendar()[1]}"
        except Exception:
            return d[:7]
    return d[:7]  # M 月


def risk_dashboard(
    returns: List[float],
    weights: Optional[Dict[str, float]] = None,
    benchmark: Optional[List[float]] = None,
    confidence: float = 0.95,
    periods_per_year: int = 252,
) -> Dict[str, Any]:
    """风险看板：单调用下聚合波动/风险/回撤/（基准 Beta）/（持仓集中度）。"""
    r = np.asarray(returns, dtype=float).ravel()
    if len(r) < 2:
        raise ValueError("returns 至少 2 个样本")
    ppy = _ann_factor(periods_per_year)
    report = build_performance_report(r.tolist(), benchmark=benchmark, periods_per_year=ppy, confidence=confidence)
    dash = {
        "ann_vol": report["performance"]["ann_vol"],
        "sharpe": report["performance"]["sharpe"],
        "max_drawdown": report["risk"]["max_drawdown"],
        "var_pct": report["risk"]["var_pct"],
        "cvar_pct": report["risk"]["cvar_pct"],
        "calmar": report["calmar"],
    }
    if "benchmark" in report:
        dash["beta"] = report["benchmark"]["beta"]
        dash["correlation"] = report["benchmark"]["correlation"]
    if weights:
        from app.risk.analytics import concentration
        dash["concentration"] = concentration(weights)
    return {"periods_per_year": ppy, "dashboard": dash, "full_report": report}


__all__ = [
    "build_performance_report",
    "compare_reports",
    "multi_compare",
    "periodic_report",
    "risk_dashboard",
]
