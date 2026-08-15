"""组合回测（V1.2 → V12 绩效归因）。

将多个「腿」（策略 + 标的 + 权重）各自独立回测后，按权重合并为组合净值曲线，
输出组合净值、各腿配置占比（随时间）、各腿净值曲线与组合绩效归因。

设计要点：
- 每条腿以「分配资金 = 总资金 × 归一化权重」独立运行现有回测引擎，互不影响
- 组合净值 = 各腿市值按日对齐后合并，支持周期性再平衡（none/D/W/M/Q/Y）
- 绩效归因（V12）：以再平衡后的真实权重还原每腿在组合内的市值，逐日盈亏对
  组合总收益的贡献累加，各腿累计贡献之和精确等于组合总收益
- 复用 STRATEGY_REGISTRY / market_service / PerformanceMetrics，零新依赖
"""

from __future__ import annotations

import math
import uuid
from typing import Any, Dict, List

from .engine import BacktestEngine, BacktestError, EquityPoint
from .metrics import PerformanceMetrics
from .strategies import STRATEGY_REGISTRY, default_factors
from ..factors import research as factor_research
from ..market.models import Instrument
from ..market.service import market_service


class PortfolioBacktest:
    """多腿组合回测：独立运行各腿后按权重合并净值。"""

    def __init__(
        self,
        legs: List[Dict[str, Any]],
        initial_cash: float = 1_000_000.0,
        start: str = "",
        end: str = "",
        rebalance: str = "none",
        cost_rates=None,
        benchmark_symbol: Optional[str] = None,
    ) -> None:
        if not legs:
            raise BacktestError("组合回测至少需要一条腿")
        if end < start:
            raise BacktestError("end 不得早于 start")
        self.initial_cash = float(initial_cash)
        self.start = start
        self.end = end
        self.rebalance = rebalance
        self.cost_rates = cost_rates
        self.benchmark_symbol = benchmark_symbol

        # 权重归一化
        raw_weights = [float(l.get("weight", 1.0)) for l in legs]
        total_w = sum(raw_weights)
        if total_w <= 0:
            raise BacktestError("组合权重之和必须大于 0")
        self.legs = []
        for leg, w in zip(legs, raw_weights):
            strategy = leg.get("strategy", "")
            if strategy not in STRATEGY_REGISTRY:
                raise BacktestError(
                    f"未知策略 {strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}"
                )
            symbols = leg.get("symbols") or []
            if not symbols:
                raise BacktestError(f"腿 {strategy} 未指定标的")
            self.legs.append(
                {
                    "strategy": strategy,
                    "params": leg.get("params", {}) or {},
                    "symbols": symbols,
                    "asset_types": leg.get("asset_types", {}) or {},
                    "interval": leg.get("interval", "daily"),
                    "weight": w / total_w,
                }
            )

    # ------------------------------------------------------------------ #
    def run(self) -> Dict[str, Any]:
        leg_results = []
        # 汇总所有腿的标的（去重保序）—— 基准与因子暴露均需用到，提前拉取行情缓存
        all_symbols: List[str] = []
        for leg in self.legs:
            for s in leg["symbols"]:
                if s not in all_symbols:
                    all_symbols.append(s)
        market_cache: Dict[str, Any] = {}
        for sym in all_symbols:
            bars = market_service.bars(
                sym, self.start, self.end, interval=leg.get("interval", "daily")
            )
            if not bars:
                raise BacktestError(
                    f"标的 {sym} 在 {self.start}~{self.end} 无行情数据"
                )
            market_cache[sym] = bars

        for leg in self.legs:
            # 1. 行情（复用全局缓存的子集）
            data: Dict[str, Any] = {sym: market_cache[sym] for sym in leg["symbols"]}
            instruments: Dict[str, Instrument] = {}
            for sym in leg["symbols"]:
                at = leg["asset_types"].get(sym, "stock")
                if at == "fund":
                    exchange = ""
                elif at == "future":
                    exchange = "CFFEX"
                else:
                    exchange = "SH"
                instruments[sym] = Instrument(
                    symbol=sym, name="标的自定义",
                    market=at, exchange=exchange,
                    contract_multiplier=float((leg.get("multipliers") or {}).get(sym, 10.0))
                    if at == "future" else 1.0,
                )
            allocated = self.initial_cash * leg["weight"]
            strategy = STRATEGY_REGISTRY[leg["strategy"]](leg["params"])
            engine = BacktestEngine(
                strategy, data, initial_cash=allocated,
                cost_rates=self.cost_rates, instruments=instruments,
            )
            result = engine.run()
            leg_results.append({"leg": leg, "allocated": allocated, "result": result})

        # 2. 按日对齐合并净值（支持周期性再平衡）
        all_dates: set = set()
        for r in leg_results:
            for p in r["result"].equity_curve:
                all_dates.add(p.date)
        if self.start:
            all_dates.add(self.start)
        if self.end:
            all_dates.add(self.end)
        dates = sorted(all_dates)

        # 每条腿在统一日期序列上的前向填充净值
        leg_value_series = [
            _leg_value_series(r["result"], dates, r["allocated"])
            for r in leg_results
        ]
        weights = [leg["weight"] for leg in self.legs]

        combined_curve, combined_points = _combine_with_rebalance(
            dates, leg_value_series, weights, self.initial_cash, self.rebalance
        )

        # 3. 组合绩效指标
        all_trades = []
        for r in leg_results:
            all_trades.extend(r["result"].trades)
        # 组合基准（equal-weight 买入持有，跨所有标的，与组合净值日期对齐）
        bench_values, bench_curve = _equal_weight_benchmark(
            market_cache, all_symbols, dates, combined_curve, self.initial_cash
        ) if self.benchmark_symbol else (None, None)
        metrics = PerformanceMetrics(
            combined_points, self.initial_cash, all_trades,
            benchmark_values=bench_values,
        )

        # 4. 各腿明细
        leg_summaries = []
        for i, r in enumerate(leg_results):
            curve = r["result"].equity_curve
            leg_metrics = PerformanceMetrics(curve, r["allocated"], r["result"].trades)
            final_value = curve[-1].total_value if curve else r["allocated"]
            leg_summaries.append(
                {
                    "index": i,
                    "strategy": r["leg"]["strategy"],
                    "weight": round(r["leg"]["weight"], 6),
                    "allocated_cash": round(r["allocated"], 2),
                    "final_value": round(final_value, 2),
                    "total_return": round(leg_metrics.total_return, 6),
                    "max_drawdown": round(leg_metrics.max_drawdown, 6),
                    "sharpe": round(leg_metrics.sharpe, 4),
                    "n_trades": len(r["result"].trades),
                }
            )

        start_date = self.start or (combined_curve[0]["date"] if combined_curve else "")
        end_date = self.end or (combined_curve[-1]["date"] if combined_curve else "")
        interval = self.legs[0].get("interval", "daily") if self.legs else "daily"

        # 5. 各腿净值曲线（对齐统一日期序列，便于前端叠加展示）
        leg_curves = [
            {
                "index": k,
                "strategy": leg_results[k]["leg"]["strategy"],
                "weight": round(weights[k], 6),
                "series": [
                    {"date": dates[i], "value": round(leg_value_series[k][i], 4)}
                    for i in range(len(dates))
                ],
            }
            for k in range(len(leg_results))
        ]

        # 6. 绩效归因（V12）：把组合总收益按各腿实际盈亏贡献分解。
        #    用再平衡后的真实权重（combined_curve[i].allocation）还原每腿在组合内的
        #    市值，逐日盈亏对组合总收益的贡献累加，各腿累计贡献之和精确等于总收益。
        n = len(leg_results)
        by_leg_contrib: List[List[float]] = [[] for _ in range(n)]
        cum_contrib = [0.0] * n
        prev_port_leg = [self.initial_cash * weights[k] for k in range(n)]
        for i in range(len(dates)):
            alloc = combined_curve[i]["allocation"] if combined_curve else {
                str(k): weights[k] for k in range(n)
            }
            port_leg = [
                combined_points[i].total_value * alloc.get(str(k), 0.0)
                for k in range(n)
            ]
            if i == 0:
                for k in range(n):
                    by_leg_contrib[k].append(0.0)
            else:
                for k in range(n):
                    pnl = port_leg[k] - prev_port_leg[k]
                    cum_contrib[k] += (pnl / self.initial_cash) if self.initial_cash else 0.0
                    by_leg_contrib[k].append(round(cum_contrib[k], 6))
            prev_port_leg = port_leg
        attribution = {
            "dates": dates,
            "total_return": round(metrics.total_return, 6),
            "by_leg": [
                {
                    "index": k,
                    "strategy": leg_results[k]["leg"]["strategy"],
                    "weight": round(weights[k], 6),
                    "cumulative_return_contrib": by_leg_contrib[k],
                    "final_contrib": round(cum_contrib[k], 6),
                }
                for k in range(n)
            ],
        }

        return {
            "type": "portfolio",
            "run_id": uuid.uuid4().hex[:12],
            "strategy": "组合回测",
            "strategy_name": "portfolio",
            "symbols": all_symbols,
            "interval": interval,
            "start_date": start_date,
            "end_date": end_date,
            "initial_cash": self.initial_cash,
            "rebalance": self.rebalance,
            "legs": leg_summaries,
            "leg_curves": leg_curves,
            "attribution": attribution,
            "metrics": metrics.to_dict(),
            "equity_curve": combined_curve,
            "calendar": dates,
            "risk_decomposition": _risk_decomposition(leg_curves, weights),
            "benchmark_symbol": self.benchmark_symbol,
            "benchmark_curve": bench_curve or [],
            "factor_exposure": _aggregate_factor_exposure(
                self.legs, all_symbols, start_date, end_date
            ),
        }


