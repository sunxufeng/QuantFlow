"""V5.1 自选股监控 + 价格预警：聚合视图端点。

向 ``app.api.market.market_service`` 注入 fixture 源的独立 MarketService，
隔离其它用例对全局单例 primary 的 monkeypatch 污染；
并手动清理 watchlists / alert_rules（db.reset 不清除这两张表）。
"""

from __future__ import annotations

import pytest

from app.api import market as market_api
from app.core.db import db
from app.market.service import MarketService
from app.market.repository import InMemoryMarketDataRepository


@pytest.fixture
def isolated_market(client, monkeypatch):
    svc = MarketService(repository=InMemoryMarketDataRepository())
    monkeypatch.setattr(market_api, "market_service", svc)
    return svc


def _clean_persistent():
    """watchlists / alert_rules 不被 db.reset 清除，需手动清理避免跨用例污染。"""
    with db._lock:
        db._ensure().execute("DELETE FROM watchlists")
        db._ensure().execute("DELETE FROM alert_rules")
        db._ensure().commit()


def test_watchlist_monitor_requires_auth(anon_client) -> None:
    r = anon_client.get("/api/market/watchlist/monitor")
    assert r.status_code == 401


def test_watchlist_monitor_aggregates_quote_and_alerts(
    client, isolated_market: MarketService
) -> None:
    _clean_persistent()
    r = client.post("/api/market/watchlist?symbol=TEST.STOCK")
    assert r.status_code == 201
    a = client.post(
        "/api/alerts",
        json={"name": "高价预警", "symbol": "TEST.STOCK", "metric": "price", "operator": ">", "threshold": 99999.0},
    )
    assert a.status_code == 201

    r = client.get("/api/market/watchlist/monitor")
    assert r.status_code == 200, r.text
    data = r.json()
    assert data["total"] == 1
    item = data["items"][0]
    assert item["symbol"] == "TEST.STOCK"
    assert item["quote"] and item["quote"]["last"] is not None
    assert item["quote"]["change_pct"] is not None
    assert len(item["alerts"]) == 1
    assert item["alerts"][0]["symbol"] == "TEST.STOCK"


def test_watchlist_monitor_empty_after_remove(client, isolated_market: MarketService) -> None:
    _clean_persistent()
    client.post("/api/market/watchlist?symbol=TEST.STOCK")
    client.delete("/api/market/watchlist/TEST.STOCK")
    r = client.get("/api/market/watchlist/monitor")
    assert r.status_code == 200
    assert r.json()["items"] == []
