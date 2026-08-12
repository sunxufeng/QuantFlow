"""Market-bar persistence boundary for M2."""

from __future__ import annotations

import threading
from abc import ABC, abstractmethod
from typing import Dict, List, Tuple

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
