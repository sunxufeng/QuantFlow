"""V5.0 行情缓存 / 数据源管理：introspection + force-refresh.

这些测试向 ``app.api.market.market_service`` 注入一个独立的 ``MarketService``
（fixture 源 + 内存仓库），以隔离其他用例对全局单例的污染。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import market as market_api
from app.market.service import MarketService
from app.market.sources import TushareDataSource
from app.market.repository import InMemoryMarketDataRepository

FIXTURE_SYMBOLS = ["TEST.STOCK", "TEST.BANK", "TEST.FUND", "TEST.FUTURE"]


@pytest.fixture
def isolated_market(client: TestClient, monkeypatch):
    """注入独立 MarketService（fixture 源 + 内存仓库）。"""
    svc = MarketService(repository=InMemoryMarketDataRepository())
    monkeypatch.setattr(market_api, "market_service", svc)
    return svc


def test_market_cache_requires_auth(anon_client: TestClient) -> None:
    r = anon_client.get("/api/market/cache")
    assert r.status_code == 401


def test_market_cache_snapshot_shape(
    client: TestClient, isolated_market: MarketService
) -> None:
    for sym in FIXTURE_SYMBOLS:
        client.get(
            f"/api/market/bars?symbol={sym}&as_table=false&start=2024-01-01&end=2024-02-01"
        )
    r = client.get("/api/market/cache")
    assert r.status_code == 200, r.text
    data = r.json()
    for k in ("provider_mode", "provider", "cache_backend", "total_bars", "symbols"):
        assert k in data
    assert data["provider"] == "fixture"
    syms = {s["symbol"] for s in data["symbols"]}
    assert set(FIXTURE_SYMBOLS).issubset(syms)
    for s in data["symbols"]:
        assert s["count"] > 0
        assert s["first_date"] and s["last_date"]


def test_market_cache_refresh_forces_reload(
    client: TestClient, isolated_market: MarketService
) -> None:
    payload = {"symbols": ["TEST.STOCK"], "start": "2024-01-01", "end": "2024-02-01"}
    r = client.post("/api/market/cache/refresh", json=payload)
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["provider"] == "fixture"
    refreshed = {x["symbol"]: x["count"] for x in data["refreshed"]}
    assert refreshed.get("TEST.STOCK", 0) > 0
    snap = client.get("/api/market/cache").json()
    assert any(s["symbol"] == "TEST.STOCK" and s["count"] > 0 for s in snap["symbols"])


def test_market_cache_refresh_all(
    client: TestClient, isolated_market: MarketService
) -> None:
    r = client.post(
        "/api/market/cache/refresh",
        json={"start": "2024-01-01", "end": "2024-02-01"},
    )
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total_bars"] > 0
    refreshed_syms = {x["symbol"] for x in data["refreshed"]}
    assert set(FIXTURE_SYMBOLS).issubset(refreshed_syms)


def test_market_cache_refresh_requires_explicit_symbols_for_tushare() -> None:
    """tushare 源不支持 symbols()，不传 symbols 应抛 DataSourceError（422 拦截）。"""
    svc = MarketService(primary=TushareDataSource(token=""), repository=InMemoryMarketDataRepository())
    with pytest.raises(Exception) as exc:
        svc.refresh(symbols=None)
    assert "symbols" in str(exc.value)
