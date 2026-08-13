"""数据节点：行情数据、财务数据（M3 数据节点）。

- ``data.quotes``   拉取日线行情（经 MarketService，支持缓存）
- ``data.financial`` 财务指标（合成演示数据，字段对齐常见财务数据集）
"""

from __future__ import annotations


from ..core.data import DataTable
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node


@work_node(
    "data.quotes",
    label="行情数据",
    category="数据",
    description="按标的与日期区间拉取日线行情（OHLCV），经 MarketService 走缓存",
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("symbol", "string", required=True, label="标的代码", description="如 TEST.STOCK / TEST.FUND"),
        ParamSpec("start", "string", default="2024-01-01", label="开始日期"),
        ParamSpec("end", "string", default="2024-02-01", label="结束日期"),
    ],
)
class QuotesNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        from ..market.service import market_service

        symbol = str(self.params["symbol"]).strip()
        start = str(self.params.get("start") or "2024-01-01")
        end = str(self.params.get("end") or "2024-02-01")
        bars = market_service.bars(symbol, start=start, end=end)
        rows = [
            {
                "symbol": b.symbol,
                "date": b.date,
                "open": b.open,
                "high": b.high,
                "low": b.low,
                "close": b.close,
                "volume": b.volume,
                "amount": b.amount,
            }
            for b in bars
        ]
        if not rows:
            ctx.log("warn", f"标的 {symbol} 在 {start}~{end} 无行情")
        return {"table": DataTable(
            columns=["symbol", "date", "open", "high", "low", "close", "volume", "amount"],
            rows=rows,
        )}


@work_node(
    "data.financial",
    label="财务数据",
    category="数据",
    description="财务指标表（演示数据）：营收/净利/ROE/毛利率/负债率，按标的生成",
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("symbol", "string", default="TEST.STOCK", label="标的代码"),
        ParamSpec("periods", "number", default=8, label="报告期数"),
        ParamSpec("seed", "number", default=1, label="随机种子"),
    ],
)
class FinancialNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        symbol = str(self.params["symbol"]).strip()
        periods = int(self.params["periods"] or 8)
        seed = int(self.params.get("seed") or 1)
        rng = _rng(seed + sum(ord(c) for c in symbol))
        rows = []
        year, quarter = 2024, 1
        revenue = 10_000_000.0 + rng() * 5_000_000
        for i in range(periods):
            revenue *= 1.0 + (rng() - 0.45) * 0.08  # 营收环比 ±4%
            net_profit = revenue * (0.08 + rng() * 0.05)
            equity = revenue * (1.2 + rng() * 0.6)
            roe = net_profit / equity if equity else 0.0
            rows.append({
                "symbol": symbol,
                "report_date": f"{year}Q{quarter}",
                "revenue": round(revenue, 2),
                "net_profit": round(net_profit, 2),
                "roe": round(roe, 4),
                "gross_margin": round(0.3 + rng() * 0.15, 4),
                "debt_ratio": round(0.4 + rng() * 0.2, 4),
            })
            quarter += 1
            if quarter > 4:
                quarter, year = 1, year + 1
        return {"table": DataTable(
            columns=["symbol", "report_date", "revenue", "net_profit", "roe", "gross_margin", "debt_ratio"],
            rows=rows,
        )}


def _rng(seed: int):
    state = (seed * 9301 + 49297) % 233280

    def _next() -> float:
        nonlocal state
        state = (state * 9301 + 49297) % 233280
        return state / 233280

    return _next
