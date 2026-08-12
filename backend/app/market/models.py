"""行情数据模型（M2 数据层）。

V1.0 只做日线（Q-06 决策）；结构上为分钟线预留字段
（``interval`` + 可选 ``datetime``），V1.3 开启分钟级时无需改表。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..core.data import DataTable

# 日线 / 分钟线（预留）
INTERVAL_DAILY = "daily"
INTERVAL_MINUTE = "minute"


@dataclass
class Bar:
    """一根 K 线。

    date 为交易日（YYYY-MM-DD）；分钟级时 date 保留日期，
    datetime 字段存放完整时间戳（预留）。
    """

    symbol: str
    date: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    amount: float = 0.0
    interval: str = INTERVAL_DAILY
    datetime: Optional[str] = None  # 分钟级预留
    source: str = ""  # provider / fixture，保证数据可追溯
    adjustment: str = "none"  # none / qfq / hfq

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "date": self.date,
            "datetime": self.datetime,
            "open": self.open,
            "high": self.high,
            "low": self.low,
            "close": self.close,
            "volume": self.volume,
            "amount": self.amount,
            "interval": self.interval,
            "source": self.source,
            "adjustment": self.adjustment,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Bar":
        return cls(
            symbol=data["symbol"],
            date=data["date"],
            open=float(data["open"]),
            high=float(data["high"]),
            low=float(data["low"]),
            close=float(data["close"]),
            volume=float(data.get("volume", 0.0)),
            amount=float(data.get("amount", 0.0)),
            interval=data.get("interval", INTERVAL_DAILY),
            datetime=data.get("datetime"),
            source=data.get("source", ""),
            adjustment=data.get("adjustment", "none"),
        )


@dataclass
class Instrument:
    """标的元信息。"""

    symbol: str
    name: str
    exchange: str = ""
    market: str = "stock"  # stock / fund / future
    currency: str = "CNY"
    lot_size: int = 100  # 一手股数
    price_tick: float = 0.01  # 最小变动价位
    # 合约信息（期货预留）
    contract_multiplier: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return {
            "symbol": self.symbol,
            "name": self.name,
            "exchange": self.exchange,
            "market": self.market,
            "currency": self.currency,
            "lot_size": self.lot_size,
            "price_tick": self.price_tick,
            "contract_multiplier": self.contract_multiplier,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "Instrument":
        return cls(
            symbol=data["symbol"],
            name=data["name"],
            exchange=data.get("exchange", ""),
            market=data.get("market", "stock"),
            currency=data.get("currency", "CNY"),
            lot_size=int(data.get("lot_size", 100)),
            price_tick=float(data.get("price_tick", 0.01)),
            contract_multiplier=float(data.get("contract_multiplier", 1.0)),
        )


def bars_to_table(bars: List[Bar]) -> DataTable:
    """K 线列表 -> DataTable（供工作流节点消费）。"""
    columns = [
        "symbol",
        "date",
        "open",
        "high",
        "low",
        "close",
        "volume",
        "amount",
        "source",
        "adjustment",
    ]
    if any(b.datetime for b in bars):
        columns.insert(2, "datetime")
    rows = [{c: b.to_dict().get(c) for c in columns} for b in bars]
    return DataTable(columns=columns, rows=rows)
