"""组合回测（V1.2）。

将多个「腿」（策略 + 标的 + 权重）各自独立回测后，按权重合并为组合净值曲线，
输出组合净值、各腿配置占比（随时间）、各腿贡献与组合绩效指标。

设计要点：
- 每条腿以「分配资金 = 总资金 × 归一化权重」独立运行现有回test引擎，互不影响
- 组合净值 = 各腿净值按日对齐后求和（买入持有、无再平衡，V1.2 基线）
- 再平衡（rebalance）当前仅支持 "none"；周期性再平衡为后续增强项
- 复用 STRATEGY_REGISTRY / market_service / PerformanceMetrics，零新依赖
"""

from __future__ import annotations

import uuid
from typing import Any, Dict, List

from .engine import BacktestEngine, BacktestError, EquityPoint
from .metrics import PerformanceMetrics
from .strategies import STRATEGY_REGISTRY
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
        for leg in self.legs:
            # 1. 拉取行情
            data: Dict[str, Any] = {}
            for sym in leg["symbols"]:
                bars = market_service.bars(
                    sym, self.start, self.end, interval=leg.get("interval", "daily")
                )
                if not bars:
                    raise BacktestError(
                        f"标的 {sym} 在 {self.start}~{self.end} 无行情数据"
                    )
                data[sym] = bars
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
        metrics = PerformanceMetrics(combined_points, self.initial_cash, all_trades)

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

        # 汇总所有腿的标的（去重保序）
        all_symbols: List[str] = []
        for leg in self.legs:
            for s in leg["symbols"]:
                if s not in all_symbols:
                    all_symbols.append(s)
        start_date = self.start or (combined_curve[0]["date"] if combined_curve else "")
        end_date = self.end or (combined_curve[-1]["date"] if combined_curve else "")
        interval = self.legs[0].get("interval", "daily") if self.legs else "daily"

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
            "metrics": metrics.to_dict(),
            "equity_curve": combined_curve,
            "calendar": dates,
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
