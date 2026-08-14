"""运行实例 API 测试：异步提交 / 查询 / WebSocket 推送。"""

from __future__ import annotations

import time

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    """V1.7 起运行接口需登录，模块级 client 改为自带合法令牌。"""
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "run_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "run_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def _submit(payload: dict) -> dict:
    resp = client.post("/api/runs", json=payload)
    assert resp.status_code == 200, resp.text
    return resp.json()


def _wait_succeeded(run_id: str, timeout: float = 5.0) -> dict:
    deadline = time.time() + timeout
    while time.time() < deadline:
        record = client.get(f"/api/runs/{run_id}").json()
        if record["status"] != "running":
            return record
        time.sleep(0.02)
    raise AssertionError("run did not finish in time")


def test_submit_run_async():
    data = _submit({
        "nodes": [{"id": "c", "node_type": "data.constant", "params": {"value": 7}}],
        "edges": [],
        "workflow_name": "异步测试",
    })
    assert data["status"] == "running"
    assert data["run_id"]

    record = _wait_succeeded(data["run_id"])
    assert record["status"] == "succeeded"
    assert record["workflow_name"] == "异步测试"
    assert record["nodes"]["c"]["status"] == "succeeded"
    assert record["nodes"]["c"]["outputs"]["value"] == 7


def test_submit_invalid_workflow_422():
    resp = client.post("/api/runs", json={"nodes": [{"id": "a", "node_type": "missing.type"}]})
    assert resp.status_code == 422


def test_list_runs():
    _submit({
        "nodes": [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}],
        "edges": [],
    })
    resp = client.get("/api/runs")
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert isinstance(items, list)
    assert len(items) >= 1
    assert {"run_id", "status", "workflow_name"} <= set(items[0].keys())


def test_get_missing_run_404():
    assert client.get("/api/runs/does_not_exist").status_code == 404


def test_ws_receives_snapshot():
    data = _submit({
        "nodes": [{"id": "c", "node_type": "data.constant", "params": {"value": 3}}],
        "edges": [],
    })
    run_id = data["run_id"]
    token = client.headers["Authorization"].split(" ", 1)[1]
    with client.websocket_connect(f"/api/ws/runs/{run_id}?token={token}") as ws:
        msg = ws.receive_json()
        assert msg["kind"] == "snapshot"
        assert msg["run_id"] == run_id
        # payload 里至少能读到当前状态字段
        assert "status" in msg["payload"]
