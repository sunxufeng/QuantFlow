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

        # 2. 按日对齐合并净值
        all_dates: set = set()
        for r in leg_results:
            for p in r["result"].equity_curve:
                all_dates.add(p.date)
        if self.start:
            all_dates.add(self.start)
        if self.end:
            all_dates.add(self.end)
        dates = sorted(all_dates)

        combined_points: List[EquityPoint] = []   # 供绩效指标计算
        combined_curve: List[Dict[str, Any]] = []  # 输出（含配置占比）
        prev_total = self.initial_cash
        for d in dates:
            cash = mv = total = 0.0
            leg_vals: List[float] = []
            for r in leg_results:
                pt = _point_at(r["result"], d, r["allocated"])
                cash += pt.cash
                mv += pt.market_value
                total += pt.total_value
                leg_vals.append(pt.total_value)
            daily = total / prev_total - 1.0 if prev_total else 0.0
            combined_points.append(
                EquityPoint(
                    date=d, cash=cash, market_value=mv,
                    total_value=total, daily_return=daily,
                )
            )
            allocation = {
                str(i): round(v / total, 6) if total else 0.0
                for i, v in enumerate(leg_vals)
            }
            combined_curve.append(
                {
                    "date": d,
                    "cash": round(cash, 4),
                    "market_value": round(mv, 4),
                    "total_value": round(total, 4),
                    "daily_return": round(daily, 6),
                    "allocation": allocation,
                }
            )
            prev_total = total

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
