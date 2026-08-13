"""N3 因子库 CRUD + 分析 API 测试（V1.1 N3）。"""

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.factors import library as factor_library

client = TestClient(app)


@pytest.fixture
def auth_headers():
    import time

    username = f"fac_user_{time.time_ns()}"
    token = client.post(
        "/api/auth/register", json={"username": username, "password": "secret123"}
    ).json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_create_and_list_factor(auth_headers):
    body = {
        "name": "测试动量",
        "expression": "close.pct_change(10)",
        "category": "动量",
        "description": "10日动量",
        "params": {"period": 10},
    }
    resp = client.post("/api/factors/library", json=body, headers=auth_headers)
    assert resp.status_code == 201
    fac = resp.json()
    assert fac["name"] == "测试动量"
    assert fac["expression"] == "close.pct_change(10)"
    assert fac["params"] == {"period": 10}
    assert fac["id"].startswith("fac_")

    listing = client.get("/api/factors/library", headers=auth_headers).json()
    assert listing["total"] >= 1
    assert any(f["id"] == fac["id"] for f in listing["items"])


def test_update_factor(auth_headers):
    created = client.post(
        "/api/factors/library",
        json={"name": "待改", "expression": "close"},
        headers=auth_headers,
    ).json()
    fid = created["id"]
    upd = client.put(
        "/api/factors/library/" + fid,
        json={"name": "已改", "category": "风险"},
        headers=auth_headers,
    )
    assert upd.status_code == 200
    assert upd.json()["name"] == "已改"
    assert upd.json()["category"] == "风险"
    assert upd.json()["expression"] == "close"  # 未改字段保留


def test_delete_factor(auth_headers):
    created = client.post(
        "/api/factors/library",
        json={"name": "待删", "expression": "close"},
        headers=auth_headers,
    ).json()
    fid = created["id"]
    d = client.delete("/api/factors/library/" + fid, headers=auth_headers)
    assert d.status_code == 204
    get = client.get("/api/factors/library/" + fid, headers=auth_headers)
    assert get.status_code == 404


def test_factor_library_requires_auth():
    assert client.get("/api/factors/library").status_code == 401
    assert client.post("/api/factors/library", json={"name": "x", "expression": "close"}).status_code == 401


def test_seed_defaults_is_idempotent():
    n1 = factor_library.seed_defaults()
    n2 = factor_library.seed_defaults()
    # 第二次不应重复写入
    assert n2 == 0
    all_factors = factor_library.list_factors()
    assert len(all_factors) >= n1


def test_seed_includes_expanded_presets():
    factor_library.seed_defaults()
    names = {f["name"] for f in factor_library.list_factors()}
    for expected in [
        "动量因子(20日)", "反转因子(5日)", "波动率因子", "市值因子(成交额)",
        "RSI因子(14日)", "MACD柱因子", "换手率因子", "低波因子",
        "乖离率因子", "量价共振因子",
    ]:
        assert expected in names, f"缺少内置因子: {expected}"


def test_seed_idempotent_by_name():
    # 模拟升级：先清空，再写入部分旧版内置因子，seed 应补齐缺失项且不重名
    for f in factor_library.list_factors():
        factor_library.delete_factor(f["id"])
    # 旧版本只含前 4 个因子
    for name, cat, expr, desc, params in [
        ("动量因子(20日)", "动量", "close.pct_change(20)", "近 20 日收益率", {"period": 20}),
        ("反转因子(5日)", "反转", "close.pct_change(5) * -1", "近 5 日收益取反", {"period": 5}),
        ("波动率因子", "风险", "close.pct_change().rolling(20).std()", "20 日收益率标准差", {"window": 20}),
        ("市值因子(成交额)", "基本面", "close * volume", "收盘价×成交量", {}),
    ]:
        factor_library.create_factor(name, expr, cat, desc, params, owner_id=None)
    added = factor_library.seed_defaults()
    names = [f["name"] for f in factor_library.list_factors()]
    assert len(names) == len(set(names))  # 无重名
    assert added == 6  # 补齐其余 6 个新增因子
    assert len(names) == 10  # 共 10 个内置因子
