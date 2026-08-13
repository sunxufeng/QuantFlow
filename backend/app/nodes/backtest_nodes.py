"""回测节点：策略回测、绩效分析、结果导出（M3 回测节点）。

对齐开发计划 §4.3「回测节点：策略回测（股/期）、绩效分析、结果导出」。

设计：
- ``backtest.run`` 将上游行情表转为 Bar 序列，调用 M2 回测引擎
  （BacktestEngine + STRATEGY_REGISTRY），输出净值曲线与交易明细。
- ``backtest.performance`` 对净值曲线表计算绩效指标（收益/回撤/夏普等）。
- ``backtest.export_json`` / ``backtest.export_csv`` 将表格导出为文本端口。
"""

from __future__ import annotations

import json
from typing import Any, List

from ..core.data import DataTable
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node
from ._utils import require_table, table_to_df


def _table_to_bars(table: DataTable) -> List[Any]:
    from ..market.models import Bar

    bars: List[Bar] = []
    for row in table.rows:
        try:
            bars.append(
                Bar(
                    symbol=str(row.get("symbol") or ""),
                    date=str(row["date"]),
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row.get("volume") or 0.0),
                    amount=float(row.get("amount") or 0.0),
                )
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError(f"行情表第 {len(bars) + 1} 行缺字段或字段非法: {exc}") from exc
    return bars


