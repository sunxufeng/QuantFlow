"""V4.2 多因子组合回测闭环测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(username: str = "mf_u") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    r = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_multifactor_requires_auth():
    resp = client.post(
        "/api/factors/research/multifactor",
        json={"symbol": "TEST.STOCK", "factors": [{"name": "m", "expression": "close", "weight": 1}]},
    )
    assert resp.status_code == 401


def test_multifactor_runs_and_returns_metrics():
    headers = _auth("mf_u1")
    resp = client.post(
        "/api/factors/research/multifactor",
        headers=headers,
        json={
            "symbol": "TEST.STOCK",
            "start": "2024-01-01",
            "end": "2024-04-01",
            "threshold": 0.0,
            "factors": [
                {"name": "动量", "expression": "close/close.shift(1)-1", "weight": 1},
                {"name": "均值回归", "expression": "(close-open)/open", "weight": 1},
            ],
        },
    )
    assert resp.status_code == 200, resp.text
    d = resp.json()
    assert "metrics" in d and "total_return" in d["metrics"]
    assert "composite_series" in d and len(d["composite_series"]) > 0
    # 每个序列点含 综合分 与 仓位
    pt = d["composite_series"][0]
    assert "composite" in pt and "position" in pt
    # 权重已回显
    assert len(d["factors"]) == 2


def test_multifactor_bad_expression_422():
    headers = _auth("mf_u2")
    resp = client.post(
        "/api/factors/research/multifactor",
        headers=headers,
        json={
            "symbol": "TEST.STOCK",
            "start": "2024-01-01",
            "end": "2024-04-01",
            "factors": [{"name": "坏", "expression": "undefined_var * 2", "weight": 1}],
        },
    )
    assert resp.status_code == 422
