"""M4-3 结构化日志测试：权限 / 过滤 / 请求上下文。"""

import logging

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(username, password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    ).json()


def _auth(token):
    return {"Authorization": f"Bearer {token}"}


def test_logs_require_auth():
    resp = client.get("/api/logs")
    assert resp.status_code == 401


def test_admin_sees_all_logs():
    admin = _register("admin")
    _register("bob")
    logging.getLogger("quantflow").info("hello admin world", extra={"user_id": "u_x"})
    resp = client.get("/api/logs", headers=_auth(admin["token"]))
    assert resp.status_code == 200
    body = resp.json()
    assert body["total"] >= 1
    assert any("hello admin world" in item["message"] for item in body["items"])


def test_regular_user_hides_others_request_logs():
    admin = _register("admin")
    bob = _register("bob")
    carol = _register("carol")
    # 模拟一次 carol 的请求日志（其 user_id 已写入）
    logging.getLogger("quantflow").info(
        "carol secret op", extra={"user_id": carol["user"]["id"]}
    )
    logging.getLogger("quantflow").info("system boot message")

    bob_resp = client.get("/api/logs", headers=_auth(bob["token"])).json()
    messages = [item["message"] for item in bob_resp["items"]]
    assert "carol secret op" not in messages
    assert "system boot message" in messages
    assert all(item.get("user_id") in (None, bob["user"]["id"]) for item in bob_resp["items"])


def test_level_filter():
    admin = _register("admin")
    logging.getLogger("quantflow").info("info msg")
    logging.getLogger("quantflow").error("error msg")
    resp = client.get(
        "/api/logs?level=error", headers=_auth(admin["token"])
    ).json()
    levels = {item["level"] for item in resp["items"]}
    assert levels == {"ERROR"}


def test_keyword_filter():
    admin = _register("admin")
    logging.getLogger("quantflow").info("create_workflow done")
    logging.getLogger("quantflow").info("delete_workflow done")
    resp = client.get(
        "/api/logs?keyword=create_workflow", headers=_auth(admin["token"])
    ).json()
    messages = [item["message"] for item in resp["items"]]
    assert "create_workflow done" in messages
    assert "delete_workflow done" not in messages


def test_request_log_carries_context():
    """每个 HTTP 请求自动产生一条带 request_id 的请求日志。"""
    admin = _register("admin")
    client.get("/api/auth/me", headers=_auth(admin["token"]))
    client.get("/api/health")
    resp = client.get("/api/logs", headers=_auth(admin["token"])).json()
    req_logs = [
        item
        for item in resp["items"]
        if item["logger"] == "quantflow.request" and item.get("path") == "/api/auth/me"
    ]
    assert len(req_logs) == 1
    assert req_logs[0]["request_id"]
    assert req_logs[0]["user_id"] == admin["user"]["id"]
    assert req_logs[0]["status"] == 200
    assert "duration_ms" in req_logs[0]
