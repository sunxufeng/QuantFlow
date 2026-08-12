"""Market-bar persistence boundary for M2."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

from ..core.db import db
from .models import Bar


class MarketDataRepository(ABC):
    """Durable bar storage contract; Mongo can replace the memory adapter."""

    @abstractmethod
    def read_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        """Return bars in the inclusive date range, ordered ascending."""

    @abstractmethod
    def upsert_daily(self, bars: List[Bar]) -> int:
        """Insert or replace bars and return the number processed."""


class InMemoryMarketDataRepository(MarketDataRepository):
    """Thread-safe M2 adapter used by tests and single-process development."""

    def __init__(self) -> None:
        self._items: Dict[Tuple[str, str, str], Bar] = {}
        self._lock = threading.RLock()

    def read_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        with self._lock:
            bars = [
                Bar.from_dict(bar.to_dict())
                for (item_symbol, date, interval), bar in self._items.items()
                if item_symbol == symbol and interval == "daily" and start <= date <= end
            ]
        return sorted(bars, key=lambda bar: bar.date)

    def upsert_daily(self, bars: List[Bar]) -> int:
        with self._lock:
            for bar in bars:
                self._items[(bar.symbol, bar.date, bar.interval)] = Bar.from_dict(bar.to_dict())
        return len(bars)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


class SQLiteMarketDataRepository(MarketDataRepository):
    """SQLite 持久化适配器（V1.1 N4）：行情落库、可追溯、可复查。

    - 复用业务库单例 ``db``；表 ``market_bars`` 主键 (symbol, date, interval)；
    - ``upsert_daily`` 采用 upsert，便于定时增量更新；
    - 读路径与 :class:`InMemoryMarketDataRepository` 行为一致。
    """

    def read_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        rows = db.query(
            "SELECT symbol, date, interval, open, high, low, close, volume, amount, source, adjustment "
            "FROM market_bars "
            "WHERE symbol = ? AND interval = 'daily' AND date >= ? AND date <= ? "
            "ORDER BY date ASC",
            (symbol, start, end),
        )
        bars: List[Bar] = []
        for r in rows:
            bars.append(
                Bar(
                    symbol=r["symbol"],
                    date=r["date"],
                    interval=r["interval"],
                    open=float(r["open"]),
                    high=float(r["high"]),
                    low=float(r["low"]),
                    close=float(r["close"]),
                    volume=float(r["volume"]),
                    amount=float(r["amount"]),
                    source=r["source"],
                    adjustment=r["adjustment"],
                )
            )
        return bars

    def upsert_daily(self, bars: List[Bar]) -> int:
        if not bars:
            return 0
        rows = [
            (
                b.symbol,
                b.date,
                b.interval,
                b.open,
                b.high,
                b.low,
                b.close,
                b.volume,
                b.amount,
                b.source,
                b.adjustment,
            )
            for b in bars
        ]
        with db._lock:
            db._ensure().executemany(
                "INSERT INTO market_bars "
                "(symbol, date, interval, open, high, low, close, volume, amount, source, adjustment) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(symbol, date, interval) DO UPDATE SET "
                "open=excluded.open, high=excluded.high, low=excluded.low, close=excluded.close, "
                "volume=excluded.volume, amount=excluded.amount, "
                "source=excluded.source, adjustment=excluded.adjustment",
                rows,
            )
            db._ensure().commit()
        return len(bars)

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS n FROM market_bars")
        return int(row["n"]) if row else 0

    def clear(self) -> None:
        with db._lock:
            db._ensure().execute("DELETE FROM market_bars")
            db._ensure().commit()

