"""V2.3 预警规则引擎测试。

覆盖：CRUD、算子比较、cross 上穿/下穿、冷却去重、评估触发通知、API 鉴权与返回结构。
行情源打桩，避免依赖外部数据；通知渠道未配置时静默（不报错）。
"""

from __future__ import annotations

from typing import List

import pytest
from fastapi.testclient import TestClient

from app.alerts import alert_service, market_service
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "alert_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "alert_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def _fake_bars(prices: List[float]):
    from app.market import Bar
    import datetime as dt

    def bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        base = dt.date(2024, 1, 2)
        return [
            Bar(
                symbol=symbol,
                date=(base + dt.timedelta(days=i)).isoformat(),
                open=float(p), high=float(p), low=float(p), close=float(p), volume=1e6,
            )
            for i, p in enumerate(prices)
        ]

    return bars


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch):
    monkeypatch.setattr(market_service, "bars", _fake_bars([100.0, 101.0, 102.0, 99.0, 105.0]))


# --------------------------------------------------------------------------- #
# API 测试
# --------------------------------------------------------------------------- #
def test_alert_crud_and_evaluate():
    resp = client.post(
        "/api/alerts",
        json={"name": "高价预警", "symbol": "TEST.STOCK", "metric": "price",
              "operator": ">", "threshold": 1000.0},
    )
    assert resp.status_code == 201, resp.text
    rid = resp.json()["id"]

    lst = client.get("/api/alerts").json()
    assert any(r["id"] == rid for r in lst["items"])

    # 阈值 1000 远高于最新价 105 -> 不触发
    ev = client.post("/api/alerts/evaluate").json()
    assert ev["evaluated"] >= 1
    my = next(r for r in ev["results"] if r["id"] == rid)
    assert my["triggered"] is False

    # 调到 100 -> 触发
    client.post(f"/api/alerts/{rid}", json={"name": "高价预警", "symbol": "TEST.STOCK",
                  "metric": "price", "operator": ">", "threshold": 100.0})
    # 改阈值需删除重建（无更新接口），改为新建一条
    resp2 = client.post(
        "/api/alerts",
        json={"name": "低价触发", "symbol": "TEST.STOCK", "metric": "price",
              "operator": ">", "threshold": 100.0},
    )
    rid2 = resp2.json()["id"]
    ev2 = client.post("/api/alerts/evaluate").json()
    my2 = next(r for r in ev2["results"] if r["id"] == rid2)
    assert my2["triggered"] is True

    # 冷却：再次评估同一规则，本次处于冷却期，不再重复通知
    ev3 = client.post("/api/alerts/evaluate").json()
    my3 = next(r for r in ev3["results"] if r["id"] == rid2)
    assert my3["triggered"] is True
    assert my3["notified"] is False

    # toggle + delete
    t = client.post(f"/api/alerts/{rid2}/toggle", json={"enabled": False}).json()
    assert t["enabled"] is False
    assert client.delete(f"/api/alerts/{rid}").status_code == 204
    assert client.delete(f"/api/alerts/{rid}").status_code == 404


def test_alert_invalid_metric():
    resp = client.post(
        "/api/alerts",
        json={"name": "x", "symbol": "TEST.STOCK", "metric": "nope", "operator": ">", "threshold": 1},
    )
    assert resp.status_code == 422


# --------------------------------------------------------------------------- #
# 引擎单元测试
# --------------------------------------------------------------------------- #
def test_cross_operators():
    # 序列: ...99 -> 105 上穿 100
    monkeypatch_bars = _fake_bars([100.0, 101.0, 102.0, 99.0, 105.0])
    market_service.bars = monkeypatch_bars

    r_up = alert_service.create_rule("上穿", "TEST.STOCK", metric="price", operator="cross_above", threshold=100.0)
    res_up = alert_service.evaluate_all()
    up = next(r for r in res_up if r["id"] == r_up["id"])
    assert up["triggered"] is True

    r_down = alert_service.create_rule("下穿", "TEST.STOCK", metric="price", operator="cross_below", threshold=100.0)
    res_down = alert_service.evaluate_all()
    down = next(r for r in res_down if r["id"] == r_down["id"])
    assert down["triggered"] is False
