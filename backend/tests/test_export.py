"""V6.2 批量导出中心。

验证：
- GET /api/export 需登录；
- resource=factors 导出当前用户因子（按 owner 隔离），json/csv 两种格式；
- resource=templates / backtests 可导出；
- 非法 resource / format 返回 400。
"""

from __future__ import annotations

import csv
import io
import json

from app.core.db import db


def _seed_factor(user_id: str, name: str):
    db.execute(
        "INSERT INTO factor_library(id, name, category, expression, description, params, owner_id, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?,?,?)",
        (f"fac_{name}", name, "动量", "mom = close.pct_change(20)", "测试因子", "{}", user_id, "2026-01-01 00:00:00", "2026-01-01 00:00:00"),
    )


def test_export_requires_auth(anon_client):
    assert anon_client.get("/api/export?resource=factors&format=json").status_code == 401


def test_export_factors_json(client):
    # 取当前用户 id：通过 /api/auth/me
    me = client.get("/api/auth/me").json()
    _seed_factor(me["id"], "test_factor_1")
    r = client.get("/api/export?resource=factors&format=json")
    assert r.status_code == 200
    data = r.json()
    assert data["resource"] == "factors"
    assert data["count"] >= 1
    names = [i["name"] for i in data["items"]]
    assert "test_factor_1" in names
    # 当前用户可见（owner 隔离）
    assert all(i["owner_id"] == me["id"] for i in data["items"])


def test_export_factors_csv(client):
    me = client.get("/api/auth/me").json()
    _seed_factor(me["id"], "test_factor_csv")
    r = client.get("/api/export?resource=factors&format=csv")
    assert r.status_code == 200
    assert "text/csv" in r.headers["content-type"]
    assert "attachment" in r.headers.get("content-disposition", "")
    text = r.text.lstrip("\ufeff")
    reader = list(csv.DictReader(io.StringIO(text)))
    assert reader
    assert reader[0]["name"] == "test_factor_csv"
    assert "name" in reader[0] and "expression" in reader[0]


def test_export_templates_and_backtests(client):
    for res in ("templates", "backtests"):
        r = client.get(f"/api/export?resource={res}&format=json")
        assert r.status_code == 200
        assert r.json()["resource"] == res
        assert isinstance(r.json()["items"], list)


def test_export_invalid_resource(client):
    assert client.get("/api/export?resource=bogus&format=json").status_code == 400


def test_export_invalid_format(client):
    assert client.get("/api/export?resource=factors&format=xls").status_code == 400