@work_node(
    "backtest.run",
    label="策略回测",
    category="回测",
    description="对上游行情表运行内置策略（buy_hold/ma_cross/fund_dingtou），输出净值曲线与交易明细",
    inputs=[PortSpec("table", "table", label="行情表")],
    outputs=[
        PortSpec("equity", "table", label="净值曲线"),
        PortSpec("trades", "table", label="交易明细"),
        PortSpec("summary", "table", label="概要"),
        PortSpec("attribution", "string", label="绩效归因"),
    ],
    params=[
        ParamSpec("strategy", "string", default="buy_hold", label="策略",
                  options=["buy_hold", "ma_cross", "fund_dingtou", "futures_ma_cross"]),
        ParamSpec("initial_cash", "number", default=1_000_000.0, label="初始资金"),
        ParamSpec("symbol", "string", default="", label="标的（空=取行情表首行 symbol）"),
        ParamSpec("asset_type", "string", default="stock", label="资产类型", options=["stock", "fund", "future"]),
        ParamSpec("contracts", "number", default=1, label="期货手数（仅期货策略）"),
        ParamSpec("multiplier", "number", default=10.0, label="合约乘数（仅期货）"),
    ],
)
class BacktestRunNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        from ..backtest import BacktestEngine, STRATEGY_REGISTRY
        from ..backtest.costs import CostRates
        from ..market.models import Instrument

        table = require_table(inputs["table"])
        bars = _table_to_bars(table)
        if not bars:
            raise ValueError("行情表为空，无法回测")
        symbol = str(self.params.get("symbol") or "").strip() or bars[0].symbol
        asset_type = str(self.params.get("asset_type") or "stock").strip()
        if asset_type == "fund":
            exchange = ""
        elif asset_type == "future":
            exchange = "CFFEX"
        else:
            exchange = "SH"
        instrument = Instrument(
            symbol=symbol,
            name=symbol,
            exchange=exchange,
            market=asset_type,
            contract_multiplier=float(self.params.get("multiplier") or 10.0)
            if asset_type == "future" else 1.0,
        )
        data = {symbol: sorted(bars, key=lambda b: b.date)}
        strategy_name = str(self.params.get("strategy") or "buy_hold")
        try:
            factory = STRATEGY_REGISTRY[strategy_name]
        except KeyError:
            raise ValueError(
                f"未知策略: {strategy_name}（支持 buy_hold/ma_cross/fund_dingtou/futures_ma_cross）"
            ) from None
        params = {}
        if strategy_name in ("ma_cross", "fund_dingtou", "buy_hold"):
            params = {"symbol": symbol}
        elif strategy_name == "futures_ma_cross":
            params = {"symbol": symbol, "contracts": int(self.params.get("contracts") or 1)}
        strategy = factory(params)
        engine = BacktestEngine(
            strategy,
            data,
            initial_cash=float(self.params.get("initial_cash") or 1_000_000.0),
            cost_rates=CostRates(),
            instruments={symbol: instrument},
        )
        result = engine.run()
        # 基准：买入持有（首笔资金按首日收盘建仓，随收盘价缩放）
        benchmark_values = None
        try:
            if bars:
                first_close = float(bars[0].close)
                benchmark_values = [
                    float(self.params.get("initial_cash") or 1_000_000.0) * (float(b.close) / first_close)
                    for b in bars
                ]
        except (IndexError, KeyError, TypeError, ValueError):
            benchmark_values = None
        from ..backtest.metrics import PerformanceMetrics

        pm = PerformanceMetrics(
            result.equity_curve,
            result.engine.initial_cash,
            result.trades,
            benchmark_values=benchmark_values,
        )
        attr = pm.to_dict()["attribution"]
        equity = DataTable(
            columns=["date", "cash", "market_value", "total_value", "daily_return"],
            rows=[
                {
                    "date": p.date,
                    "cash": round(p.cash, 2),
                    "market_value": round(p.market_value, 2),
                    "total_value": round(p.total_value, 2),
                    "daily_return": round(p.daily_return, 6),
                }
                for p in result.equity_curve
            ],
        )
        def _num(v, default=0.0) -> float:
            try:
                return 0.0 if v is None else float(v)
            except (TypeError, ValueError):
                return default

        trades = DataTable(
            columns=["date", "symbol", "side", "price", "shares", "amount", "fee", "pnl"],
            rows=[
                {
                    "date": getattr(t, "date", ""),
                    "symbol": getattr(t, "symbol", ""),
                    "side": getattr(t, "side", ""),
                    "price": round(_num(getattr(t, "price", 0.0)), 4),
                    "shares": _num(getattr(t, "shares", 0.0)),
                    "amount": round(_num(getattr(t, "price", 0.0)) * _num(getattr(t, "shares", 0.0)), 2),
                    "fee": round(sum(_num(v) for v in getattr(t, "costs", {}).values()), 2),
                    "pnl": round(_num(getattr(t, "pnl", None)), 2),
                }
                for t in result.trades
            ],
        )
        total = equity.rows[-1]["total_value"] if equity.rows else 0.0
        base = equity.rows[0]["total_value"] if equity.rows else 0.0
        summary_rows = [
            {"metric": "strategy", "value": strategy_name},
            {"metric": "symbol", "value": symbol},
            {"metric": "days", "value": len(equity.rows)},
            {"metric": "initial_cash", "value": float(self.params.get("initial_cash") or 1_000_000.0)},
            {"metric": "final_value", "value": round(total, 2)},
            # 与 equity 曲线同口径：相对首日净值（已含首日成本）
            {"metric": "total_return", "value": round(total / base - 1.0, 6) if base else 0.0},
            {"metric": "trade_count", "value": len(trades.rows)},
        ]
        # 绩效归因（V1.5）：交易层面 + 曲线层面 + 基准对比
        trade_attr = attr.get("trade", {})
        if trade_attr:
            for key, label in [
                ("profit_factor", "盈亏比(profit_factor)"),
                ("avg_win", "平均盈利"),
                ("avg_loss", "平均亏损"),
                ("payoff_ratio", " payoff_ratio"),
                ("max_win_streak", "最大连胜"),
                ("max_loss_streak", "最大连亏"),
            ]:
                if key in trade_attr:
                    summary_rows.append({"metric": label, "value": round(trade_attr[key], 4) if isinstance(trade_attr[key], float) else trade_attr[key]})
        curve_attr = attr.get("curve", {})
        if curve_attr:
            if "max_drawdown_days" in curve_attr:
                summary_rows.append({"metric": "最大回撤天数", "value": curve_attr["max_drawdown_days"]})
            if "exposure_ratio" in curve_attr:
                summary_rows.append({"metric": "持仓暴露比", "value": round(curve_attr["exposure_ratio"], 4)})
        bench_attr = attr.get("benchmark", {})
        if bench_attr:
            for key, label in [
                ("benchmark_return", "基准收益(买入持有)"),
                ("excess_return", "超额收益"),
                ("alpha", "alpha(年化)"),
                ("beta", "beta"),
            ]:
                if key in bench_attr:
                    summary_rows.append({"metric": label, "value": round(bench_attr[key], 6)})
        summary = DataTable(columns=["metric", "value"], rows=summary_rows)
        return {
            "equity": equity,
            "trades": trades,
            "summary": summary,
            "attribution": json.dumps(attr, ensure_ascii=False, default=str),
        }


