"""因子预处理与合成：winsorize / zscore / neutralize（中性化）/ composite（合成）。

V1.1 N3 计算层。横向标准化默认使用全局 ddof=0，与既有 factor.composite 节点口径一致。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd


def winsorize(series: pd.Series, pct: float = 0.01) -> pd.Series:
    """缩尾：将两端 pct 分位以外的极值截断到分位点。"""
    s = series.astype(float)
    if len(s) == 0:
        return s
    lo, hi = s.quantile(pct), s.quantile(1 - pct)
    return s.clip(lo, hi)


def zscore(series: pd.Series) -> pd.Series:
    """标准化：(x - mean) / std（ddof=0），std≈0 时退化为 0。"""
    s = series.astype(float)
    mean = s.mean()
    std = s.std(ddof=0)
    if std is None or std == 0 or math.isnan(std):
        std = 1e-12
    return (s - mean) / std


def neutralize(factor: pd.Series, exposures: pd.DataFrame) -> pd.Series:
    """因子中性化：对风格/行业暴露做 OLS 回归取残差，剔除暴露带来的共性。

    exposures 的列即为需剔除的暴露（如市值、行业 one-hot）；
    内部先做标准化再带截距回归，结果与量纲无关。
    """
    y = factor.astype(float).values
    if exposures is None or exposures.shape[1] == 0 or len(exposures) != len(y):
        return factor.astype(float)
    x = exposures.astype(float).copy()
    x = (x - x.mean()) / x.std(ddof=0).replace(0, 1e-12)
    X = np.column_stack([np.ones(len(y)), x.values])
    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    resid = y - X @ beta
    return pd.Series(resid, index=factor.index)


def composite_factors(
    df: pd.DataFrame,
    cols: Sequence[str],
    weights: Optional[Sequence[float]] = None,
    winsorize_pct: Optional[float] = None,
) -> pd.Series:
    """多因子合成：逐列（可选 winsorize）+ 全局 zscore 后加权求和。

    权重为空则等权；传入权重会自动归一化（与 factor.composite 节点一致）。
    winsorize_pct 为 None 时不缩尾（保持与历史节点完全一致的口径）。
    """
    if not cols:
        raise ValueError("至少需要一个因子列")
    if weights:
        if len(weights) != len(cols):
            raise ValueError("权重数量需与因子列一致")
        w = [float(x) for x in weights]
        total = sum(w) or 1.0
        w = [x / total for x in w]
    else:
        w = [1.0 / len(cols)] * len(cols)
    out: Optional[pd.Series] = None
    for col, weight in zip(cols, w):
        series = df[col].astype(float)
        if winsorize_pct is not None:
            series = winsorize(series, winsorize_pct)
        norm = zscore(series) * weight
        out = norm if out is None else out + norm
    return out


def expression_factor(
    df: pd.DataFrame, expression: str, output: str = "factor"
) -> pd.DataFrame:
    """表达式因子：基于列名的 pandas 表达式计算新因子列（factor.expression 节点底层）。"""
    expr = str(expression).strip()
    output = str(output or "factor").strip() or "factor"
    if not expr:
        raise ValueError("表达式为空")
    result = df.copy()
    try:
        result[output] = result.eval(expr)
    except Exception as exc:
        raise ValueError(f"表达式求值失败（{expr}）: {exc}") from exc
    return result
