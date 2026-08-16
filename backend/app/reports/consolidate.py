"""V97 综合报告聚合器。

复用 ``app.reports.analytics`` 的纯函数（build_performance_report / risk_dashboard），
把绩效 / 风险 / 看板聚合成一份多章节报告，供前端「综合报告」视图渲染与一键导出。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import numpy as np

from app.reports.analytics import build_performance_report, risk_dashboard


def consolidate_report(
    returns: List[float],
    weights: Optional[Dict[str, float]] = None,
    benchmark: Optional[List[float]] = None,
    periods_per_year: int = 252,
    confidence: float = 0.95,
) -> Dict[str, Any]:
    """综合报告：把绩效 / 风险 / 看板聚合成一份结构化报告。

    返回 summary（头条指标）、performance、risk、dashboard、benchmark（可选），
    以及 export_sections（供前端导出工具直接消费）。
    """
    r = np.asarray(returns, dtype=float).ravel()
    if len(r) < 2:
        raise ValueError("returns 至少 2 个样本")
    perf = build_performance_report(
        r.tolist(), benchmark=benchmark, periods_per_year=periods_per_year, confidence=confidence
    )
    dash = risk_dashboard(
        r.tolist(), weights=weights, benchmark=benchmark,
        periods_per_year=periods_per_year, confidence=confidence,
    )
    d = dash["dashboard"]
    perf_p = perf["performance"]
    summary: Dict[str, Any] = {
        "年化收益": perf_p["ann_return"],
        "年化波动": perf_p["ann_vol"],
        "夏普": perf_p["sharpe"],
        "最大回撤": perf["risk"]["max_drawdown"],
        "Calmar": perf["calmar"],
        "索提诺": perf_p["sortino"],
        "VaR95": perf["risk"]["var_pct"],
        "CVaR95": perf["risk"]["cvar_pct"],
        "胜率": perf_p["win_rate"],
    }
    if "beta" in d:
        summary["Beta"] = d["beta"]
        summary["相关性"] = d["correlation"]
    if "concentration" in d:
        summary["集中度(HHI)"] = d["concentration"]

    export_sections = [
        {"title": "绩效摘要", "kv": summary},
        {"title": "绩效明细", "kv": perf_p},
        {"title": "风险明细", "kv": perf["risk"]},
        {"title": "风险看板", "kv": d},
    ]
    if "benchmark" in perf and perf["benchmark"]:
        export_sections.append({"title": "基准对比", "kv": perf["benchmark"]})

    return {
        "params": {
            "periods_per_year": periods_per_year,
            "confidence": confidence,
            "n_observations": int(len(r)),
            "has_benchmark": benchmark is not None,
            "n_assets": len(weights) if weights else 0,
        },
        "summary": summary,
        "performance": perf_p,
        "risk": perf["risk"],
        "dashboard": d,
        "benchmark": perf.get("benchmark"),
        "export_sections": export_sections,
    }


__all__ = ["consolidate_report"]
