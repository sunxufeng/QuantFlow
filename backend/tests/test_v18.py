"""V18 扩展风险指标测试：CVaR / Calmar / Omega / 期望收益 / 水下曲线。"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.engine import EquityPoint
from app.backtest.metrics import PerformanceMetrics
from app.market import Bar
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v18_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v18_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch, tmp_path):
    base = dt.date(2024, 1, 2)
    closes = [10, 11, 12, 13, 14, 15, 14, 16, 17, 18, 19, 20, 19, 21, 22, 23,
              22, 24, 25, 26]
    all_bars = [
        Bar(symbol="T.SH", date=(base + dt.timedelta(days=i)).isoformat(),
            open=float(c), high=float(c), low=float(c), close=float(c), volume=1e6)
        for i, c in enumerate(closes)
    ]

    def fake_bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        if symbol == "NODATA.SH":
            return []
        bars = all_bars
        if start:
            bars = [b for b in bars if b.date >= start]
        if end:
            bars = [b for b in bars if b.date <= end]
        return bars

    monkeypatch.setattr(backtest_api.market_service, "bars", fake_bars)
    monkeypatch.setattr(
        backtest_api, "report_store", backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    )


def _make_points(closes, initial=1_000_000.0):
    dates = [(dt.date(2024, 1, 1) + dt.timedelta(days=i)).isoformat() for i in range(len(closes))]
    pts = []
    for i, c in enumerate(closes):
        v = initial * (c / closes[0])
        pts.append(EquityPoint(date=dates[i], cash=0.0, market_value=v, total_value=v,
                               daily_return=0.0 if i == 0 else c / closes[i - 1] - 1.0))
    return pts


def test_extended_risk_pure():
    # 含涨跌的序列：VaR/CVaR 有限，Omega>0，水下曲线非正
    pts = _make_points([10, 11, 10.5, 12, 11.5, 13, 12.5, 14])
    m = PerformanceMetrics(pts, pts[0].total_value, [])
    er = m.extended_risk
    assert len(er["underwater"]) == len(pts)
    assert all(d <= 0.0 for d in er["underwater"])
    # 历史法 VaR/CVaR：CVaR <= VaR，且均为有限数
    assert er["cvar95_annual"] <= er["var95_annual"]
    assert er["var95_annual"] == er["var95_annual"]  # 有限（非 NaN）
    assert er["omega"] > 0
    assert er["calmar"] >= 0


def test_extended_risk_drawdown_underwater():
    # 先涨后跌：水下曲线应出现负值
    pts = _make_points([10, 12, 14, 12, 10, 11])
    m = PerformanceMetrics(pts, pts[0].total_value, [])
    er = m.extended_risk
    assert min(er["underwater"]) < 0
    assert m.max_drawdown < 0


def test_extended_risk_with_losses():
    # 含亏损的序列：VaR/CVaR 应为负
    pts = _make_points([10, 9, 8, 9, 10, 11, 10, 9, 8, 7])
    m = PerformanceMetrics(pts, pts[0].total_value, [])
    er = m.extended_risk
    assert er["cvar95_annual"] < 0
    assert er["var95_annual"] < 0


def test_metrics_extended_endpoint():
    run = client.post("/api/backtest/run", json={
        "strategy": "buy_hold", "params": {"shares": 1000},
        "symbols": ["T.SH"], "start": "2024-01-01", "end": "2024-12-31",
    }).json()
    rid = run["run_id"]
    res = client.post("/api/backtest/metrics-extended", json={"run_id": rid}).json()
    assert "metrics" in res
    er = res["metrics"]["extended_risk"]
    assert "underwater" in er and "cvar95_annual" in er and "calmar" in er
    assert len(er["underwater"]) == res["metrics"]["days"]


def test_metrics_extended_unknown_run():
    res = client.post("/api/backtest/metrics-extended", json={"run_id": "nope"})
    assert res.status_code == 404
