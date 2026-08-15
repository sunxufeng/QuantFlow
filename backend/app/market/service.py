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

    # ------------------------------------------------------------------ #
    # 用户行情导入（V7.1）：用户上传 CSV -> 落库，回测/行情可直接使用
    # ------------------------------------------------------------------ #
    def upload_bars(self, symbol: str, bars: List[Bar]) -> int:
        """把用户上传的日线写入持久化层（source='upload'），返回写入条数。"""
        if not bars:
            return 0
        written = self.repository.upsert_daily(bars)
        # 让缓存失效（旧 provider 缓存可能已含该 symbol 的空/错误结果）
        self.cache.delete(
            cache_key(self.primary.name, symbol, DEFAULT_START, DEFAULT_END, "daily")
        )
        return written

    def uploaded_symbols(self) -> List[dict]:
        """返回所有用户导入（source='upload'）的标的快照。"""
        return [s for s in self.repository.list_symbols() if s.get("source") == "upload"]

    def delete_uploaded(self, symbol: str) -> int:
        """删除用户导入的标的（同时清缓存）。"""
        n = self.repository.delete_symbol(symbol)
        self.cache.delete(
            cache_key(self.primary.name, symbol, DEFAULT_START, DEFAULT_END, "daily")
        )
        return n

    # ------------------------------------------------------------------ #
    # 缓存/数据源管理（V5.0）：可见性 + 强制刷新
    # ------------------------------------------------------------------ #
    def cache_summary(self) -> dict:
        """快照：数据源模式、缓存后端、库中总 K 线、各标的中继情况。"""
        import os

        return {
            "provider_mode": os.getenv("QF_MARKET_PROVIDER", "tushare"),
            "provider": self.primary.name,
            "adjustment": self.primary.adjustment,
            "cache_backend": self.cache.name,
            "total_bars": self.repository.count(),
            "cache_ttl_seconds": CACHE_TTL,
            "symbols": self.repository.list_symbols(),
        }

    def refresh(
        self,
        symbols: Optional[List[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> dict:
        """强制从数据源重新拉取并落库（绕过热缓存），返回刷新摘要。

        - symbols 为空时默认刷新当前数据源支持的全部标的；
        - tushare 数据源不支持 ``symbols()``，必须显式传入 symbols。
        """
        start = start or DEFAULT_START
        end = end or DEFAULT_END
        if not symbols:
            try:
                instruments = self.primary.symbols()
            except DataSourceError as exc:
                raise DataSourceError(
                    "该数据源不支持自动列举标的，请在刷新时显式指定 symbols"
                ) from exc
            symbols = [i.symbol for i in instruments]
        refreshed: List[dict] = []
        for sym in symbols:
            bars = self._fetch(self.primary, sym, start, end)
            if bars:
                self.repository.upsert_daily(bars)
            refreshed.append({"symbol": sym, "count": len(bars)})
        return {
            "refreshed": refreshed,
            "total_bars": self.repository.count(),
            "provider": self.primary.name,
            "start": start,
            "end": end,
        }

    def _fetch(self, source: MarketDataSource, symbol: str, start: str, end: str) -> List[Bar]:
        try:
            return source.fetch_daily(symbol, start, end)
        except DataSourceError:
            raise
        except Exception as exc:  # pragma: no cover - network/provider failure
            raise DataSourceError(f"{source.name} failed to fetch {symbol}: {exc}") from exc


# 全局单例（API 层使用）
market_service = MarketService()
