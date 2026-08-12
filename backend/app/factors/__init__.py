"""QuantFlow 独立因子分析模块（V1.1 N3）。

把因子计算从节点内部抽离为可独立复用的库：节点与 REST API 共用同一套口径。
"""

from __future__ import annotations

from .analyzer import FactorAnalyzer, quick_factor_report
from .stats import ic_decay, ic_series, ic_summary, rank_ic
from .transform import composite_factors, expression_factor, neutralize, winsorize, zscore

__all__ = [
    "FactorAnalyzer",
    "quick_factor_report",
    "rank_ic",
    "ic_series",
    "ic_summary",
    "ic_decay",
    "winsorize",
    "zscore",
    "neutralize",
    "composite_factors",
    "expression_factor",
]
