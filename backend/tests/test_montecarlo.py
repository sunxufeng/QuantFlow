"""蒙特卡洛鲁棒性模拟测试（V15）。"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.montecarlo import monte_carlo
from app.market import Bar
from app.main import app


client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    """回测接口需登录，模块级 client 自带合法令牌。"""
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "mc_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "mc_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch, tmp_path):
    def fake_bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        if symbol == "NODATA.SH":
            return []
        return _bars([10, 11, 12, 13, 14, 15, 14, 16, 17, 18], symbol)

    monkeypatch.setattr(backtest_api.market_service, "bars", fake_bars)
    monkeypatch.setattr(
        backtest_api, "report_store", backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    )


def _bars(closes, symbol="T.SH"):
    base = dt.date(2024, 1, 2)
    return [
        Bar(symbol=symbol, date=(base + dt.timedelta(days=i)).isoformat(),
            open=float(c), high=float(c), low=float(c), close=float(c), volume=1e6)
        for i, c in enumerate(closes)
    ]


def _equity_curve(closes, initial=1_000_000.0):
    """构造净值曲线（含 daily_return、total_value、date）。"""
    pts = []
    prev = initial
    for i, c in enumerate(closes):
        tv = initial * (c / closes[0])
        dr = tv / prev - 1.0 if i > 0 else 0.0
        pts.append({
            "date": (dt.date(2024, 1, 2) + dt.timedelta(days=i)).isoformat(),
            "cash": 0.0,
            "market_value": tv,
            "total_value": tv,
            "daily_return": dr,
        })
        prev = tv
    return pts


class TestMonteCarloPure:
    def test_deterministic_same_seed(self):
        curve = _equity_curve([10, 11, 12, 13, 14, 15, 14, 16, 17, 18])
        a = monte_carlo(curve, 1_000_000.0, n_sims=50, seed=42)
        b = monte_carlo(curve, 1_000_000.0, n_sims=50, seed=42)
        assert a["summary"]["final_equity"]["p50"] == b["summary"]["final_equity"]["p50"]
        assert a["bands"][-1]["p50"] == b["bands"][-1]["p50"]

    def test_different_seed_differs(self):
        curve = _equity_curve([10, 11, 12, 13, 14, 15, 14, 16, 17, 18])
        a = monte_carlo(curve, 1_000_000.0, n_sims=50, seed=1)
        b = monte_carlo(curve, 1_000_000.0, n_sims=50, seed=2)
        # 不同种子应产生不同模拟（极偶然相同才失败）
        assert a["summary"]["final_equity"]["p50"] != b["summary"]["final_equity"]["p50"]

    def test_band_length_and_percentile_order(self):
        curve = _equity_curve([10, 11, 12, 13, 14, 15, 14, 16, 17, 18])
        mc = monte_carlo(curve, 1_000_000.0, n_sims=100, seed=7)
        assert len(mc["bands"]) == len(curve)
        for b in mc["bands"]:
            assert b["p_low"] <= b["p25"] <= b["p50"] <= b["p75"] <= b["p_high"]

    def test_summary_fields_and_histogram_sum(self):
        curve = _equity_curve([10, 11, 12, 13, 14, 15, 14, 16, 17, 18])
        n = 120
        mc = monte_carlo(curve, 1_000_000.0, n_sims=n, seed=3)
        for key in ("final_equity", "total_return", "max_drawdown", "sharpe"):
            row = mc["summary"][key]
            assert set(row) >= {"p5", "p25", "p50", "p75", "p95", "mean"}
        assert sum(mc["histogram"]["counts"]) == n
        assert len(mc["histogram"]["bin_centers"]) == len(mc["histogram"]["counts"])

    def test_actual_metrics_present(self):
        curve = _equity_curve([10, 11, 12, 13, 14, 15, 14, 16, 17, 18])
        mc = monte_carlo(curve, 1_000_000.0, n_sims=30, seed=5)
        assert mc["actual"]["final_value"] == 1_800_000.0  # 18/10 * 1e6
        assert "sharpe" in mc["actual"]

    def test_too_few_returns_raises(self):
        curve = _equity_curve([10, 11])
        with pytest.raises(ValueError):
            monte_carlo(curve, 1_000_000.0, n_sims=10, seed=1)

    def test_accepts_equitypoint_like_objects(self):
        # 用简单命名元组式对象验证 _get 兼容
        from types import SimpleNamespace
        pts = [
            SimpleNamespace(date="2024-01-02", total_value=1_000_000.0, daily_return=0.0),
            SimpleNamespace(date="2024-01-03", total_value=1_100_000.0, daily_return=0.1),
            SimpleNamespace(date="2024-01-04", total_value=1_210_000.0, daily_return=0.1),
        ]
        mc = monte_carlo(pts, 1_000_000.0, n_sims=20, seed=9)
        assert len(mc["bands"]) == 3


class TestMonteCarloAPI:
    def test_run_spec_flow(self):
        resp = client.post("/api/backtest/montecarlo", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["TEST.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
            "n_sims": 50,
            "seed": 11,
            "confidence": 0.9,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["n_sims"] == 50
        assert data["strategy"] == "buy_hold"
        assert len(data["bands"]) >= 2
        assert "summary" in data and "histogram" in data
        assert data["actual"]["final_value"] > 0

    def test_run_id_flow(self):
        # 先跑一次回测落盘
        run = client.post("/api/backtest/run", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["TEST.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
        })
        assert run.status_code == 200
        rid = run.json()["run_id"]
        resp = client.post("/api/backtest/montecarlo", json={
            "run_id": rid,
            "n_sims": 40,
            "seed": 21,
        })
        assert resp.status_code == 200, resp.text
        data = resp.json()
        assert data["run_id"] == rid
        assert len(data["bands"]) >= 2

    def test_unknown_strategy_422(self):
        resp = client.post("/api/backtest/montecarlo", json={
            "strategy": "nope",
            "symbols": ["TEST.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
        })
        assert resp.status_code == 422

    def test_missing_run_and_spec_422(self):
        resp = client.post("/api/backtest/montecarlo", json={"n_sims": 10})
        assert resp.status_code == 422

    def test_unknown_run_id_404(self):
        resp = client.post("/api/backtest/montecarlo", json={"run_id": "missing-id"})
        assert resp.status_code == 404
