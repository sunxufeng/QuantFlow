"""M4-4 监控测试：健康检查增强 / 系统概览 / Prometheus 指标权限。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(username, password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    ).json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_health_includes_run_stats():
    resp = client.get("/api/health")
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "ok"
    assert "uptime_seconds" in body
    assert "runs" in body
    assert body["runs"]["total"] >= 0


def test_overview_requires_auth():
    resp = client.get("/api/monitoring/overview")
    assert resp.status_code == 401


def test_overview_fields_for_admin():
    admin = _register("admin")
    resp = client.get("/api/monitoring/overview", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["server"]["uptime_seconds"] >= 0
    assert "nodes" in body and body["nodes"]["registered"] >= 1
    assert "ws_connections" in body
    assert "users" in body and body["users"]["total"] >= 1
    assert "projects" in body


def test_overview_hides_aggregates_for_regular_user():
    _register("admin")
    bob = _register("bob")
    resp = client.get("/api/monitoring/overview", headers=_auth(bob["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert "users" not in body
    assert "projects" not in body
    assert body["requested_by"] == "bob"


def test_metrics_requires_admin():
    _register("admin")
    bob = _register("bob")
    assert (
        client.get("/api/monitoring/metrics", headers=_auth(bob["token"])).status_code
        == 403
    )
    resp = client.get("/api/monitoring/metrics", headers=_auth(bob["token"]))
    assert resp.status_code == 403


def test_metrics_prometheus_format():
    admin = _register("admin")
    resp = client.get("/api/monitoring/metrics", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    assert resp.headers["content-type"].startswith("text/plain")
    text = resp.text
    assert "quantflow_uptime_seconds" in text
    assert "quantflow_runs_total" in text
    assert "quantflow_nodes_registered" in text
