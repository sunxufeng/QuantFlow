"""N3 因子分析 API 测试：鉴权 / 表格分析 / 行情构建分析。"""

import pytest
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


def _ic_table_payload():
    rows = [
        {"date": "d1", "factor": 1, "fwd_return": 2},
        {"date": "d1", "factor": 2, "fwd_return": 3},
        {"date": "d1", "factor": 3, "fwd_return": 1},
        {"date": "d1", "factor": 4, "fwd_return": 4},
        {"date": "d2", "factor": 2, "fwd_return": 1},
        {"date": "d2", "factor": 4, "fwd_return": 2},
        {"date": "d2", "factor": 1, "fwd_return": 3},
        {"date": "d2", "factor": 3, "fwd_return": 4},
    ]
    return {"columns": ["date", "factor", "fwd_return"], "rows": rows}


def test_analyze_requires_auth():
    resp = client.post("/api/factors/analyze", json={"table": _ic_table_payload()})
    assert resp.status_code == 401


def test_analyze_table():
    headers = _auth_headers("fac_user1")
    resp = client.post(
        "/api/factors/analyze",
        json={"table": _ic_table_payload(), "n_quantiles": 4, "max_lag": 2},
        headers=headers,
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    assert report["ic"]["mean"] == pytest.approx(0.2)
    assert report["ic"]["ir"] == pytest.approx(0.7071067811865475)
    assert len(report["ic_decay"]) == 2
    assert report["quantile_returns"]["long_short"] is not None


def test_analyze_rows_columns():
    headers = _auth_headers("fac_user2")
    payload = _ic_table_payload()
    resp = client.post(
        "/api/factors/analyze",
        json={
            "columns": payload["columns"],
            "rows": payload["rows"],
            "factor": "factor",
            "forward_return": "fwd_return",
            "date": "date",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    assert resp.json()["report"]["ic"]["n"] == 2


def test_analyze_from_market_symbols():
    headers = _auth_headers("fac_user3")
    # 至少 3 个标的，保证每个交易日的截面样本 >= 3（RankIC 最低样本要求）
    resp = client.post(
        "/api/factors/analyze",
        json={
            "symbols": ["TEST.STOCK", "TEST.BANK", "TEST.FUND"],
            "start": "2024-01-01",
            "end": "2024-02-01",
        },
        headers=headers,
    )
    assert resp.status_code == 200
    report = resp.json()["report"]
    # 由行情构建的动量因子，应有 IC 统计与分层收益
    assert report["ic"]["n"] >= 1
    assert "by_quantile" in report["quantile_returns"]


def test_analyze_missing_input_400():
    headers = _auth_headers("fac_user4")
    resp = client.post("/api/factors/analyze", json={}, headers=headers)
    assert resp.status_code == 400


# --------------------------------------------------------------------------- #
# 因子研究（V2.9）：相关性矩阵 + IC/IR
# --------------------------------------------------------------------------- #
def test_research_matrix():
    headers = _auth_headers("fac_user5")
    resp = client.get("/api/factors/research/matrix", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["factors"]) == 7
    assert len(body["matrix"]) == 7 and len(body["matrix"][0]) == 7
    # 对角线应为 1.0
    for i in range(7):
        assert body["matrix"][i][i] == 1.0
    assert body["dates_count"] >= 1


def test_research_ic():
    headers = _auth_headers("fac_user6")
    resp = client.get("/api/factors/research/ic?window=10", headers=headers)
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["results"]) == 7
    # 多数因子应有观测样本（合成 20 日行情，window=10 约 9 期）
    obs = [v["observations"] for v in body["results"].values()]
    assert sum(1 for o in obs if o and o > 0) >= 3
    # 有样本因子的 mean_ic 应为有限数值
    for v in body["results"].values():
        if v["observations"] and v["observations"] > 0:
            assert isinstance(v["mean_ic"], (int, float))
            assert isinstance(v["ir"], (int, float))
