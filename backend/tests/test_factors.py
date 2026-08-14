"""V2.5 因子库与因子评分测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "factor_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "factor_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def test_catalog_lists_builtin_factors():
    r = client.get("/api/factors/scoring/catalog")
    assert r.status_code == 200, r.text
    names = [f["name"] for f in r.json()["items"]]
    for expected in ("momentum", "volatility", "rsi", "mean_reversion", "volume_trend", "drawdown", "sharpe"):
        assert expected in names


def test_score_returns_ranked_composite():
    r = client.post(
        "/api/factors/scoring/score",
        json={"symbols": ["TEST.STOCK", "TEST.BANK", "TEST.FUND"]},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "rank"
    scores = d["scores"]
    assert len(scores) == 3
    # 按综合分降序且含 rank 字段
    composites = [s["composite"] for s in scores]
    assert composites == sorted(composites, reverse=True)
    assert scores[0]["rank"] == 1
    # 每个标的都有全部因子明细
    assert "momentum" in scores[0]["factors"]
    assert scores[0]["as_of_date"]


def test_score_with_explicit_factors_and_zscore():
    r = client.post(
        "/api/factors/scoring/score",
        json={
            "symbols": ["TEST.STOCK", "TEST.BANK"],
            "factors": [{"name": "momentum", "direction": 1, "weight": 2.0}],
            "method": "zscore",
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "zscore"
    assert len(d["factors"]) == 1


def test_score_unknown_factor_422():
    r = client.post(
        "/api/factors/scoring/score",
        json={"symbols": ["TEST.STOCK"], "factors": [{"name": "not_a_factor"}]},
    )
    assert r.status_code == 422


def test_score_empty_symbols_422():
    r = client.post("/api/factors/scoring/score", json={"symbols": []})
    assert r.status_code == 422
