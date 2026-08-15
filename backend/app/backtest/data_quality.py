"""行情数据质量校验（V27）。

对一段 bar 序列做结构化体检，输出 0~100 的质量分、问题清单（按严重度分级）
与分类汇总。纯标准库实现。

检查项：
- 缺失字段（open/high/low/close/volume 为 None 或 NaN）
- 非正价格（<= 0）
- OHLC 一致性（high < low；close/open 越出 [low, high]）
- 重复时间戳
- 时间戳非单调（乱序）
- 零成交量
- 异常收益（|z| 超过阈值，或单根绝对收益超过 50%）
- 交易日缺口（相邻间隔 > 期望间隔 * 容忍倍数）
- 陈旧性（最近一根比 as_of 早超过容忍窗口）
"""
from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

_HIGH = "high"
_MEDIUM = "medium"
_LOW = "low"

# 各类问题扣分权重（按严重度）
_PENALTY = {_HIGH: 12.0, _MEDIUM: 5.0, _LOW: 2.0}


def _is_missing(v: Any) -> bool:
    if v is None:
        return True
    try:
        return isinstance(v, float) and math.isnan(v)
    except TypeError:
        return False


def _to_float(v: Any) -> Optional[float]:
    if _is_missing(v):
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _parse_ts(ts: str) -> Optional[float]:
    """宽松解析时间戳为 epoch 秒；支持 ISO 与 YYYY-MM-DD。"""
    if _is_missing(ts):
        return None
    s = str(ts).strip().replace("Z", "+00:00")
    # 仅日期
    if len(s) <= 10 and s[4] == "-" and s[7] == "-":
        s = s + "T00:00:00"
    for fmt in ("%Y-%m-%dT%H:%M:%S", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            from datetime import datetime
            return datetime.strptime(s[:19], fmt[:19]).timestamp()
        except ValueError:
            continue
    try:
        from datetime import datetime
        return datetime.fromisoformat(s).timestamp()
    except (ValueError, TypeError):
        return None


def _mean(xs: List[float]) -> float:
    return sum(xs) / len(xs) if xs else 0.0


def _stdev(xs: List[float]) -> float:
    if len(xs) < 2:
        return 0.0
    m = _mean(xs)
    var = sum((x - m) ** 2 for x in xs) / (len(xs) - 1)
    return math.sqrt(var)


def validate_bars(
    bars: List[Dict[str, Any]],
    symbol: Optional[str] = None,
    expected_interval_days: Optional[float] = None,
    as_of: Optional[str] = None,
    outlier_z: float = 5.0,
    gap_tolerance: float = 3.0,
) -> Dict[str, Any]:
    """校验 bar 序列，返回质量报告。"""
    issues: List[Dict[str, Any]] = []
    cats = {
        "missing_fields": 0, "non_positive": 0, "ohlc_error": 0,
        "duplicate_ts": 0, "non_monotonic": 0, "zero_volume": 0,
        "outlier": 0, "gap": 0, "stale": 0,
    }
    by_sev: Dict[str, int] = {_HIGH: 0, _MEDIUM: 0, _LOW: 0}

    n = len(bars)
    if n == 0:
        return {
            "symbol": symbol,
            "score": 0.0,
            "summary": {"total_bars": 0, "date_min": None, "date_max": None,
                        "issues_total": 1, "by_severity": by_sev, **cats},
            "issues": [{"index": -1, "ts": None, "severity": _HIGH,
                        "category": "missing_fields", "message": "数据为空"}],
        }

    # 解析时间戳与价格
    parsed: List[Dict[str, Any]] = []
    for i, b in enumerate(bars):
        ts_raw = b.get("timestamp") or b.get("date") or b.get("time")
        ts = _parse_ts(ts_raw) if ts_raw is not None else None
        o = _to_float(b.get("open"))
        h = _to_float(b.get("high"))
        l = _to_float(b.get("low"))
        c = _to_float(b.get("close"))
        v = _to_float(b.get("volume"))
        parsed.append({"i": i, "ts": ts, "ts_raw": str(ts_raw) if ts_raw is not None else None,
                       "o": o, "h": h, "l": l, "c": c, "v": v})

    # 缺失字段
    for p in parsed:
        miss = [k for k in ("o", "h", "l", "c") if p[k] is None] + (["v"] if p["v"] is None else [])
        if miss:
            cats["missing_fields"] += 1
            sev = _HIGH
            by_sev[sev] += 1
            issues.append({"index": p["i"], "ts": p["ts_raw"], "severity": sev,
                           "category": "missing_fields",
                           "message": f"缺失字段：{', '.join(miss)}"})

    # 非正价格 / OHLC 一致性
    for p in parsed:
        if None not in (p["o"], p["h"], p["l"], p["c"]):
            if min(p["o"], p["h"], p["l"], p["c"]) <= 0:
                cats["non_positive"] += 1
                by_sev[_HIGH] += 1
                issues.append({"index": p["i"], "ts": p["ts_raw"], "severity": _HIGH,
                               "category": "non_positive", "message": "存在非正价格(<=0)"})
                continue
            if p["h"] < p["l"]:
                cats["ohlc_error"] += 1
                by_sev[_HIGH] += 1
                issues.append({"index": p["i"], "ts": p["ts_raw"], "severity": _HIGH,
                               "category": "ohlc_error", "message": f"high({p['h']}) < low({p['l']})"})
            elif not (p["l"] <= p["c"] <= p["h"] and p["l"] <= p["o"] <= p["h"]):
                cats["ohlc_error"] += 1
                by_sev[_MEDIUM] += 1
                issues.append({"index": p["i"], "ts": p["ts_raw"], "severity": _MEDIUM,
                               "category": "ohlc_error",
                               "message": f"open/close 越出 [low,high] 区间"})

    # 零成交量
    for p in parsed:
        if p["v"] is not None and p["v"] <= 0:
            cats["zero_volume"] += 1
            by_sev[_LOW] += 1
            issues.append({"index": p["i"], "ts": p["ts_raw"], "severity": _LOW,
                           "category": "zero_volume", "message": "成交量为 0 或负值"})

    # 重复 / 非单调时间戳
    seen: Dict[float, int] = {}
    last_ts: Optional[float] = None
    monotonic_ok = True
    for p in parsed:
        if p["ts"] is None:
            continue
        if p["ts"] in seen:
            cats["duplicate_ts"] += 1
            by_sev[_HIGH] += 1
            issues.append({"index": p["i"], "ts": p["ts_raw"], "severity": _HIGH,
                           "category": "duplicate_ts", "message": "时间戳与第 "
                           f"{seen[p['ts']]} 根重复"})
        else:
            seen[p["ts"]] = p["i"]
        if last_ts is not None and p["ts"] < last_ts - 1e-9:
            monotonic_ok = False
        if last_ts is None or p["ts"] >= last_ts:
            last_ts = p["ts"]

    if not monotonic_ok:
        cats["non_monotonic"] += 1
        by_sev[_MEDIUM] += 1
        issues.append({"index": -1, "ts": None, "severity": _MEDIUM,
                       "category": "non_monotonic", "message": "时间戳存在乱序"})

    # 异常收益（基于 close）
    closes = [p["c"] for p in parsed if p["c"] is not None]
    if len(closes) >= 3:
        rets = [(closes[i] / closes[i - 1] - 1.0) for i in range(1, len(closes)) if closes[i - 1] != 0]
        if rets:
            m = _mean(rets)
            sd = _stdev(rets)
            for idx, r in enumerate(rets, start=1):
                if abs(r) > 0.5:
                    cats["outlier"] += 1
                    by_sev[_HIGH] += 1
                    issues.append({"index": parsed[idx]["i"], "ts": parsed[idx]["ts_raw"],
                                   "severity": _HIGH, "category": "outlier",
                                   "message": f"单根收益 {r * 100:.1f}% 超过 50%"})
                elif sd > 0 and abs(r - m) > outlier_z * sd:
                    cats["outlier"] += 1
                    by_sev[_MEDIUM] += 1
                    issues.append({"index": parsed[idx]["i"], "ts": parsed[idx]["ts_raw"],
                                   "severity": _MEDIUM, "category": "outlier",
                                   "message": f"收益偏离均值 {abs(r - m) / sd:.1f}σ（阈值 {outlier_z}σ）"})

    # 交易日缺口（需 expected_interval_days）
    if expected_interval_days and len(parsed) >= 2:
        for j in range(1, len(parsed)):
            a, b = parsed[j - 1]["ts"], parsed[j]["ts"]
            if a is None or b is None:
                continue
            gap = (b - a) / 86400.0
            if gap > expected_interval_days * gap_tolerance:
                cats["gap"] += 1
                by_sev[_MEDIUM] += 1
                issues.append({"index": parsed[j]["i"], "ts": parsed[j]["ts_raw"],
                               "severity": _MEDIUM, "category": "gap",
                               "message": f"间隔 {gap:.1f} 天，超过期望 {expected_interval_days} 天*{gap_tolerance}"})

    # 陈旧性
    if as_of:
        as_of_ts = _parse_ts(as_of)
        last_valid = max((p["ts"] for p in parsed if p["ts"] is not None), default=None)
        if as_of_ts is not None and last_valid is not None:
            lag_days = (as_of_ts - last_valid) / 86400.0
            tol = (expected_interval_days or 1.0) * gap_tolerance
            if lag_days > tol:
                cats["stale"] += 1
                by_sev[_MEDIUM] += 1
                issues.append({"index": -1, "ts": parsed[-1]["ts_raw"], "severity": _MEDIUM,
                               "category": "stale",
                               "message": f"最新数据距今 {lag_days:.1f} 天，超过容忍 {tol:.1f} 天"})

    # 评分
    total_penalty = sum(_PENALTY[s] for s in (it["severity"] for it in issues))
    score = max(0.0, min(100.0, 100.0 - total_penalty))
    issues_total = len(issues)

    ts_sorted = sorted(p["ts_raw"] for p in parsed if p["ts_raw"] is not None)
    summary = {
        "total_bars": n,
        "date_min": ts_sorted[0] if ts_sorted else None,
        "date_max": ts_sorted[-1] if ts_sorted else None,
        "issues_total": issues_total,
        "by_severity": by_sev,
        **cats,
    }

    return {
        "symbol": symbol,
        "score": _round(score),
        "grade": _grade(score),
        "summary": summary,
        "issues": issues,
    }


def _round(x: float, n: int = 2) -> float:
    return round(x, n)


def _grade(score: float) -> str:
    if score >= 95:
        return "A"
    if score >= 85:
        return "B"
    if score >= 70:
        return "C"
    if score >= 50:
        return "D"
    return "E"
