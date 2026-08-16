"""行情数据层（M2）：数据源适配 + 缓存 + 服务入口。"""

from .cache import CacheBackend, MemoryCache, RedisCache, default_cache
from .models import Bar, Instrument, bars_to_table
from .repository import InMemoryMarketDataRepository, MarketDataRepository
from .service import MarketService, market_service
from .sources import (
    CTPDataSource,
    CryptoDataSource,
    DataSourceError,
    LocalDataSource,
    MarketDataSource,
    QMTDataSource,
    TushareDataSource,
    available_data_sources,
)

__all__ = [
    "Bar",
    "Instrument",
    "bars_to_table",
    "MarketDataRepository",
    "InMemoryMarketDataRepository",
    "CacheBackend",
    "MemoryCache",
    "RedisCache",
    "default_cache",
    "MarketService",
    "market_service",
    "DataSourceError",
    "LocalDataSource",
    "MarketDataSource",
    "TushareDataSource",
    "CTPDataSource",
    "QMTDataSource",
    "CryptoDataSource",
    "available_data_sources",
]
