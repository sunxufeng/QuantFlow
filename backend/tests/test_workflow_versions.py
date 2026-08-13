"""V1.5 工作流版本管理：快照 / 列表 / 恢复（repository + API）。"""

import time

import pytest
from fastapi.testclient import TestClient

from app.core.workflow_repository import (
    InMemoryWorkflowRepository,
    VersionNotFoundError,
    WorkflowNotFoundError,
)
from app.main import app

client = TestClient(app)


@pytest.fixture
def auth_headers():
    username = f"ver_user_{time.time_ns()}"
    token = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def _make_workflow(headers, node_id, value):
    return client.post(
        "/api/workflows",
        json={
            "name": "版本测试",
            "nodes": [{"id": node_id, "node_type": "data.constant", "params": {"value": value}}],
            "edges": [],
        },
        headers=headers,
    ).json()


# ---- repository 层 ----
def test_repository_snapshot_list_restore():
    repo = InMemoryWorkflowRepository()
    wf = repo.create({"name": "wf", "nodes": [{"id": "a"}], "edges": []})
    snap = repo.snapshot(wf["id"], label="初版")
    assert snap["version"] == 1
    assert snap["label"] == "初版"
    assert snap["node_count"] if "node_count" in snap else True  # 旧结构兼容

    # 修改工作流
    repo.update(wf["id"], {"name": "wf2", "nodes": [{"id": "b"}], "edges": []})
    versions = repo.list_versions(wf["id"])
    assert len(versions) == 1
    assert versions[0]["version"] == 1
    assert versions[0]["name"] == "wf"
    assert "node_count" in versions[0]
    assert versions[0]["node_count"] == 1

    # 恢复
    restored = repo.restore(wf["id"], 1)
    assert restored["name"] == "wf"
    assert restored["nodes"] == [{"id": "a"}]
    assert restored["version"] == 3  # create=1, update=2, restore=3


def test_repository_restore_missing_version():
    repo = InMemoryWorkflowRepository()
    wf = repo.create({"name": "wf", "nodes": [], "edges": []})
    with pytest.raises(VersionNotFoundError):
        repo.restore(wf["id"], 99)


def test_repository_delete_clears_snapshots():
    repo = InMemoryWorkflowRepository()
    wf = repo.create({"name": "wf", "nodes": [], "edges": []})
    repo.snapshot(wf["id"], label="v1")
    assert len(repo.list_versions(wf["id"])) == 1
    repo.delete(wf["id"])
    with pytest.raises(WorkflowNotFoundError):
        repo.list_versions(wf["id"])


# ---- API 层 ----
def test_workflow_version_lifecycle(auth_headers):
    wf = _make_workflow(auth_headers, "n1", 1)

    # 创建快照
    snap = client.post(
        f"/api/workflows/{wf['id']}/versions", json={"label": "初始"}, headers=auth_headers
    )
    assert snap.status_code == 201
    assert snap.json()["version"] == 1

    # 修改并保存
    upd = client.put(
        f"/api/workflows/{wf['id']}",
        json={"name": "版本测试改", "nodes": [{"id": "n2", "node_type": "data.constant", "params": {"value": 2}}], "edges": []},
        headers=auth_headers,
    )
    assert upd.status_code == 200

    # 列出版本
    listing = client.get(f"/api/workflows/{wf['id']}/versions", headers=auth_headers)
    assert listing.status_code == 200
    versions = listing.json()
    assert len(versions) == 1
    assert versions[0]["version"] == 1

    # 恢复到初始版本
    restore = client.post(f"/api/workflows/{wf['id']}/versions/1/restore", headers=auth_headers)
    assert restore.status_code == 200
    restored_nodes = restore.json()["nodes"]
    assert len(restored_nodes) == 1
    assert restored_nodes[0]["id"] == "n1"
    assert restored_nodes[0]["params"] == {"value": 1}


def test_restore_missing_version_404(auth_headers):
    wf = _make_workflow(auth_headers, "n1", 1)
    resp = client.post(f"/api/workflows/{wf['id']}/versions/99/restore", headers=auth_headers)
    assert resp.status_code == 404
