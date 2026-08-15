"""V27 绩效归因增强 API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "attr_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "attr_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def test_brinson_attribution():
    payload = {
        "method": "brinson",
        "groups": [
            {"name": "tech", "portfolio_weight": 0.6, "benchmark_weight": 0.5,
             "portfolio_return": 0.12, "benchmark_return": 0.10},
            {"name": "fin", "portfolio_weight": 0.4, "benchmark_weight": 0.5,
             "portfolio_return": 0.05, "benchmark_return": 0.07},
        ],
    }
    r = client.post("/api/backtest/performance-attribution", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "brinson"
    # 效应之和应等于主动收益
    assert d["checksum_ok"] is True
    assert abs((d["total_allocation"] + d["total_selection"] + d["total_interaction"])
               - d["active_return"]) < 1e-6
    assert len(d["groups"]) == 2


def test_factor_attribution():
    payload = {
        "method": "factor",
        "factors": [
            {"name": "mkt", "exposure": 1.1, "factor_return": 0.08},
            {"name": "smb", "exposure": 0.3, "factor_return": 0.02},
        ],
        "specific_return": 0.01,
    }
    r = client.post("/api/backtest/performance-attribution", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "factor"
    assert abs(d["total_return"] - (d["explained_return"] + d["specific_return"])) < 1e-6


def test_holdings_attribution():
    payload = {
        "method": "holdings",
        "holdings": [
            {"symbol": "A", "weight": 0.5, "return_": 0.10},
            {"symbol": "B", "weight": 0.5, "return_": -0.02},
        ],
    }
    r = client.post("/api/backtest/performance-attribution", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "holdings"
    assert d["holdings"][0]["symbol"] == "A"  # 按贡献降序
    assert d["holdings"][0]["cumulative_pct"] == 1.25 or abs(d["holdings"][0]["cumulative_pct"] - 1.25) < 1e-6


def test_invalid_method_rejected():
    r = client.post("/api/backtest/performance-attribution", json={"method": "nope"})
    assert r.status_code == 422
