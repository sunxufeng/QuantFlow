"""M5-3 安全测试：JWT 篡改/伪造、SQL 注入、越权隔离。

覆盖 test_auth / test_projects 未覆盖的攻击面：
- JWT payload 篡改（改 role/username）→ 401
- 错误密钥伪造签名 → 401
- SQL 注入（登录/项目名）→ 非 200/500
- 非成员工作流列表隔离 + 读取 403
- viewer 越权删除项目 → 403
"""

import time

import jwt
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(username: str, password: str = "secret123"):
    return client.post("/api/auth/register", json={"username": username, "password": password})


def _login(username: str, password: str = "secret123") -> str:
    resp = client.post("/api/auth/login", json={"username": username, "password": password})
    assert resp.status_code == 200
    return resp.json()["token"]


def _sign(payload: dict, secret: str) -> str:
    return jwt.encode(payload, secret, algorithm="HS256")


def test_jwt_tampered_payload_rejected():
    """篡改 payload（改 role/username）后签名不匹配 → 401。"""
    token = _login("tamper_a", "secret123") if _register("tamper_a").status_code == 201 else _login("tamper_a")
    # 解码并修改 role
    header, payload_raw, _ = token.split(".")
    import base64
    payload = json_loads_b64(payload_raw)
    payload["role"] = "admin"
    new_payload = base64.urlsafe_b64encode(
        __import__("json").dumps(payload, separators=(",", ":")).encode()
    ).rstrip(b"=").decode()
    tampered = f"{header}.{new_payload}."
    # 直接以「无签名/错签名」形态提交
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {tampered}xxx"})
    assert resp.status_code == 401


def json_loads_b64(s: str):
    import base64
    import json
    return json.loads(base64.urlsafe_b64decode(s + "=" * (-len(s) % 4)))


def test_jwt_forged_with_wrong_secret_rejected():
    """用攻击者密钥伪造 token → 401。"""
    _register("forge_a")
    token = _sign(
        {"uid": "fake", "username": "forge_a", "role": "admin", "exp": int(time.time()) + 3600},
        secret="attacker-secret-8f3b2a1c9d4e5f6a00000000",
    )
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert resp.status_code == 401


def test_jwt_no_signature_rejected():
    """三段式但签名段为空 → 401。"""
    _register("nosig_a")
    token = _sign(
        {"uid": "x", "username": "nosig_a", "role": "user", "exp": int(time.time()) + 3600},
        secret="whatever-secret-key-000000000000000000000000",
    )
    no_sig = token.rsplit(".", 1)[0] + "."
    resp = client.get("/api/auth/me", headers={"Authorization": f"Bearer {no_sig}"})
    assert resp.status_code == 401


def test_sql_injection_on_login():
    """SQL 注入登录不返回 200（参数化查询生效）。"""
    for payload in [
        {"username": "admin' OR '1'='1", "password": "x" * 8},
        {"username": "' OR 1=1 --", "password": "x" * 8},
        {"username": 'admin" OR "1"="1', "password": "x" * 8},
    ]:
        resp = client.post("/api/auth/login", json=payload)
        assert resp.status_code in (401, 422, 400), resp.status_code


def test_sql_injection_on_project_name():
    """项目名 SQL 注入不触发 500（参数化 INSERT 生效）。"""
    _register("sqli_a")
    token = _login("sqli_a")
    resp = client.post(
        "/api/projects",
        json={"name": "x' OR '1'='1' --", "description": "inject"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code in (200, 201, 422)


def test_non_member_workflow_list_isolation():
    """非成员列表项目工作流为空，不泄露内容。"""
    _register("iso_a")
    _register("iso_b")
    _register("iso_c")
    ta, tc = _login("iso_a"), _login("iso_c")
    proj = client.post(
        "/api/projects", json={"name": "iso_proj"}, headers={"Authorization": f"Bearer {ta}"}
    ).json()
    pid = proj["id"]
    wf = client.post(
        "/api/workflows",
        json={
            "name": "iso_wf",
            "project_id": pid,
            "nodes": [{"id": "n1", "node_type": "math.add", "params": {"a": 1, "b": 2}}],
            "edges": [],
        },
        headers={"Authorization": f"Bearer {ta}"},
    ).json()
    # C 非成员：列表隔离
    resp = client.get(
        f"/api/workflows?project_id={pid}", headers={"Authorization": f"Bearer {tc}"}
    )
    assert resp.status_code in (200, 403)
    if resp.status_code == 200:
        assert all(w["id"] != wf["id"] for w in resp.json())
    # C 非成员：直接读 403
    resp = client.get(f"/api/workflows/{wf['id']}", headers={"Authorization": f"Bearer {tc}"})
    assert resp.status_code == 403


def test_viewer_cannot_delete_project():
    """viewer 越权删除项目 → 403。"""
    _register("del_a")
    _register("del_b")
    ta, tb = _login("del_a"), _login("del_b")
    pid = client.post(
        "/api/projects", json={"name": "del_proj"}, headers={"Authorization": f"Bearer {ta}"}
    ).json()["id"]
    client.post(
        f"/api/projects/{pid}/members",
        json={"username": "del_b", "role": "viewer"},
        headers={"Authorization": f"Bearer {ta}"},
    )
    resp = client.delete(f"/api/projects/{pid}", headers={"Authorization": f"Bearer {tb}"})
    assert resp.status_code == 403
