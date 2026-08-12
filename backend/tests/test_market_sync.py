"""N4 行情落库与数据自动更新测试：SQLite 仓库 + 同步状态/触发。"""

from fastapi.testclient import TestClient

from app.main import app
from app.market.repository import SQLiteMarketDataRepository

client = TestClient(app)


def _register(username, password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    ).json()["token"]


def _auth_headers(username, password="secret123"):
    token = _register(username, password)
    return {"Authorization": f"Bearer {token}"}


def test_market_bars_persist_to_sqlite():
    repo = SQLiteMarketDataRepository()
    repo.clear()
    headers = _auth_headers("sync_user")
    # 首次请求回源并落库
    resp = client.get(
        "/api/market/bars",
        params={"symbol": "TEST.STOCK", "start": "2024-01-01", "end": "2024-02-01"},
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["count"] > 0
    # 已从 SQLite 仓库可读
    stored = repo.read_daily("TEST.STOCK", "2024-01-01", "2024-02-01")
    assert len(stored) > 0


def test_manual_sync_writes_bars_and_records_status():
    repo = SQLiteMarketDataRepository()
    repo.clear()
    headers = _auth_headers("sync_user2")
    resp = client.post("/api/market/sync", headers=headers)
    assert resp.status_code == 202
    body = resp.json()
    assert body["status"] == "success"
    # fixture 有 3 个标的，每个 20 根日线
    assert body["bars_written"] >= 1

    # 状态接口可读
    status = client.get("/api/market/sync/status", headers=headers).json()
    assert status["status"] in ("success", "failed", "never_run")
    assert status["stored_bars"] >= 1


def test_sync_requires_auth():
    resp = client.post("/api/market/sync")
    assert resp.status_code == 401