@work_node(
    "backtest.performance",
    label="绩效分析",
    category="回测",
    description="基于净值曲线表计算绩效指标：收益、年化、最大回撤、夏普、波动率",
    inputs=[PortSpec("equity", "table", label="净值曲线")],
    outputs=[
        PortSpec("metrics", "table", label="绩效指标"),
        PortSpec("attribution", "string", label="绩效归因"),
    ],
    params=[
        ParamSpec("annual_factor", "number", default=252, label="年化交易日"),
        ParamSpec("risk_free", "number", default=0.0, label="无风险利率（年化）"),
    ],
)
class PerformanceNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        from ..backtest.metrics import PerformanceMetrics
        from ..backtest.engine import EquityPoint

        table = require_table(inputs["equity"])
        if "total_value" not in table.columns:
            raise ValueError("净值曲线表缺少 total_value 列")
        points = [
            EquityPoint(
                date=str(r.get("date") or ""),
                cash=float(r.get("cash") or 0.0),
                market_value=float(r.get("market_value") or 0.0),
                total_value=float(r.get("total_value") or 0.0),
                daily_return=float(r.get("daily_return") or 0.0),
            )
            for r in table.rows
        ]
        if len(points) < 2:
            raise ValueError("净值曲线至少需要 2 个点")
        factor = max(float(self.params.get("annual_factor") or 252), 1.0)
        rf = float(self.params.get("risk_free") or 0.0)
        pm = PerformanceMetrics(points, points[0].total_value, [], benchmark_values=None)
        base = pm.to_dict()
        # 用节点自身参数重算夏普（含无风险利率），覆盖 engine 默认 rf=0
        values = [p.total_value for p in points]
        returns = [values[i] / values[i - 1] - 1.0 if values[i - 1] else 0.0 for i in range(1, len(values))]
        mean_r = sum(returns) / len(returns)
        std_r = (sum((r - mean_r) ** 2 for r in returns) / len(returns)) ** 0.5
        sharpe = (mean_r * factor - rf) / (std_r * (factor ** 0.5)) if std_r > 0 else 0.0
        rows = [
            {"metric": "days", "value": len(values)},
            {"metric": "total_return", "value": round(base["total_return"], 6)},
            {"metric": "annual_return", "value": round(base["annual_return"], 6)},
            {"metric": "max_drawdown", "value": round(base["max_drawdown"], 6)},
            {"metric": "sharpe", "value": round(sharpe, 6)},
            {"metric": "annual_volatility", "value": round(std_r * (factor ** 0.5), 6)},
        ]
        # 曲线层面归因
        curve_attr = base["attribution"].get("curve", {})
        if "max_drawdown_days" in curve_attr:
            rows.append({"metric": "最大回撤天数", "value": curve_attr["max_drawdown_days"]})
        if "exposure_ratio" in curve_attr:
            rows.append({"metric": "持仓暴露比", "value": round(curve_attr["exposure_ratio"], 4)})
        return {
            "metrics": DataTable(columns=["metric", "value"], rows=rows),
            "attribution": json.dumps(base["attribution"], ensure_ascii=False, default=str),
        }


@work_node(
    "backtest.export_json",
    label="结果导出 JSON",
    category="回测",
    description="将表格序列化为 JSON 字符串输出",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("json", "string")],
)
class ExportJsonNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        table = require_table(inputs["table"])
        payload = table.to_dict()
        return {"json": json.dumps(payload, ensure_ascii=False, default=str)}


@work_node(
    "backtest.export_csv",
    label="结果导出 CSV",
    category="回测",
    description="将表格序列化为 CSV 字符串输出",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("csv", "string")],
)
class ExportCsvNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        table = require_table(inputs["table"])
        import csv
        import io

        buf = io.StringIO()
        writer = csv.DictWriter(buf, fieldnames=table.columns, extrasaction="ignore")
        writer.writeheader()
        for row in table.rows:
            writer.writerow({k: row.get(k) for k in table.columns})
        return {"csv": buf.getvalue()}
