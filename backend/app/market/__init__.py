"""行情数据层（M2）：数据源适配 + 缓存 + 服务入口。"""

from .cache import MemoryCache, RedisCache, default_cache
from .models import Bar, Instrument, bars_to_table
from .service import MarketService, market_service
from .sources import (
    DataSourceError,
    LocalDataSource,
    MarketDataSource,
    TushareDataSource,
)

__all__ = [
    "Bar",
    "Instrument",
    "bars_to_table",
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
]
