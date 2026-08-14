"""因子研究分析（V2.9）。

在 V2.5 因子库基础上，提供两类横截面研究：

1. **因子相关性矩阵**：把所有因子在「标的 × 时间」面板上的取值合并，
   计算因子两两之间的 Pearson 相关系数，用于发现冗余因子。
2. **因子 IC / IR 分析**：对每个因子，逐期计算其横截面取值与
   「下期收益」的秩相关系数（Information Coefficient），
   再汇总为 均值 IC / 标准差 IC / IR（信息比率）/ IC>0 占比。

全部基于合成行情（4 个 TEST 标的、日期对齐），离线即可运行；
接入真实数据源后无需改动本模块（只换 ``market_service.bars`` 来源）。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..market.models import Bar
from ..market.service import market_service
from .registry import list_factors, compute_factor

# 默认研究标的池（合成行情，日期彼此对齐）
DEFAULT_UNIVERSE = ["TEST.STOCK", "TEST.BANK", "TEST.FUND", "TEST.FUTURE"]


# --------------------------------------------------------------------------- #
# 统计工具
# --------------------------------------------------------------------------- #
def _pearson(x: List[float], y: List[float]) -> Optional[float]:
    """成对剔除 None 后的 Pearson 相关系数。"""
    pairs = [(a, b) for a, b in zip(x, y) if a is not None and b is not None]
    n = len(pairs)
    if n < 3:
        return None
    mx = sum(a for a, _ in pairs) / n
    my = sum(b for _, b in pairs) / n
    cov = sum((a - mx) * (b - my) for a, b in pairs)
    vx = sum((a - mx) ** 2 for a, _ in pairs)
    vy = sum((b - my) ** 2 for _, b in pairs)
    if vx == 0 or vy == 0:
        return None
    return cov / math.sqrt(vx * vy)


def _rank(values: List[Optional[float]]) -> List[Optional[float]]:
    """对含 None 的序列做平均秩（tie 取平均秩），None 位置返回 None。"""
    idx_vals = [(i, v) for i, v in enumerate(values) if v is not None]
    if not idx_vals:
        return [None] * len(values)
    ordered = sorted(idx_vals, key=lambda t: t[1])
    ranks = [None] * len(values)
    i = 0
    while i < len(ordered):
        j = i
        while j + 1 < len(ordered) and ordered[j + 1][1] == ordered[i][1]:
            j += 1
        avg = (i + j) / 2.0 + 1.0  # 1-based 平均秩
        for k in range(i, j + 1):
            ranks[ordered[k][0]] = avg
        i = j + 1
    return ranks


def _spearman(x: List[Optional[float]], y: List[Optional[float]]) -> Optional[float]:
    rx = [_r for _r in _rank(x) if _r is not None]
    ry = [_r for _r in _rank(y) if _r is not None]
    # 对齐有效位置
    px, py = [], []
    for a, b in zip(_rank(x), _rank(y)):
        if a is not None and b is not None:
            px.append(a)
            py.append(b)
    if len(px) < 3:
        return None
    return _pearson(px, py)


# --------------------------------------------------------------------------- #
# 面板构建
# --------------------------------------------------------------------------- #
def _build_panel(
    symbols: List[str], start: str, end: str, window: int
) -> Dict[str, object]:
    """构建 标的 × 时间 因子面板。

    返回：
        dates:    对齐后的交易日期列表
        symbols:  标的顺序
        factors:  因子名列表
        values:   {factor: [[value_per_symbol] per_date]}
    """
    data: Dict[str, List[Bar]] = {}
    for s in symbols:
        try:
            bars = market_service.bars(s, start, end)
        except Exception:
            bars = []
        data[s] = bars

    date_sets = [set(b.date for b in bars) for bars in data.values()]
    common = sorted(set.intersection(*date_sets)) if date_sets else []
    if not common:
        return {"dates": [], "symbols": symbols, "factors": [], "values": {}}

    ordered = {s: sorted(data[s], key=lambda b: b.date) for s in symbols}
    date_idx = {s: {b.date: i for i, b in enumerate(ordered[s])} for s in symbols}

    factors = [f["name"] for f in list_factors()]
    values: Dict[str, List[List[Optional[float]]]] = {f: [] for f in factors}

    for d in common:
        row: Dict[str, List[Optional[float]]] = {f: [] for f in factors}
        for s in symbols:
            i = date_idx[s].get(d)
            if i is None:
                for f in factors:
                    row[f].append(None)
                continue
            hist = ordered[s][: i + 1]  # 含当期的历史
            for f in factors:
                if len(hist) > window:
                    row[f].append(compute_factor(f, hist, window))
                else:
                    row[f].append(None)
        for f in factors:
            values[f].append(row[f])

    return {
        "dates": common,
        "symbols": symbols,
        "factors": factors,
        "values": values,
    }


# --------------------------------------------------------------------------- #
# 对外分析函数
# --------------------------------------------------------------------------- #
def correlation_matrix(
    symbols: Optional[List[str]] = None,
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
) -> Dict[str, object]:
    """因子相关性矩阵（pooled 跨期 × 跨标的 Pearson）。"""
    symbols = symbols or DEFAULT_UNIVERSE
    panel = _build_panel(symbols, start, end, window)
    factors = panel["factors"]
    values = panel["values"]

    matrix = []
    for fi in factors:
        col = []
        fcol = [v for row in values[fi] for v in row]  # 摊平 (date, symbol)
        for fj in factors:
            frow = [v for row in values[fj] for v in row]
            if fi == fj:
                col.append(1.0)
            else:
                col.append(_pearson(fcol, frow))
        matrix.append(col)

    return {
        "factors": factors,
        "matrix": matrix,
        "symbols": panel["symbols"],
        "dates_count": len(panel["dates"]),
    }


def ic_analysis(
    symbols: Optional[List[str]] = None,
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
    forward: int = 1,
) -> Dict[str, object]:
    """逐因子 IC / IR 分析。

    对每个因子：
        - ic_series：每期横截面 Spearman(因子值, 下期收益)
        - mean_ic / std_ic / ir / ic_positive_ratio
    """
    symbols = symbols or DEFAULT_UNIVERSE
    panel = _build_panel(symbols, start, end, window)
    factors = panel["factors"]
    values = panel["values"]
    dates = panel["dates"]
    symbols_order = panel["symbols"]

    # 预取每标的收盘价序列（按对齐日期），用于计算下期收益
    closes: Dict[str, Dict[str, float]] = {}
    for s in symbols_order:
        try:
            bars = market_service.bars(s, start, end)
        except Exception:
            bars = []
        closes[s] = {b.date: float(b.close) for b in bars}

    results = {}
    for f in factors:
        ic_series: List[Optional[float]] = []
        for di, d in enumerate(dates):
            if di + forward >= len(dates):
                continue
            d_next = dates[di + forward]
            fvals = values[f][di]
            rvals = []
            ok = True
            for si, s in enumerate(symbols_order):
                c0 = closes[s].get(d)
                c1 = closes[s].get(d_next)
                if c0 is None or c1 is None or fvals[si] is None or c0 <= 0:
                    rvals.append(None)
                else:
                    rvals.append(c1 / c0 - 1.0)
            ic = _spearman(fvals, rvals)
            if ic is not None:
                ic_series.append(ic)
        if ic_series:
            mean_ic = sum(ic_series) / len(ic_series)
            var = sum((x - mean_ic) ** 2 for x in ic_series) / max(1, len(ic_series) - 1)
            std_ic = math.sqrt(var)
            ir = mean_ic / std_ic if std_ic > 0 else 0.0
            pos = sum(1 for x in ic_series if x > 0)
            results[f] = {
                "mean_ic": round(mean_ic, 4),
                "std_ic": round(std_ic, 4),
                "ir": round(ir, 4),
                "ic_positive_ratio": round(pos / len(ic_series), 4),
                "observations": len(ic_series),
                "ic_series": [round(x, 4) for x in ic_series],
            }
        else:
            results[f] = {
                "mean_ic": None,
                "std_ic": None,
                "ir": None,
                "ic_positive_ratio": None,
                "observations": 0,
                "ic_series": [],
            }

    return {
        "factors": factors,
        "results": results,
        "forward_days": forward,
        "symbols": symbols_order,
        "dates_count": len(dates),
    }


# 因子排行榜可排序指标（默认按均值 IC 降序）
RANK_METRICS = ["mean_ic", "ir", "ic_positive_ratio", "std_ic"]


def factor_ranking(
    symbols: Optional[List[str]] = None,
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
    forward: int = 1,
    metric: str = "mean_ic",
    order: str = "desc",
) -> Dict[str, object]:
    """因子排行榜：基于 IC/IR 对所有内置因子排序。

    复用 ``ic_analysis`` 计算逐因子 IC/IR，再按指定指标（默认均值 IC）
    排序，并附带因子的方向（direction）与中文说明，便于按因子质量筛选。

    ``order`` 为 ``desc``（默认，越大越好，适合 mean_ic/ir/ic_positive_ratio）
    或 ``asc``（适合 std_ic，越小越稳定）。缺失 IC 的因子排在末尾。
    """
    if metric not in RANK_METRICS:
        metric = "mean_ic"
    descending = order != "asc"

    ic = ic_analysis(
        symbols=symbols, start=start, end=end, window=window, forward=forward
    )
    meta = {f["name"]: f for f in list_factors()}

    rows = []
    for f in ic["factors"]:
        res = ic["results"].get(f, {})
        rows.append(
            {
                "factor": f,
                "direction": meta.get(f, {}).get("direction", 0),
                "description": meta.get(f, {}).get("description", ""),
                "mean_ic": res.get("mean_ic"),
                "std_ic": res.get("std_ic"),
                "ir": res.get("ir"),
                "ic_positive_ratio": res.get("ic_positive_ratio"),
                "observations": res.get("observations", 0),
                "ic_series": res.get("ic_series", []),
            }
        )

    # 缺失 IC 的因子永远排在末尾（与排序方向无关）
    non_null = [r for r in rows if r.get(metric) is not None]
    null_rows = [r for r in rows if r.get(metric) is None]
    non_null.sort(key=lambda r: r.get(metric), reverse=descending)
    ranked_rows = non_null + null_rows

    return {
        "metric": metric,
        "order": order,
        "ranked": ranked_rows,
        "forward_days": forward,
        "symbols": ic["symbols"],
        "dates_count": ic["dates_count"],
    }
