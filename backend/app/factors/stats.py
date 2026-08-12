"""因子统计量：RankIC / IC 序列 / IC 均值·ICIR·t 统计量 / IC 衰减。

V1.1 N3「因子分析模块独立」核心计算层，纯函数、可独立复用（节点与 REST API 共用）。
所有 IC 均使用 **截面 RankIC**（因子与下期收益的秩相关系数 = Spearman），
与 V1.0 既有 factor.ic 节点口径保持一致。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
import pandas as pd


def rank_ic(factor: pd.Series, forward_return: pd.Series) -> Optional[float]:
    """截面 RankIC：因子与下期收益的秩相关系数（Pearson-of-ranks = Spearman）。

    样本不足 3 个返回 None（与既有节点口径一致）。
    """
    pair = pd.concat([factor, forward_return], axis=1).dropna()
    pair = pair.iloc[:, [0, 1]]
    if len(pair) < 3:
        return None
    corr = pair.iloc[:, 0].rank().corr(pair.iloc[:, 1].rank())
    if corr is None or (isinstance(corr, float) and math.isnan(corr)):
        return None
    return float(corr)


def ic_series(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str,
    date_col: Optional[str] = None,
) -> List[Tuple[str, Optional[float]]]:
    """按日期截面计算 RankIC 序列。

    无 date 列时视为单一截面，返回 [("", ic)]。
    返回 [(date, ic), ...]，ic 为 None 表示当日样本不足。
    """
    if date_col and date_col in df.columns:
        out: List[Tuple[str, Optional[float]]] = []
        for date, sub in df.dropna(subset=[factor_col, ret_col]).groupby(date_col):
            ic = rank_ic(sub[factor_col], sub[ret_col])
            out.append((str(date), ic))
        return out
    ic = rank_ic(df[factor_col], df[ret_col])
    return [("", ic)]


def ic_summary(ics: Sequence[Optional[float]]) -> Dict[str, Optional[float]]:
    """由 IC 序列汇总 IC 均值 / 标准差 / ICIR / t 统计量 / 正 IC 占比 / 样本数。"""
    vals = [x for x in ics if x is not None]
    n = len(vals)
    if n == 0:
        return {
            "mean": None,
            "std": None,
            "ir": None,
            "t_stat": None,
            "pct_positive": None,
            "n": 0,
        }
    mean = sum(vals) / n
    if n >= 2:
        var = sum((x - mean) ** 2 for x in vals) / (n - 1)
        std = math.sqrt(var) if var > 0 else 0.0
    else:
        std = 0.0
    ir = mean / std if std > 0 else None
    t_stat = (mean / (std / math.sqrt(n))) if std > 0 else None
    pct_positive = sum(1 for x in vals if x > 0) / n
    return {
        "mean": mean,
        "std": std,
        "ir": ir,
        "t_stat": t_stat,
        "pct_positive": pct_positive,
        "n": n,
    }


def ic_decay(
    df: pd.DataFrame,
    factor_col: str,
    ret_col: str,
    date_col: Optional[str],
    max_lag: int = 5,
) -> List[Dict[str, Optional[float]]]:
    """IC 衰减：因子对滞后 L 期收益的截面 RankIC（pooled 近似）。

    对每一滞后 L，将第 d 日的因子与第 d+L 日的下期收益合并后计算一次 RankIC。
    反映因子预测能力的持续性，L 越大 IC 越低说明衰减越快。
    """
    if max_lag < 1:
        return []
    work = df.dropna(subset=[factor_col, ret_col]).copy()
    if not (date_col and date_col in work.columns):
        # 无时间维度无法计算衰减
        return []
    dates = sorted(work[date_col].astype(str).unique())
    out: List[Dict[str, Optional[float]]] = []
    for lag in range(1, max_lag + 1):
        f_parts: List[float] = []
        r_parts: List[float] = []
        for i in range(len(dates) - lag):
            d0, d1 = dates[i], dates[i + lag]
            f = work.loc[work[date_col].astype(str) == d0, factor_col]
            r = work.loc[work[date_col].astype(str) == d1, ret_col]
            f_parts.extend(f.astype(float).tolist())
            r_parts.extend(r.astype(float).tolist())
        if len(f_parts) >= 3:
            ic = rank_ic(pd.Series(f_parts), pd.Series(r_parts))
        else:
            ic = None
        out.append({"lag": lag, "ic": ic})
    return out
