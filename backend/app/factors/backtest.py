"""因子回测：多空组合收益（V30 因子库扩展）。

把单一因子在时间维度上滚动计算，逐期做横截面分组，构建
**多空组合**（做多因子值最高分组、做空最低分组），得到可交易的因子收益序列，
用于回答「这个因子历史上能不能稳定赚钱、方向对不对」。

与 :mod:`app.factors.analyzer`（给定因子列+下期收益的 IC/分层分析）的区别：
本模块**自驱数据**——给定因子名/表达式与股票池，自行拉取（或合成）行情、
自行计算因子时间序列、自行构造多空组合收益与累计曲线，开箱即用、离线可跑。

中性化：``neutralized=True`` 时，逐期对因子值做横截面缩尾 + z-score，
剔除截面水平差异后再分组，避免被市值/行业等共性漂移主导排序。

因子输入支持两类：
- 内置因子名（``registry`` 里的 momentum/volatility/rsi 等函数型因子）→ 滚动求值；
- 表达式（库因子的 ``close.pct_change(20)`` 等，或自定义）→ ``df.eval`` 求值。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np
import pandas as pd

from ..market import synthetic
from ..market.models import Bar
from . import transform
from .registry import FactorNotFoundError, compute_factor, list_factors


def factor_catalog() -> List[Dict]:
    """返回可用于回测的因子清单（内置函数型 + 库表达式型）。"""
    out: List[Dict] = []
    for f in list_factors():
        out.append({
            "name": f["name"],
            "kind": "builtin",
            "window": f.get("window"),
            "direction": f.get("direction"),
            "description": f.get("description", ""),
        })
    try:
        from .library import list_factors as lib_list
        for f in lib_list():
            out.append({
                "name": f["name"],
                "kind": "expression",
                "expression": f.get("expression", ""),
                "category": f.get("category", ""),
                "description": f.get("description", ""),
            })
    except Exception:
        pass
    return out


def _bars_to_df(bars: Sequence[Bar]) -> pd.DataFrame:
    rows = []
    for b in bars:
        if isinstance(b, dict):
            rows.append(b)
        else:
            rows.append({
                "date": getattr(b, "date", None) or getattr(b, "timestamp", None),
                "open": float(getattr(b, "open", 0.0) or 0.0),
                "high": float(getattr(b, "high", 0.0) or 0.0),
                "low": float(getattr(b, "low", 0.0) or 0.0),
                "close": float(getattr(b, "close", 0.0) or 0.0),
                "volume": float(getattr(b, "volume", 0.0) or 0.0),
            })
    df = pd.DataFrame(rows)
    if "date" in df.columns:
        df = df.sort_values("date").reset_index(drop=True)
    return df


def _factor_series(symbol_bars: Sequence[Bar], factor: str) -> List[Optional[float]]:
    """计算某标的的因子时间序列（与 bars 等长，不足数据为 None）。"""
    builtins = {f["name"] for f in list_factors()}
    if factor in builtins:
        out = []
        bars = list(symbol_bars)
        for t in range(len(bars)):
            try:
                v = compute_factor(factor, bars[: t + 1])
            except Exception:
                v = None
            out.append(v if v is not None else None)
        return out
    # 表达式：对整段行情 df.eval，返回 Series（自动处理 pct_change/rolling 等）
    df = _bars_to_df(symbol_bars)
    try:
        s = df.eval(factor)
    except Exception as exc:
        raise ValueError(f"因子表达式求值失败（{factor}）：{exc}") from exc
    return [None if (v is None or (isinstance(v, float) and math.isnan(v))) else float(v) for v in s.tolist()]


def _load_universe(universe: List[str], start: str, end: str, source: str, seed: Optional[int]):
    if source == "synthetic":
        return synthetic.generate_universe(universe, start, end, seed=seed)
    # live：从行情服务取
    from ..market.service import market_service
    out: Dict[str, List[Bar]] = {}
    for sym in universe:
        bars = market_service.bars(sym, start=start, end=end, interval="daily")
        if not bars:
            raise ValueError(f"标的 {sym} 无行情数据（live 模式需先入库；或用 source=synthetic）")
        out[sym] = bars
    return out


def factor_long_short(
    factor: str,
    universe: List[str],
    start: str,
    end: str,
    quantiles: int = 5,
    neutralized: bool = False,
    source: str = "synthetic",
    seed: Optional[int] = None,
) -> Dict:
    """对单因子做多空组合回测。

    返回累计收益曲线、多空日收益、IC 时间序列与绩效指标。
    """
    if quantiles < 2:
        raise ValueError("quantiles 至少为 2")
    if not universe:
        raise ValueError("universe 不能为空")
    try:
        data = _load_universe(universe, start, end, source, seed)
    except ValueError as exc:
        raise ValueError(str(exc)) from exc

    # 对齐公共交易日
    date_sets = [set(str(b["date"] if isinstance(b, dict) else getattr(b, "date")) for b in bars) for bars in data.values()]
    common = sorted(set.intersection(*date_sets)) if date_sets else []
    if len(common) < quantiles + 2:
        raise ValueError("公共交易日不足，无法分组回测（请扩大区间或股票池）")

    # 每个标的：close 序列 + 因子时间序列（对齐到 common）
    closes: Dict[str, List[float]] = {}
    factors_t: Dict[str, List[Optional[float]]] = {}
    for sym, bars in data.items():
        df = _bars_to_df(bars).set_index("date")
        df = df.reindex(common)
        closes[sym] = df["close"].astype(float).tolist()
        fseries = _factor_series(bars, factor)
        # 因子序列按原始顺序截断/对齐到 common（长度应一致）
        if len(fseries) >= len(common):
            factors_t[sym] = fseries[-len(common):]
        else:
            factors_t[sym] = [None] * (len(common) - len(fseries)) + fseries

    n = len(common)
    ls_returns: List[float] = []
    ic_series: List[Dict] = []
    cum = 1.0
    cum_return: List[float] = [0.0]  # 首个交易日无收益

    for t in range(n - 1):
        # 当期因子值与下期收益
        fvals = []
        rets = []
        for sym in universe:
            fv = factors_t[sym][t]
            c0 = closes[sym][t]
            c1 = closes[sym][t + 1]
            if fv is None or c0 in (None, 0) or c1 is None:
                continue
            r = c1 / c0 - 1.0
            fvals.append(fv)
            rets.append(r)
        if len(fvals) < 2:
            ls_returns.append(0.0)
            cum_return.append(cum - 1.0)
            continue
        farr = np.array(fvals, dtype=float)
        rarr = np.array(rets, dtype=float)
        if neutralized:
            s = pd.Series(farr)
            s = transform.winsorize(s, 0.01)
            s = transform.zscore(s)
            farr = s.values
        order = np.argsort(farr)
        q = max(1, len(order) // quantiles)
        long_idx = order[-q:]
        short_idx = order[:q]
        long_ret = float(np.mean(rarr[long_idx]))
        short_ret = float(np.mean(rarr[short_idx]))
        port = long_ret - short_ret
        ls_returns.append(port)
        cum *= (1.0 + port)
        cum_return.append(cum - 1.0)
        # IC：因子值与下期收益的秩相关
        try:
            ic = float(np.corrcoef(_rank(farr), _rank(rarr))[0, 1])
        except Exception:
            ic = None
        ic_series.append({"date": common[t + 1], "ic": ic})

    ls_arr = np.array(ls_returns, dtype=float)
    ics = [x["ic"] for x in ic_series if x["ic"] is not None]
    ic_mean = float(np.mean(ics)) if ics else 0.0
    ic_std = float(np.std(ics, ddof=0)) if len(ics) > 1 else 0.0
    ir = ic_mean / ic_std if ic_std > 1e-12 else 0.0
    ann = float(np.mean(ls_arr) * 252) if len(ls_arr) else 0.0
    sd = float(np.std(ls_arr, ddof=0)) if len(ls_arr) > 1 else 0.0
    sharpe = ann / sd / math.sqrt(252) if sd > 1e-12 else 0.0
    mdd = _max_drawdown(cum_return)

    return {
        "factor": factor,
        "universe": universe,
        "source": source,
        "quantiles": quantiles,
        "neutralized": neutralized,
        "dates": common[1:],
        "cum_return": [round(x, 6) for x in cum_return[1:]],
        "ls_returns": [round(x, 6) for x in ls_returns],
        "ic_series": ic_series,
        "metrics": {
            "ann_return": round(ann, 6),
            "sharpe": round(sharpe, 4),
            "max_drawdown": round(mdd, 6),
            "ic_mean": round(ic_mean, 4),
            "ic_std": round(ic_std, 4),
            "ir": round(ir, 4),
            "ic_positive_ratio": round(sum(1 for x in ics if x > 0) / len(ics), 4) if ics else 0.0,
            "n": len(ls_returns),
        },
    }


def _rank(arr: np.ndarray) -> np.ndarray:
    order = np.argsort(arr)
    ranks = np.empty(len(arr), dtype=float)
    ranks[order] = np.arange(len(arr), dtype=float)
    return ranks


def _max_drawdown(cum_return: List[float]) -> float:
    peak = -1e9
    mdd = 0.0
    for v in cum_return:
        if v > peak:
            peak = v
        mdd = min(mdd, v - peak)
    return mdd
