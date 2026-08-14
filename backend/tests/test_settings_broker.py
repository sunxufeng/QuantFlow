"""V1.7 券商凭证配置 API 测试。"""

from app.main import app
from fastapi.testclient import TestClient


def _authed():
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "broker_r", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "broker_r", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def test_broker_get_requires_auth(anon_client):
    assert anon_client.get("/api/settings/broker").status_code == 401


def test_broker_get_default_masked():
    c = _authed()
    resp = c.get("/api/settings/broker")
    assert resp.status_code == 200
    body = resp.json()
    assert body["broker"] == "none"
    assert body["configured"] is False
    # 无 key 时脱敏为空串
    assert body["api_key"] == ""


def test_broker_put_save_and_mask():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "broker_w", "password": "secret123"})
        token = c.post(
            "/api/auth/login", json={"username": "broker_w", "password": "secret123"}
        ).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        resp = c.put(
            "/api/settings/broker",
            json={
                "broker": "universal",
                "api_key": "ak_live_1234567890",
                "api_secret": "secret_abcdef",
                "base_url": "https://api.broker.example/v1",
                "account_id": "acc_99887766",
            },
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["broker"] == "universal"
        assert body["configured"] is True
        # 敏感字段脱敏
        assert body["api_key"] == "****7890"
        assert body["api_secret"] == "****cdef"
        assert body["account_id"] == "****7766"
        # 再次读取，确认持久化且脱敏
        again = c.get("/api/settings/broker").json()
        assert again["api_key"] == "****7890"
        assert again["configured"] is True


def test_broker_put_rejects_bad_type():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "broker_b", "password": "secret123"})
        token = c.post(
            "/api/auth/login", json={"username": "broker_b", "password": "secret123"}
        ).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        resp = c.put("/api/settings/broker", json={"broker": "nope"})
        assert resp.status_code == 400


def test_broker_test_none_configured():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "broker_t", "password": "secret123"})
        token = c.post(
            "/api/auth/login", json={"username": "broker_t", "password": "secret123"}
        ).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        resp = c.post("/api/settings/broker/test", json={"broker": "none"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["configured"] is False
        assert body["ok"] is False


def test_broker_test_simulated_ok():
    with TestClient(app) as c:
        c.post("/api/auth/register", json={"username": "broker_s", "password": "secret123"})
        token = c.post(
            "/api/auth/login", json={"username": "broker_s", "password": "secret123"}
        ).json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        resp = c.post(
            "/api/settings/broker/test",
            json={"broker": "simulated", "api_key": "ak_whatever"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["ok"] is True
        assert body["broker"] == "simulated"