def _point_at(result, date: str, allocated: float) -> EquityPoint:
    """取某腿在指定日期的净值点；早于其首交易日则返回分配资金占位点。"""
    for p in result.equity_curve:
        if p.date == date:
            return p
    return EquityPoint(
        date=date, cash=allocated, market_value=0.0,
        total_value=allocated, daily_return=0.0,
    )


# 支持的再平衡频率
REBALANCE_FREQS = ("none", "D", "W", "M", "Q", "Y")


def _leg_value_series(result, dates: List[str], allocated: float) -> List[float]:
    """把单腿回测净值前向填充到统一日期序列（停牌/非交易日沿用上一日）。"""
    nav = {p.date: float(p.total_value) for p in result.equity_curve}
    first_date = min(nav) if nav else None
    out: List[float] = []
    last = allocated
    for d in dates:
        if d in nav:
            last = nav[d]
        elif first_date is not None and d < first_date:
            last = allocated
        # d >= first_date 且非该腿交易日：沿用 last（净值不变）
        out.append(last)
    return out


def _is_rebalance_date(date_str: str, prev_str: str, freq: str) -> bool:
    """判断 date_str 是否为再平衡日（freq 见 REBALANCE_FREQS）。"""
    from datetime import date as _date

    if freq == "D":
        return True
    if prev_str is None:
        return True
    cur = _date.fromisoformat(date_str)
    prev = _date.fromisoformat(prev_str)
    if freq == "W":
        return cur.isocalendar()[1] != prev.isocalendar()[1]
    if freq == "M":
        return (cur.year, cur.month) != (prev.year, prev.month)
    if freq == "Q":
        return (cur.year, (cur.month - 1) // 3) != (prev.year, (prev.month - 1) // 3)
    if freq == "Y":
        return cur.year != prev.year
    return False


def _combine_with_rebalance(
    dates: List[str],
    leg_series: List[List[float]],
    weights: List[float],
    initial_cash: float,
    rebalance: str,
) -> "tuple[List[Dict[str, Any]], List[EquityPoint]]":
    """按目标权重合并多腿净值，支持周期性再平衡。

    - rebalance='none'：买入持有，各腿净值直接相加（与 V1.2 基线一致）。
    - 其它频率（D/W/M/Q/Y）：在再平衡日把各腿净值重置为目标权重 × 当前总值，
      其余交易日按各腿自身收益自然漂移。
    """
    combined_curve: List[Dict[str, Any]] = []
    combined_points: List[EquityPoint] = []
    n = len(leg_series)
    if n == 0:
        return combined_curve, combined_points

    leg_vals = [leg_series[k][0] for k in range(n)]
    prev_total = sum(leg_vals)
    prev_date = None
    for i, d in enumerate(dates):
        if i > 0:
            for k in range(n):
                prev_v = leg_series[k][i - 1]
                cur_v = leg_series[k][i]
                r = (cur_v / prev_v - 1.0) if prev_v else 0.0
                leg_vals[k] *= (1.0 + r)
            if _is_rebalance_date(d, prev_date, rebalance):
                total = sum(leg_vals)
                leg_vals = [w * total for w in weights]
        total = sum(leg_vals)
        daily = (total / prev_total - 1.0) if (i > 0 and prev_total) else 0.0
        allocation = {
            str(k): round(leg_vals[k] / total, 6) if total else 0.0
            for k in range(n)
        }
        combined_points.append(
            EquityPoint(
                date=d, cash=0.0, market_value=total,
                total_value=total, daily_return=daily,
            )
        )
        combined_curve.append(
            {
                "date": d,
                "cash": 0.0,
                "market_value": round(total, 4),
                "total_value": round(total, 4),
                "daily_return": round(daily, 6),
                "allocation": allocation,
            }
        )
        prev_total = total
        prev_date = d
    return combined_curve, combined_points


def _risk_decomposition(
    leg_curves: List[Dict[str, Any]], weights: List[float]
) -> Dict[str, Any]:
    """组合风险分解（V13，欧拉波动率分解）。

    用各腿对齐日历的净值序列算日收益，构建协方差矩阵 Σ：
    - 组合日波动 σ_p = sqrt(wᵀΣw)
    - 边际风险贡献 MCR_k = (Σw)_k / σ_p
    - 风险贡献 RC_k = w_k · MCR_k（日），各腿求和精确等于 σ_p
    - 相关系数矩阵 corr_kl = Σ_kl / sqrt(Σ_kk Σ_ll)
    年化乘以 sqrt(252)。单腿或收益样本不足时退化为各腿独立波动。
    """
    n = len(leg_curves)
    # 各腿日收益序列
    rets: List[List[float]] = []
    for lc in leg_curves:
        s = lc.get("series", [])
        r = []
        for i in range(1, len(s)):
            prev = s[i - 1].get("value", 0.0) or 0.0
            cur = s[i].get("value", 0.0) or 0.0
            r.append((cur / prev - 1.0) if prev else 0.0)
        rets.append(r)

    if n == 0:
        return {
            "portfolio_vol_annual": 0.0,
            "per_leg_vol_annual": [],
            "risk_contrib_annual": [],
            "risk_contrib_pct": [],
            "correlation": [],
            "weights": [],
        }

    if n == 1:
        rv = rets[0]
        vol = _std(rv) if len(rv) >= 2 else 0.0
        vol_annual = vol * math.sqrt(252)
        return {
            "portfolio_vol_annual": round(vol_annual, 6),
            "per_leg_vol_annual": [round(vol_annual, 6)],
            "risk_contrib_annual": [round(vol_annual, 6)],
            "risk_contrib_pct": [1.0],
            "correlation": [[1.0]],
            "weights": [round(weights[0], 6)],
        }

    T = min(len(r) for r in rets)
    if T < 2:
        per_leg_vol = []
        for k in range(n):
            rv = rets[k][:T]
            vol = _std(rv) if len(rv) >= 2 else 0.0
            per_leg_vol.append(round(vol * math.sqrt(252), 6))
        return {
            "portfolio_vol_annual": 0.0,
            "per_leg_vol_annual": per_leg_vol,
            "risk_contrib_annual": [0.0] * n,
            "risk_contrib_pct": [0.0] * n,
            "correlation": [[0.0] * n for _ in range(n)],
            "weights": [round(weights[k], 6) for k in range(n)],
        }

    R = [[rets[k][i] for i in range(T)] for k in range(n)]
    means = [sum(R[k]) / T for k in range(n)]
    cov: List[List[float]] = [[0.0] * n for _ in range(n)]
    for a in range(n):
        for b in range(a, n):
            s = sum((R[a][i] - means[a]) * (R[b][i] - means[b]) for i in range(T)) / (T - 1)
            cov[a][b] = cov[b][a] = s

    w = [weights[k] for k in range(n)]
    port_var = sum(w[a] * sum(w[b] * cov[a][b] for b in range(n)) for a in range(n))
    port_vol_daily = math.sqrt(port_var) if port_var > 0 else 0.0
    port_vol_annual = port_vol_daily * math.sqrt(252)

    sw = [sum(cov[k][b] * w[b] for b in range(n)) for k in range(n)]
    mcr = [sw[k] / port_vol_daily if port_vol_daily else 0.0 for k in range(n)]
    rc = [w[k] * mcr[k] for k in range(n)]
    rc_annual = [rc[k] * math.sqrt(252) for k in range(n)]
    rc_pct = [rc[k] / port_vol_daily if port_vol_daily else 0.0 for k in range(n)]

    per_leg_vol = [
        math.sqrt(cov[k][k]) * math.sqrt(252) if cov[k][k] > 0 else 0.0 for k in range(n)
    ]
    corr: List[List[float]] = [[0.0] * n for _ in range(n)]
    for a in range(n):
        for b in range(n):
            if a == b:
                corr[a][b] = 1.0  # 自相关系數恒为 1（即便该腿收益方差为 0）
                continue
            sa = math.sqrt(cov[a][a])
            sb = math.sqrt(cov[b][b])
            corr[a][b] = (cov[a][b] / (sa * sb)) if (sa and sb) else 0.0

    return {
        "portfolio_vol_annual": round(port_vol_annual, 6),
        "per_leg_vol_annual": [round(v, 6) for v in per_leg_vol],
        "risk_contrib_annual": [round(v, 6) for v in rc_annual],
        "risk_contrib_pct": [round(v, 6) for v in rc_pct],
        "correlation": [[round(v, 4) for v in row] for row in corr],
        "weights": [round(w[k], 6) for k in range(n)],
    }


def _std(xs: List[float]) -> float:
    """样本标准差（ddof=1）。"""
    n = len(xs)
    if n < 2:
        return 0.0
    mean = sum(xs) / n
    return math.sqrt(sum((x - mean) ** 2 for x in xs) / (n - 1))


def _equal_weight_benchmark(
    data: Dict[str, List[Any]],
    symbols: List[str],
    dates: List[str],
    combined_curve: List[Dict[str, Any]],
    initial_cash: float,
) -> "tuple[Optional[List[float]], Optional[List[Dict[str, Any]]]]":
    """构建等权买入持有基准（跨所有标的，与组合净值日期对齐）。

    返回 (benchmark_values, benchmark_curve)。每个标的使用自身收盘价做买入持有
    NAV，等权取均值作为组合基准。任意标的无行情时退化为 (None, None)。
    """
    closes: List[Dict[str, float]] = []
    bases: List[float] = []
    for sym in symbols:
        bars = data.get(sym)
        if not bars:
            return None, None
        close_by_date = {b.date: float(b.close) for b in bars}
        if not close_by_date:
            return None, None
        closes.append(close_by_date)
        bases.append(close_by_date[min(close_by_date)] or 1.0)

    values: List[float] = []
    curve: List[Dict[str, Any]] = []
    for i, d in enumerate(dates):
        navs = []
        ok = True
        for j, cbd in enumerate(closes):
            # 取该日期及之前最近一个交易日的收盘价（停牌沿用上一日）
            last = None
            for dd in dates[: i + 1]:
                if dd in cbd:
                    last = cbd[dd]
            if last is None:
                ok = False
                break
            navs.append(last / bases[j])
        if not ok or not navs:
            continue
        nav = initial_cash * (sum(navs) / len(navs))
        values.append(nav)
        if combined_curve:
            curve.append({"date": d, "value": round(nav, 2)})
    if len(values) < 2:
        return None, None
    return values, curve


def _aggregate_factor_exposure(
    legs: List[Dict[str, Any]],
    all_symbols: List[str],
    start: str,
    end: str,
) -> Dict[str, Any]:
    """组合因子暴露（V14）：按各腿权重聚合因子 IC/IR。

    每条腿按策略取默认因子，调用 factor_research.ic_analysis 计算因子 IC/IR，
    再以腿权重加权汇总到每个因子。输出各因子的加权 IC 均值、加权 IR 与暴露占比。
    因子分析失败时整体退化为空（不影响主回测）。
    """
    if not all_symbols or not start or not end:
        return {"factors": [], "notice": "样本不足"}
    # 汇总每条腿的因子及其权重
    leg_factors: List[Dict[str, Any]] = []
    for leg in legs:
        fs = default_factors(leg.get("strategy", ""))
        if fs:
            leg_factors.append({"weight": leg.get("weight", 0.0), "factors": fs})
    if not leg_factors:
        return {"factors": [], "notice": "各腿策略未配置关联因子"}

    agg: Dict[str, Dict[str, float]] = {}
    total_w = 0.0
    for lf in leg_factors:
        w = lf["weight"]
        total_w += w
        # 同一因子可能被多个腿引用，逐腿累加权重贡献
        for f in lf["factors"]:
            agg.setdefault(f, {"w": 0.0, "ic": 0.0, "ir": 0.0, "n": 0})
            agg[f]["w"] += w
    if total_w <= 0:
        return {"factors": [], "notice": "权重之和为 0"}

    # 各因子只算一次 IC/IR（用全部标的 + 全区间），按腿出现权重放大暴露
    computed = {}
    try:
        ic = factor_research.ic_analysis(
            symbols=all_symbols, start=start, end=end, window=10, forward=1
        )
        for factor_name, stat in (ic.get("results") or {}).items():
            if not stat:
                continue
            computed[factor_name] = {
                "ic_mean": stat.get("mean_ic") or 0.0,
                "ir": stat.get("ir") or 0.0,
            }
    except Exception as exc:  # 因子分析失败不影响主回测
        logger = __import__("logging").getLogger("quantflow.backtest.portfolio")
        logger.warning("portfolio factor exposure failed: %s", exc)
        return {"factors": [], "notice": "因子分析失败"}

    # 仅对确有 IC 结果的因子做暴露占比归一化（无 IC 的因子不展示）
    emitted = [(f, acc, computed[f]) for f, acc in agg.items() if computed.get(f)]
    total_factor_w = sum(acc["w"] for _, acc, _ in emitted) or 1.0
    factors_out = []
    for f, acc, c in emitted:
        exposure_w = acc["w"] / total_factor_w
        factors_out.append({
            "factor": f,
            "ic_mean": round(c["ic_mean"], 4),
            "ir": round(c["ir"], 4),
            "exposure_weight": round(exposure_w, 4),
        })
    factors_out.sort(key=lambda x: abs(x["ic_mean"]), reverse=True)
    return {
        "factors": factors_out,
        "total_exposure_weight": round(sum(f["exposure_weight"] for f in factors_out), 4),
    }
