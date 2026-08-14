"""V3.4 批量生成并对比回测 API 测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(username: str = "batch_u") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    r = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_batch_requires_auth():
    resp = client.post("/api/workflows/batch-generate-compare", json={"prompts": ["动量"]})
    assert resp.status_code == 401


def test_batch_empty_prompts_422():
    headers = _auth("batch_u1")
    resp = client.post(
        "/api/workflows/batch-generate-compare", json={"prompts": []}, headers=headers
    )
    assert resp.status_code == 422


def test_batch_generates_runs_and_compares():
    headers = _auth("batch_u2")
    resp = client.post(
        "/api/workflows/batch-generate-compare",
        headers=headers,
        json={"prompts": ["动量因子策略，用 TEST.STOCK", "均线金叉策略，用 TEST.BANK"], "use_llm": False},
    )
    assert resp.status_code == 200
    d = resp.json()
    items = d["items"]
    assert len(items) == 2
    for it in items:
        assert it["ok"] is True, it.get("error")
        assert "total_return" in it["metrics"]
        assert isinstance(it["curve_pct"], list) and len(it["curve_pct"]) > 0
        # 曲线首点应为 0.0（归一化）
        assert it["curve_pct"][0]["pct"] == 0.0


def test_batch_caps_at_five():
    headers = _auth("batch_u3")
    prompts = [f"策略{i}，用 TEST.STOCK" for i in range(8)]
    resp = client.post(
        "/api/workflows/batch-generate-compare",
        headers=headers,
        json={"prompts": prompts, "use_llm": False},
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 5
