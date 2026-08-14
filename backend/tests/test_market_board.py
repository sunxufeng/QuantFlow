"""V2.4 自选股 / 行情看板测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "board_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "board_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def test_watchlist_crud_and_quotes():
    # 添加
    r = client.post("/api/market/watchlist?symbol=TEST.STOCK")
    assert r.status_code == 201, r.text
    # 重复添加不报错
    client.post("/api/market/watchlist?symbol=TEST.STOCK")

    lst = client.get("/api/market/watchlist").json()
    assert "TEST.STOCK" in lst["items"]

    # 行情快照
    q = client.get("/api/market/quotes?symbols=TEST.STOCK,TEST.BANK").json()
    assert len(q["items"]) == 2
    stock = next(x for x in q["items"] if x["symbol"] == "TEST.STOCK")
    assert stock["last"] is not None
    assert stock["change_pct"] is not None

    # 无行情标的
    bad = client.get("/api/market/quotes?symbols=NODATA.XXX").json()
    assert bad["items"][0].get("error")

    # 移除
    assert client.delete("/api/market/watchlist/TEST.STOCK").status_code == 204
    assert client.delete("/api/market/watchlist/TEST.STOCK").status_code == 204
    assert "TEST.STOCK" not in client.get("/api/market/watchlist").json()["items"]
