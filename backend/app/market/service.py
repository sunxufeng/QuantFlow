"""行情服务：多数据源调度 + 缓存 + 降级（M2 数据层）。

对外只暴露 ``MarketService``：
- ``bars(symbol, start, end, interval)``：带缓存的数据获取
- ``instruments()``：可用标的列表
- 数据源异常自动降级（tushare 无 token/网络失败 → 本地源）
"""

from __future__ import annotations

import json
import logging
from typing import List, Optional

from .cache import CacheBackend, default_cache
from .models import Bar, Instrument
from .sources import (
    DataSourceError,
    LocalDataSource,
    MarketDataSource,
    cache_key,
    default_data_source,
)

logger = logging.getLogger("quantflow.market.service")

# 日线默认起始（本地内置数据起点）
DEFAULT_START = "2024-01-01"
DEFAULT_END = "2024-02-01"
CACHE_TTL = 3600  # 行情缓存 1 小时


class MarketService:
    """行情数据统一入口。"""

    def __init__(
        self,
        primary: Optional[MarketDataSource] = None,
        fallback: Optional[MarketDataSource] = None,
        cache: Optional[CacheBackend] = None,
    ) -> None:
        self.primary = primary or default_data_source()
        self.fallback = fallback or LocalDataSource()
        self.cache = cache or default_cache()
        # 保证 primary != fallback（防止 tushare 失败后自旋）
        if self.primary is self.fallback:
            self.primary = LocalDataSource()

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

        bars = self._fetch(self.primary, symbol, start, end)
        source = self.primary.name
        if not bars and self.fallback is not None:
            logger.info("primary(%s) 无数据，降级到 %s", self.primary.name, self.fallback.name)
            bars = self._fetch(self.fallback, symbol, start, end)
            source = self.fallback.name
            key = cache_key(source, symbol, start, end, interval)

        if bars and use_cache:
            self.cache.set(key, [b.to_dict() for b in bars], CACHE_TTL)
        return bars

    def instruments(self) -> List[Instrument]:
        try:
            items = self.primary.symbols()
            if items:
                return items
        except DataSourceError:
            pass
        return self.fallback.symbols()

    def _fetch(self, source: MarketDataSource, symbol: str, start: str, end: str) -> List[Bar]:
        try:
            return source.fetch_daily(symbol, start, end)
        except DataSourceError as exc:
            logger.warning("数据源 %s 获取 %s 失败：%s", source.name, symbol, exc)
            return []
        except Exception as exc:  # pragma: no cover - 网络等不可控
            logger.exception("数据源 %s 异常：%s", source.name, exc)
            return []


# 全局单例（API 层使用）
market_service = MarketService()
