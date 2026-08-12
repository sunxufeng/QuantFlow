"""M4-1 用户体系测试：注册 / 登录 / JWT / 角色 / 越权。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(username="alice", password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    )


def test_register_first_user_is_admin():
    resp = _register()
    assert resp.status_code == 201
    body = resp.json()
    assert body["user"]["username"] == "alice"
    assert body["user"]["role"] == "admin"
    assert body["token"]


def test_register_second_user_is_user_role():
    _register()
    resp = _register("bob", "secret123")
    assert resp.status_code == 201
    assert resp.json()["user"]["role"] == "user"


def test_register_duplicate_username_409():
    _register()
    resp = _register()
    assert resp.status_code == 409


def test_register_invalid_username_rejected():
    resp = _register("bad name", "secret123")
    assert resp.status_code == 422
    resp2 = _register("ab", "secret123")  # 太短
    assert resp2.status_code == 422


def test_register_short_password_rejected():
    resp = _register("carol", "123")
    assert resp.status_code == 422


def test_login_ok_returns_token():
    _register()
    resp = client.post(
        "/api/auth/login", json={"username": "alice", "password": "secret123"}
    )
    assert resp.status_code == 200
    assert resp.json()["user"]["username"] == "alice"
    assert resp.json()["token_type"] == "bearer"


def test_login_wrong_password_401():
    _register()
    resp = client.post(
        "/api/auth/login", json={"username": "alice", "password": "wrongpass"}
    )
    assert resp.status_code == 401


def test_login_unknown_user_401():
    resp = client.post(
        "/api/auth/login", json={"username": "nobody", "password": "secret123"}
    )
    assert resp.status_code == 401


def test_me_with_valid_token():
    token = _register().json()["token"]
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 200
    assert resp.json()["username"] == "alice"


def test_me_without_token_401():
    resp = client.get("/api/auth/me")
    assert resp.status_code == 401


def test_me_with_invalid_token_401():
    resp = client.get("/api/auth/me", headers={"Authorization": "Bearer bogus"})
    assert resp.status_code == 401


def test_me_with_expired_token_401():
    from datetime import datetime, timedelta, timezone

    import jwt

    from app.config import settings

    expired = jwt.encode(
        {
            "uid": "u_x",
            "username": "alice",
            "role": "admin",
            "exp": datetime.now(timezone.utc) - timedelta(minutes=1),
        },
        settings.SECRET_KEY,
        algorithm="HS256",
    )
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


def test_password_hash_is_salted():
    """同一密码两次哈希得到不同摘要（随机盐）。"""
    from app.core.security import hash_password, verify_password

    h1, s1 = hash_password("secret123")
    h2, s2 = hash_password("secret123")
    assert h1 != h2
    assert s1 != s2
    assert verify_password("secret123", h1, s1) is True
    assert verify_password("wrong", h1, s1) is False
