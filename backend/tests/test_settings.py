"""V6.1 系统设置 + 用户偏好。

验证：
- GET /api/settings 需登录；返回 system（版本/数据源/缓存/券商）+ preferences 默认值；
- PUT /api/settings 可更新并持久化用户偏好（部分合并）；
- 非法字段值返回 400。
"""

from __future__ import annotations


def test_settings_requires_auth(anon_client):
    assert anon_client.get("/api/settings").status_code == 401
    assert anon_client.put("/api/settings", json={"theme": "dark"}).status_code == 401


def test_settings_shape(client):
    r = client.get("/api/settings")
    assert r.status_code == 200
    data = r.json()
    assert "system" in data and "preferences" in data
    assert data["system"]["version"]
    assert data["system"]["market"]["provider_mode"] in ("fixture", "tushare", None)
    prefs = data["preferences"]
    assert prefs["default_view"] == "home"
    assert prefs["theme"] == "light"
    assert prefs["preferred_data_source"] == "fixture"


def test_settings_put_persists_and_merges(client):
    r = client.put("/api/settings", json={"default_view": "trade", "theme": "dark"})
    assert r.status_code == 200
    saved = r.json()["preferences"]
    assert saved["default_view"] == "trade"
    assert saved["theme"] == "dark"
    # 未提供的字段保留默认
    assert saved["preferred_data_source"] == "fixture"

    # 再次读取仍持久化
    got = client.get("/api/settings").json()["preferences"]
    assert got["default_view"] == "trade"
    assert got["theme"] == "dark"


def test_settings_put_invalid_view(client):
    r = client.put("/api/settings", json={"default_view": "not_a_view"})
    assert r.status_code == 400


def test_settings_put_invalid_theme(client):
    r = client.put("/api/settings", json={"theme": "neon"})
    assert r.status_code == 400
