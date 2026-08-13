"""M2 数据层测试：行情模型、数据源、缓存、服务降级。"""

from __future__ import annotations

import pytest

from app.market import (
    Bar,
    DataSourceError,
    InMemoryMarketDataRepository,
    LocalDataSource,
    MemoryCache,
    bars_to_table,
)
from app.market.cache import RedisCache
from app.market.sources import TushareDataSource, cache_key
from app.market.service import MarketService


class _EmptySource(LocalDataSource):
    """返回空数据的测试数据源（模拟主源无数据）。"""

    name = "empty"

    def fetch_daily(self, symbol, start, end):
        return []


class _FailSource(LocalDataSource):
    """抛异常的数据源（模拟 tushare 未授权）。"""

    name = "fail"

    def fetch_daily(self, symbol, start, end):
        raise DataSourceError("no token")


# --------------------------------------------------------------------------- #
# 模型
# --------------------------------------------------------------------------- #
def test_bar_roundtrip():
    bar = Bar(symbol="600519.SH", date="2024-01-02", open=1, high=2, low=0.5, close=1.5, volume=100)
    restored = Bar.from_dict(bar.to_dict())
    assert restored == bar
    assert restored.datetime is None
    assert restored.interval == "daily"


def test_bars_to_table():
    bars = [
        Bar(symbol="600519.SH", date="2024-01-02", open=1, high=2, low=0.5, close=1.5, volume=100),
        Bar(symbol="600519.SH", date="2024-01-03", open=1.5, high=2, low=1, close=1.8, volume=120),
    ]
    table = bars_to_table(bars)
    assert table.columns == [
        "symbol", "date", "open", "high", "low", "close", "volume", "amount", "source", "adjustment", "dividend"
    ]
    assert len(table) == 2
    assert table.rows[0]["close"] == 1.5


def test_bars_to_table_empty():
    table = bars_to_table([])
    assert len(table) == 0
    assert "close" in table.columns


# --------------------------------------------------------------------------- #
# 数据源
# --------------------------------------------------------------------------- #
def test_local_source_fetch_range():
    src = LocalDataSource()
    bars = src.fetch_daily("TEST.STOCK", "2024-01-02", "2024-01-05")
    assert len(bars) == 4
    assert bars[0].date == "2024-01-02"
    assert bars[-1].date == "2024-01-05"


def test_local_source_unknown_symbol():
    src = LocalDataSource()
    assert src.fetch_daily("999999.X", "2024-01-01", "2024-02-01") == []


def test_local_source_symbols_include_etf():
    src = LocalDataSource()
    symbols = {i.symbol for i in src.symbols()}
    assert "TEST.FUND" in symbols


def test_tushare_without_token_raises():
    src = TushareDataSource(token=None)
    with pytest.raises(DataSourceError):
        src.fetch_daily("600519.SH", "2024-01-01", "2024-01-02")


# --------------------------------------------------------------------------- #
# 缓存
# --------------------------------------------------------------------------- #
def test_memory_cache_ttl():
    c = MemoryCache()
    c.set("k", {"a": 1}, ttl=10)
    assert c.get("k") == {"a": 1}


def test_memory_cache_expired():
    c = MemoryCache()
    c.set("k", 1, ttl=-1)  # 立即过期
    assert c.get("k") is None


def test_redis_cache_fallback_to_memory():
    """Redis 不可用时自动降级为内存，不影响功能。"""
    c = RedisCache(url="redis://127.0.0.1:1", fallback_ttl=60)  # 不存在的端口
    c.set("k", [1, 2, 3], ttl=60)
    assert c.get("k") == [1, 2, 3]


def test_cache_key_deterministic():
    k1 = cache_key("fixture", "TEST.STOCK", "2024-01-01", "2024-02-01", "daily")
    k2 = cache_key("fixture", "TEST.STOCK", "2024-01-01", "2024-02-01", "daily")
    assert k1 == k2
    assert len(k1) == 24


# --------------------------------------------------------------------------- #
# 服务
# --------------------------------------------------------------------------- #
def test_service_primary_local():
    svc = MarketService(primary=LocalDataSource(), cache=MemoryCache())
    bars = svc.bars("TEST.STOCK")
    assert len(bars) == 20
    assert bars[0].close > 0


def test_service_empty_primary_returns_empty():
    svc = MarketService(primary=_EmptySource(), cache=MemoryCache())
    bars = svc.bars("TEST.STOCK", start="2024-01-02", end="2024-01-05")
    assert bars == []


def test_service_failing_primary_is_explicit():
    svc = MarketService(primary=_FailSource(), cache=MemoryCache())
    with pytest.raises(DataSourceError):
        svc.bars("TEST.BANK", start="2024-01-02", end="2024-01-04")


def test_service_cache_hit():
    svc = MarketService(primary=LocalDataSource(), cache=MemoryCache())
    svc.bars("TEST.STOCK")
    # 第二次命中缓存（返回相同数据）
    bars = svc.bars("TEST.STOCK")
    assert len(bars) == 20


def test_service_instruments():
    svc = MarketService(primary=LocalDataSource(), cache=MemoryCache())
    assert len(svc.instruments()) >= 3


def test_service_unknown_symbol_empty():
    svc = MarketService(primary=LocalDataSource(), cache=MemoryCache())
    assert svc.bars("999999.X") == []


def test_repository_roundtrip_and_service_read_through():
    repository = InMemoryMarketDataRepository()
    source = LocalDataSource()
    svc = MarketService(primary=source, cache=MemoryCache(), repository=repository)
    fetched = svc.bars("TEST.STOCK", start="2024-01-02", end="2024-01-05", use_cache=False)
    assert len(fetched) == 4
    stored = repository.read_daily("TEST.STOCK", "2024-01-02", "2024-01-05")
    assert [bar.date for bar in stored] == [bar.date for bar in fetched]
    assert all(bar.source == "fixture" for bar in stored)
