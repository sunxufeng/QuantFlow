"""因子评分与排序服务（V2.5）。

流程：
1. 对每个标的，用 ``market_service`` 拉取日线，计算各因子原始值；
2. 按因子列做横截面标准化（rank 百分位 或 zscore）；
3. 应用方向（direction）与权重（weight）合成综合分；
4. 返回按综合分降序排列的评分明细。

缺失值（数据不足导致因子为 None）用该列中位数填补，确保排序稳健。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from ..market.service import market_service
from .registry import FactorNotFoundError, compute_factor, get_factor


class FactorScoreConfigError(Exception):
    def __init__(self, message: str) -> None:
        super().__init__(message)
        self.message = message


def _median(values: List[float]) -> float:
    if not values:
        return 0.0
    s = sorted(values)
    n = len(s)
    mid = n // 2
    return s[mid] if n % 2 else (s[mid - 1] + s[mid]) / 2.0


def _rank_normalize(column: List[Optional[float]]) -> List[float]:
    """返回每个位置在横截面中的百分位（0~1），None 用列中位数填补。"""
    filled = [v if v is not None else _median([x for x in column if x is not None]) for v in column]
    order = sorted(range(len(filled)), key=lambda i: filled[i])
    ranks = [0.0] * len(filled)
    n = len(filled)
    # 处理并列：相同值取平均排名
    i = 0
    while i < n:
        j = i
        while j + 1 < n and filled[order[j + 1]] == filled[order[i]]:
            j += 1
        avg_rank = (i + j) / 2.0
        for k in range(i, j + 1):
            ranks[order[k]] = (avg_rank + 1.0) / n
        i = j + 1
    return ranks


def _zscore_normalize(column: List[Optional[float]]) -> List[float]:
    filled = [v if v is not None else _median([x for x in column if x is not None]) for v in column]
    n = len(filled)
    if n < 2:
        return [0.5] * n
    mean = sum(filled) / n
    var = sum((x - mean) ** 2 for x in filled) / (n - 1)
    if var == 0:
        return [0.5] * n
    import math

    return [(x - mean) / math.sqrt(var) for x in filled]


def score(
    *,
    symbols: List[str],
    factors: Optional[List[dict]] = None,
    start: Optional[str] = None,
    end: Optional[str] = None,
    method: str = "rank",
) -> dict:
    if not symbols:
        raise FactorScoreConfigError("symbols 不能为空")
    if method not in ("rank", "zscore"):
        raise FactorScoreConfigError("method 仅支持 rank / zscore")

    # 解析因子规格：默认使用全部因子目录及其默认方向/窗口
    if not factors:
        factors = [
            {
                "name": meta["name"],
                "window": meta["window"],
                "direction": meta["direction"],
                "weight": 1.0,
            }
            for meta in _default_factor_specs()
        ]
    else:
        for f in factors:
            if "name" not in f:
                raise FactorScoreConfigError("每个 factor 必须包含 name")
            try:
                meta = get_factor(f["name"])
            except FactorNotFoundError as exc:
                raise FactorScoreConfigError(str(exc)) from None
            f.setdefault("window", meta["window"])
            f.setdefault("direction", meta["direction"])
            f.setdefault("weight", 1.0)
            if f["direction"] not in (1, -1):
                raise FactorScoreConfigError("direction 必须为 1 或 -1")

    # 计算每个标的的因子原始值
    raw_matrix: Dict[str, Dict[str, Optional[float]]] = {}
    as_of_dates: Dict[str, Optional[str]] = {}
    for sym in symbols:
        bars = market_service.bars(sym, start=start, end=end)
        as_of_dates[sym] = bars[-1].date if bars else None
        row: Dict[str, Optional[float]] = {}
        for f in factors:
            try:
                row[f["name"]] = compute_factor(f["name"], bars, f["window"])
            except Exception:
                row[f["name"]] = None
        raw_matrix[sym] = row

    # 逐因子横截面标准化
    normalized: Dict[str, List[float]] = {f["name"]: [] for f in factors}
    for f in factors:
        col = [raw_matrix[sym][f["name"]] for sym in symbols]
        if method == "rank":
            norm = _rank_normalize(col)
        else:
            norm = _zscore_normalize(col)
        # 应用方向：低配因子取反向（rank 下 1 - pct；zscore 下取负）
        if f["direction"] == -1:
            norm = [1.0 - v if method == "rank" else -v for v in norm]
        normalized[f["name"]] = norm

    # 加权合成综合分
    total_weight = sum(f["weight"] for f in factors) or 1.0
    scores = []
    for idx, sym in enumerate(symbols):
        comp = 0.0
        breakdown = {}
        norm_breakdown = {}
        for f in factors:
            v = normalized[f["name"]][idx]
            raw = raw_matrix[sym][f["name"]]
            breakdown[f["name"]] = raw
            norm_breakdown[f["name"]] = round(v, 6)
            comp += v * f["weight"]
        comp = comp / total_weight
        scores.append(
            {
                "symbol": sym,
                "composite": round(comp, 6),
                "as_of_date": as_of_dates[sym],
                "factors": {k: (round(v, 6) if isinstance(v, float) else v) for k, v in breakdown.items()},
                "normalized": norm_breakdown,
            }
        )

    scores.sort(key=lambda x: x["composite"], reverse=True)
    for rank, s in enumerate(scores, 1):
        s["rank"] = rank

    return {
        "method": method,
        "as_of_dates": as_of_dates,
        "factors": [
            {"name": f["name"], "window": f["window"], "direction": f["direction"], "weight": f["weight"]}
            for f in factors
        ],
        "scores": scores,
    }


def _default_factor_specs() -> List[dict]:
    from .registry import list_factors

    return list_factors()
