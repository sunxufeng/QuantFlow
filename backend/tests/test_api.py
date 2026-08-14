"""API 测试：节点列表 / 工作流校验 / 运行。"""

import pytest
from fastapi.testclient import TestClient

from app.core.workflow_repository import WORKFLOW_REPOSITORY
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    """V1.7 起主读接口需登录，模块级 client 改为自带合法令牌。"""
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "api_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "api_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def test_health():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_list_nodes():
    resp = client.get("/api/nodes")
    assert resp.status_code == 200
    types = {s["node_type"] for s in resp.json()}
    assert "math.add" in types
    assert "data.demo_table" in types


def test_validate_ok():
    resp = client.post("/api/workflows/validate", json={
        "nodes": [
            {"id": "c", "node_type": "data.constant", "params": {"value": 1}},
            {"id": "a", "node_type": "math.add", "params": {}},
        ],
        "edges": [
            {"source": "c", "source_port": "value", "target": "a", "target_port": "a"},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["valid"] is True


def test_validate_cycle():
    resp = client.post("/api/workflows/validate", json={
        "nodes": [
            {"id": "a", "node_type": "math.add", "params": {}},
            {"id": "b", "node_type": "math.add", "params": {}},
        ],
        "edges": [
            {"source": "a", "source_port": "result", "target": "b", "target_port": "a"},
            {"source": "b", "source_port": "result", "target": "a", "target_port": "a"},
        ],
    })
    assert resp.status_code == 200
    assert resp.json()["valid"] is False
    assert any("环" in e for e in resp.json()["errors"])


def test_run_workflow():
    resp = client.post("/api/workflows/run", json={
        "nodes": [
            {"id": "c", "node_type": "data.constant", "params": {"value": 5}},
            {"id": "a", "node_type": "math.add", "params": {}},
        ],
        "edges": [
            {"source": "c", "source_port": "value", "target": "a", "target_port": "a"},
            {"source": "c", "source_port": "value", "target": "a", "target_port": "b"},
        ],
    })
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "succeeded"
    assert data["nodes"][1]["outputs"]["result"] == 10


def test_run_invalid_workflow_422():
    resp = client.post("/api/workflows/run", json={
        "nodes": [{"id": "a", "node_type": "math.add", "params": {}}],
        "edges": [{"source": "a", "source_port": "nope", "target": "a", "target_port": "a"}],
    })
    assert resp.status_code == 422


def test_workflow_crud_import_export():
    WORKFLOW_REPOSITORY.clear()
    payload = {
        "name": "Demo strategy",
        "description": "M1 persistence test",
        "nodes": [
            {
                "id": "c",
                "node_type": "data.constant",
                "params": {"value": 5},
                "position": {"x": 60, "y": 120},
            },
        ],
        "edges": [],
    }

    created = client.post("/api/workflows", json=payload)
    assert created.status_code == 201
    workflow_id = created.json()["id"]
    assert created.json()["version"] == 1

    listed = client.get("/api/workflows")
    assert listed.status_code == 200
    assert [item["id"] for item in listed.json()] == [workflow_id]

    detail = client.get(f"/api/workflows/{workflow_id}")
    assert detail.json()["nodes"][0]["position"] == {"x": 60.0, "y": 120.0}

    payload["name"] = "Updated strategy"
    updated = client.put(f"/api/workflows/{workflow_id}", json=payload)
    assert updated.status_code == 200
    assert updated.json()["version"] == 2

    exported = client.get(f"/api/workflows/{workflow_id}/export")
    assert exported.status_code == 200
    assert "id" not in exported.json()
    assert exported.json()["name"] == "Updated strategy"

    exported_payload = exported.json()
    exported_payload["name"] = "Imported copy"
    imported = client.post("/api/workflows/import", json=exported_payload)
    assert imported.status_code == 201
    assert imported.json()["id"] != workflow_id

    deleted = client.delete(f"/api/workflows/{workflow_id}")
    assert deleted.status_code == 204
    assert client.get(f"/api/workflows/{workflow_id}").status_code == 404


def test_create_workflow_validates_graph():
    response = client.post("/api/workflows", json={
        "name": "Invalid",
        "nodes": [{"id": "a", "node_type": "missing.node", "params": {}}],
        "edges": [],
    })
    assert response.status_code == 422
