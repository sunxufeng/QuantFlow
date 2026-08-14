"""V3.1 个人工作流模板库 API 测试。"""

from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

_VALID_NODES = [
    {"id": "n1", "node_type": "data.quotes", "params": {"symbol": "TEST.STOCK"}},
    {"id": "n2", "node_type": "backtest.run", "params": {"strategy": "buy_hold"}},
]
_VALID_EDGES = [
    {"id": "e1", "source": "n1", "source_port": "table", "target": "n2", "target_port": "table"},
]


def _auth(username: str = "tpl_u") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    token = client.post(
        "/api/auth/login", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_save_template_requires_auth():
    resp = client.post(
        "/api/workflows/templates",
        json={"name": "x", "nodes": _VALID_NODES, "edges": _VALID_EDGES},
    )
    assert resp.status_code == 401


def test_save_and_list_template():
    headers = _auth("tpl_u1")
    resp = client.post(
        "/api/workflows/templates",
        headers=headers,
        json={
            "name": "动量模板",
            "description": "测试",
            "nodes": _VALID_NODES,
            "edges": _VALID_EDGES,
            "tags": ["动量", "测试"],
        },
    )
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "动量模板"
    assert body["builtin"] is False
    assert body["id"].startswith("tpl_")

    lst = client.get("/api/workflows/templates/mine", headers=headers).json()
    assert any(t["id"] == body["id"] for t in lst)
    assert any("动量" in (t.get("tags") or []) for t in lst)


def test_save_invalid_graph_422():
    headers = _auth("tpl_u2")
    resp = client.post(
        "/api/workflows/templates",
        headers=headers,
        json={
            "name": "坏图",
            "nodes": [{"id": "n1", "node_type": "no.such.node", "params": {}}],
            "edges": [],
        },
    )
    assert resp.status_code == 422


def test_delete_template_and_protection():
    headers = _auth("tpl_u3")
    created = client.post(
        "/api/workflows/templates",
        headers=headers,
        json={"name": "待删", "nodes": _VALID_NODES, "edges": _VALID_EDGES},
    ).json()
    tid = created["id"]

    # 删除
    assert client.delete(f"/api/workflows/templates/{tid}", headers=headers).status_code == 204
    # 删后不存在
    assert client.get(f"/api/workflows/templates/{tid}", headers=headers).status_code == 404
    lst = client.get("/api/workflows/templates/mine", headers=headers).json()
    assert all(t["id"] != tid for t in lst)


def test_delete_other_user_template_forbidden():
    a = _auth("tpl_owner")
    b = _auth("tpl_other")
    tid = client.post(
        "/api/workflows/templates",
        headers=a,
        json={"name": "别人的", "nodes": _VALID_NODES, "edges": _VALID_EDGES},
    ).json()["id"]
    # B 删除 A 的模板应 403
    assert client.delete(f"/api/workflows/templates/{tid}", headers=b).status_code == 403
