"""Market-data service: cache -> repository -> configured provider."""

from __future__ import annotations

import logging
from typing import List, Optional

from .cache import CacheBackend, default_cache
from .models import Bar, Instrument, INTERVAL_MINUTE
from .repository import (
    MarketDataRepository,
    SQLiteMarketDataRepository,
)
from .sources import DataSourceError, MarketDataSource, cache_key, default_data_source

logger = logging.getLogger("quantflow.market.service")

# 日线默认起始（本地内置数据起点）
DEFAULT_START = "2024-01-01"
DEFAULT_END = "2024-02-01"
CACHE_TTL = 3600  # 行情缓存 1 小时

# 默认持久化后端：SQLite（V1.1 N4 行情落库）；测试可显式传入内存版。
_DEFAULT_REPOSITORY = SQLiteMarketDataRepository


class MarketService:
    """行情数据统一入口。"""

    def __init__(
        self,
        primary: Optional[MarketDataSource] = None,
        cache: Optional[CacheBackend] = None,
        repository: Optional[MarketDataRepository] = None,
    ) -> None:
        self.primary = primary or default_data_source()
        self.cache = cache or default_cache()
        self.repository = repository or _DEFAULT_REPOSITORY()

    def bars(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
        interval: str = "daily",
        use_cache: bool = True,
    ) -> List[Bar]:
        start = start or DEFAULT_START
        end = end or DEFAULT_END
        key = cache_key(self.primary.name, symbol, start, end, interval)

        if use_cache:
            cached = self.cache.get(key)
            if cached is not None:
                return [Bar.from_dict(b) for b in cached]

        if interval == INTERVAL_MINUTE:
            bars = self._fetch_minute(self.primary, symbol, start, end)
        else:
            bars = self.repository.read_daily(symbol, start, end)
            if not bars:
                bars = self._fetch(self.primary, symbol, start, end)
                if bars:
                    self.repository.upsert_daily(bars)

        if bars and use_cache:
            self.cache.set(key, [b.to_dict() for b in bars], CACHE_TTL)
        return bars

    def _fetch_minute(self, source: MarketDataSource, symbol: str, start: str, end: str) -> List[Bar]:
        try:
            return source.fetch_minute(symbol, start, end)
        except DataSourceError:
            raise
        except Exception as exc:  # pragma: no cover - provider failure
            raise DataSourceError(f"{source.name} failed to fetch minute {symbol}: {exc}") from exc

    def instruments(self) -> List[Instrument]:
        return self.primary.symbols()

    def _fetch(self, source: MarketDataSource, symbol: str, start: str, end: str) -> List[Bar]:
        try:
            return source.fetch_daily(symbol, start, end)
        except DataSourceError:
            raise
        except Exception as exc:  # pragma: no cover - network/provider failure
            raise DataSourceError(f"{source.name} failed to fetch {symbol}: {exc}") from exc


# 全局单例（API 层使用）
market_service = MarketService()
