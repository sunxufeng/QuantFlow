"""V3.2 因子排行榜 API 测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(username: str = "rank_u") -> dict:
    client.post(
        "/api/auth/register",
        json={"username": username, "password": "secret123"},
    )
    r = client.post(
        "/api/auth/login",
        json={"username": username, "password": "secret123"},
    )
    token = r.json()["token"]
    return {"Authorization": f"Bearer {token}"}


def test_ranking_requires_auth():
    resp = client.get("/api/factors/research/ranking")
    assert resp.status_code == 401


def test_ranking_returns_sorted_rows():
    headers = _auth("rank_u1")
    resp = client.get("/api/factors/research/ranking", headers=headers)
    assert resp.status_code == 200
    d = resp.json()
    assert d["metric"] == "mean_ic"
    ranked = d["ranked"]
    assert len(ranked) == 7  # 7 个内置因子
    keys = {"factor", "direction", "description", "mean_ic", "std_ic", "ir",
            "ic_positive_ratio", "observations", "ic_series"}
    assert keys.issubset(set(ranked[0].keys()))
    # 默认按均值 IC 降序：每行非空则单调不增
    vals = [r["mean_ic"] for r in ranked if r["mean_ic"] is not None]
    assert vals == sorted(vals, reverse=True)
    # 缺失 IC 的因子（样本不足）必须排在末尾，与排序方向无关
    assert ranked[-1]["mean_ic"] is None
    assert all(r["mean_ic"] is not None for r in ranked[:-1])


def test_ranking_metric_and_order_params():
    headers = _auth("rank_u2")
    resp = client.get(
        "/api/factors/research/ranking",
        headers=headers,
        params={"metric": "ir", "order": "asc"},
    )
    assert resp.status_code == 200
    d = resp.json()
    assert d["metric"] == "ir" and d["order"] == "asc"
    vals = [r["ir"] for r in d["ranked"] if r["ir"] is not None]
    assert vals == sorted(vals)  # 升序


def test_ranking_invalid_metric_falls_back():
    headers = _auth("rank_u3")
    resp = client.get(
        "/api/factors/research/ranking",
        headers=headers,
        params={"metric": "bogus"},
    )
    assert resp.status_code == 200
    assert resp.json()["metric"] == "mean_ic"
