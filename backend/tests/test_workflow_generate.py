"""V3.0 AI 策略工作台：自然语言 → 工作流生成 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(username: str = "wfgen_u") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_generate_requires_auth():
    resp = client.post("/api/workflows/generate", json={"prompt": "均线策略"})
    assert resp.status_code == 401


def test_generate_ma_cross_rule():
    headers = _auth("wfgen_u1")
    resp = client.post(
        "/api/workflows/generate",
        json={"prompt": "写一个均线金叉策略，用 TEST.BANK，10 日窗口", "use_llm": False},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["source"] == "rule"
    assert body["name"] == "均线交叉策略"
    assert len(body["nodes"]) >= 2 and len(body["edges"]) >= 1
    # 生成的一定可导入（通过 DAG 校验已在接口内断言）


def test_generate_futures_rule():
    headers = _auth("wfgen_u2")
    resp = client.post(
        "/api/workflows/generate",
        json={"prompt": "期货多空策略，用 TEST.FUTURE", "use_llm": False},
        headers=headers,
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "期货均线多空策略"
    assert any(n["node_type"] == "data.quotes" and n["params"]["symbol"] == "TEST.FUTURE" for n in body["nodes"])


def test_generate_empty_prompt_422():
    headers = _auth("wfgen_u3")
    resp = client.post("/api/workflows/generate", json={"prompt": "   "}, headers=headers)
    assert resp.status_code == 422
