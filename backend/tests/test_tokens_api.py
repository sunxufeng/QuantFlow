"""N2 API Token 端点测试：创建 / 鉴权 / 列表 / 吊销。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(username, password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    ).json()["token"]


def _auth_headers(username, password="secret123"):
    token = _register(username, password)
    return {"Authorization": f"Bearer {token}"}


def _login(username, password="secret123"):
    return client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )


def test_create_token_returns_one_time_secret():
    headers = _auth_headers("tok_user")
    resp = client.post("/api/tokens", json={"name": "ci-runner"}, headers=headers)
    assert resp.status_code == 201
    body = resp.json()
    assert body["token"].startswith("qf.")
    assert "." in body["token"]
    assert body["prefix"]
    assert body["revoked"] is False


def test_token_authenticates_requests():
    headers = _auth_headers("tok_user2")
    token = client.post("/api/tokens", json={"name": "runner"}, headers=headers).json()[
        "token"
    ]
    resp = client.get(
        "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
    )
    assert resp.status_code == 200
    assert resp.json()["username"] == "tok_user2"


def test_jwt_still_works_alongside_token():
    _auth_headers("tok_user3")
    jwt = client.post("/api/auth/login", json={"username": "tok_user3", "password": "secret123"}).json()["token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {jwt}"})
    assert resp.status_code == 200


def test_list_and_revoke_token():
    headers = _auth_headers("tok_user4")
    created = client.post("/api/tokens", json={"name": "tmp"}, headers=headers).json()
    prefix = created["prefix"]

    listing = client.get("/api/tokens", headers=headers).json()
    assert any(t["prefix"] == prefix for t in listing)

    # 吊销
    resp = client.delete(f"/api/tokens/{prefix}", headers=headers)
    assert resp.status_code == 204

    # 吊销后无法鉴权
    bad = client.get(
        "/api/auth/me",
        headers={"Authorization": f"Bearer {created['token']}"},
    )
    assert bad.status_code == 401

    # 重复吊销返回 404
    again = client.delete(f"/api/tokens/{prefix}", headers=headers)
    assert again.status_code == 404


def test_token_requires_auth():
    resp = client.post("/api/tokens", json={"name": "x"})
    assert resp.status_code == 401
