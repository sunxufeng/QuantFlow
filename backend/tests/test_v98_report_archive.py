"""V98 报告存档 CRUD 测试。"""


def test_archive_save_and_get(client):
    payload = {"name": "我的综合报告", "type": "consolidate", "content": {"summary": {"夏普": 1.2}, "export_sections": []}}
    r = client.post("/api/reports/archive", json=payload)
    assert r.status_code == 200
    rid = r.json()["id"]
    g = client.get(f"/api/reports/archive/{rid}")
    assert g.status_code == 200
    assert g.json()["name"] == "我的综合报告"
    assert g.json()["content"]["summary"]["夏普"] == 1.2


def test_archive_list(client):
    client.post("/api/reports/archive", json={"name": "r1", "content": {"a": 1}})
    client.post("/api/reports/archive", json={"name": "r2", "content": {"b": 2}})
    lst = client.get("/api/reports/archive")
    assert lst.status_code == 200
    items = lst.json()["items"]
    assert len(items) == 2
    # content 不在列表中
    assert "content" not in items[0]


def test_archive_delete(client):
    rid = client.post("/api/reports/archive", json={"name": "r1", "content": {}}).json()["id"]
    d = client.delete(f"/api/reports/archive/{rid}")
    assert d.status_code == 200
    assert client.get(f"/api/reports/archive/{rid}").status_code == 404


def test_archive_not_found_for_other_user(client):
    # 直接插入一条属于「其他用户」的存档，当前 client 读取应 404（owner 隔离）。
    from app.core.db import db
    db.execute(
        "INSERT INTO report_archive (id,name,type,content,owner_id,created_at) VALUES (?,?,?,?,?,?)",
        ("x-other", "secret", "consolidate", "{}", "other-owner-id", "2024-01-01T00:00:00"),
    )
    assert client.get("/api/reports/archive/x-other").status_code == 404


def test_archive_requires_auth(anon_client):
    assert anon_client.post("/api/reports/archive", json={"name": "x", "content": {}}).status_code == 401
    assert anon_client.get("/api/reports/archive").status_code == 401
