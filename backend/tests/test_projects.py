"""M4-2 项目与成员管理测试：项目 CRUD / 成员权限 / 工作流项目作用域。"""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _register(username, password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    ).json()


def _auth_header(token):
    return {"Authorization": f"Bearer {token}"}


def _create_project(token, name="默认项目"):
    return client.post(
        "/api/projects", json={"name": name, "description": ""}, headers=_auth_header(token)
    )


def _mk_workflow(project_id=None):
    return {
        "name": "wf",
        "nodes": [
            {"id": "c", "node_type": "data.constant", "params": {"value": 1}},
            {"id": "a", "node_type": "math.add", "params": {}},
        ],
        "edges": [
            {"source": "c", "source_port": "value", "target": "a", "target_port": "a"},
        ],
        **({"project_id": project_id} if project_id else {}),
    }


def test_create_project():
    user = _register("alice")
    resp = _create_project(user["token"])
    assert resp.status_code == 201
    body = resp.json()
    assert body["name"] == "默认项目"
    assert body["owner_id"] == user["user"]["id"]
    assert body["member_count"] == 1


def test_list_my_projects():
    alice = _register("alice")  # admin（首个注册用户）
    bob = _register("bob")
    _create_project(alice["token"], "A 项目")
    _create_project(alice["token"], "B 项目")
    _create_project(bob["token"], "Bob 项目")

    # admin 可见全部项目
    alice_list = client.get("/api/projects", headers=_auth_header(alice["token"])).json()
    assert {p["name"] for p in alice_list} == {"A 项目", "B 项目", "Bob 项目"}
    # 普通用户仅可见自己参与的项目
    bob_list = client.get("/api/projects", headers=_auth_header(bob["token"])).json()
    assert {p["name"] for p in bob_list} == {"Bob 项目"}


def test_list_projects_requires_auth():
    resp = client.get("/api/projects")
    assert resp.status_code == 401


def test_project_detail_forbidden_for_non_member():
    alice = _register("alice")
    bob = _register("bob")
    pid = _create_project(alice["token"]).json()["id"]
    resp = client.get(f"/api/projects/{pid}", headers=_auth_header(bob["token"]))
    assert resp.status_code == 403


def test_add_member_and_role_check():
    alice = _register("alice")
    bob = _register("bob")
    pid = _create_project(alice["token"]).json()["id"]

    resp = client.post(
        f"/api/projects/{pid}/members",
        json={"username": "bob", "role": "viewer"},
        headers=_auth_header(alice["token"]),
    )
    assert resp.status_code == 201

    members = client.get(
        f"/api/projects/{pid}/members", headers=_auth_header(alice["token"])
    ).json()
    assert {m["username"]: m["role"] for m in members} == {
        "alice": "owner",
        "bob": "viewer",
    }

    # viewer 不能改项目
    resp = client.put(
        f"/api/projects/{pid}",
        json={"name": "hacked", "description": ""},
        headers=_auth_header(bob["token"]),
    )
    assert resp.status_code == 403


def test_non_member_cannot_add_member():
    alice = _register("alice")
    bob = _register("bob")
    pid = _create_project(alice["token"]).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/members",
        json={"username": "bob", "role": "member"},
        headers=_auth_header(bob["token"]),
    )
    assert resp.status_code == 403


def test_add_unknown_user_404():
    alice = _register("alice")
    pid = _create_project(alice["token"]).json()["id"]
    resp = client.post(
        f"/api/projects/{pid}/members",
        json={"username": "nobody", "role": "member"},
        headers=_auth_header(alice["token"]),
    )
    assert resp.status_code == 404


def test_cannot_remove_owner():
    alice = _register("alice")
    pid = _create_project(alice["token"]).json()["id"]
    resp = client.delete(
        f"/api/projects/{pid}/members/{alice['user']['id']}",
        headers=_auth_header(alice["token"]),
    )
    assert resp.status_code == 400


def test_owner_can_delete_project():
    alice = _register("alice")
    pid = _create_project(alice["token"]).json()["id"]
    resp = client.delete(f"/api/projects/{pid}", headers=_auth_header(alice["token"]))
    assert resp.status_code == 204
    assert client.get(f"/api/projects/{pid}", headers=_auth_header(alice["token"])).status_code == 404


def test_workflow_scoped_to_project():
    alice = _register("alice")
    bob = _register("bob")
    pid = _create_project(alice["token"]).json()["id"]

    # 认证用户创建带 project_id 的工作流
    resp = client.post(
        "/api/workflows", json=_mk_workflow(pid), headers=_auth_header(alice["token"])
    )
    assert resp.status_code == 201
    wf = resp.json()
    assert wf["project_id"] == pid
    assert wf["owner_id"] == alice["user"]["id"]

    # 按项目过滤列表
    items = client.get(
        f"/api/workflows?project_id={pid}", headers=_auth_header(alice["token"])
    ).json()
    assert len(items) == 1

    # bob（非成员）不能创建到该项目
    resp = client.post(
        "/api/workflows", json=_mk_workflow(pid), headers=_auth_header(bob["token"])
    )
    assert resp.status_code == 403

    # bob 列表看不到 alice 的工作流
    bob_items = client.get(
        "/api/workflows", headers=_auth_header(bob["token"])
    ).json()
    assert len(bob_items) == 0


def test_workflow_requires_auth():
    """V1.7 起工作流接口需登录；未认证返回 401，登录后可正常创建。"""
    resp = client.post("/api/workflows", json=_mk_workflow())
    assert resp.status_code == 401
    user = _register("carol")
    authed = client.post(
        "/api/workflows", json=_mk_workflow(), headers=_auth_header(user["token"])
    )
    assert authed.status_code == 201
    wf = authed.json()
    assert wf["project_id"] is None
