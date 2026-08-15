"""V27 行情数据质量校验 API 测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "dq_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "dq_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def test_detects_multiple_issues():
    bars = [
        {"timestamp": "2024-01-01", "open": 10, "high": 9, "low": 10, "close": 10, "volume": 100},  # high<low
        {"timestamp": "2024-01-01", "open": 10, "high": 12, "low": 9, "close": 11, "volume": 0},   # 重复 + 零量
        {"timestamp": "2024-01-10", "open": None, "high": 13, "low": 10, "close": 12, "volume": 50},  # 缺失 + 缺口(9天)
    ]
    payload = {"symbol": "X", "bars": bars, "expected_interval_days": 1, "as_of": "2024-01-10"}
    r = client.post("/api/backtest/data-quality", json=payload)
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["score"] < 100
    assert d["summary"]["issues_total"] >= 4
    assert d["summary"]["by_severity"]["high"] >= 2  # high<low + 重复
    assert d["summary"]["duplicate_ts"] >= 1
    assert d["summary"]["missing_fields"] >= 1
    assert d["summary"]["gap"] >= 1
    # 等级应在合理范围
    assert d["grade"] in ("A", "B", "C", "D", "E")


def test_clean_series_scores_high():
    bars = [
        {"timestamp": "2024-01-01", "open": 10, "high": 10.5, "low": 9.8, "close": 10.2, "volume": 1000},
        {"timestamp": "2024-01-02", "open": 10.2, "high": 10.6, "low": 10.0, "close": 10.4, "volume": 1100},
        {"timestamp": "2024-01-03", "open": 10.4, "high": 10.9, "low": 10.3, "close": 10.7, "volume": 1050},
    ]
    r = client.post("/api/backtest/data-quality", json={"bars": bars})
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["score"] == 100.0
    assert d["issues"] == []
    assert d["grade"] == "A"


def test_empty_bars_rejected():
    r = client.post("/api/backtest/data-quality", json={"bars": []})
    assert r.status_code == 422
