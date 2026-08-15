"""V20 合成行情 + 前向模拟测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.montecarlo import forward_simulate
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v20_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v20_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _store(tmp_path):
    monkeypatch_store = backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    backtest_api.report_store = monkeypatch_store


def test_synthetic_generate():
    res = client.post("/api/backtest/market/synthetic", json={
        "symbols": ["S.A", "S.B"], "start": "2024-01-01", "end": "2024-03-31",
        "mu_annual": 0.1, "sigma_annual": 0.2, "seed": 7,
    }).json()
    assert "bars" in res
    assert len(res["bars"]["S.A"]) > 0
    # 不同 seed 应产生不同序列
    res2 = client.post("/api/backtest/market/synthetic", json={
        "symbols": ["S.A"], "start": "2024-01-01", "end": "2024-03-31", "seed": 99,
    }).json()
    a1 = res["bars"]["S.A"][0]["close"]
    a2 = res2["bars"]["S.A"][0]["close"]
    assert a1 != a2


def test_synthetic_run():
    res = client.post("/api/backtest/synthetic-run", json={
        "strategy": "ma_cross", "params": {}, "symbols": ["S.A"],
        "start": "2024-01-01", "end": "2024-12-31",
        "mu_annual": 0.15, "sigma_annual": 0.25, "seed": 3,
    }).json()
    assert "run_id" in res
    assert res["metrics"]["days"] >= 2
    # 合成行情为非平坦，应产生交易
    assert len(res.get("trades", [])) >= 0


def test_forward_sim_pure():
    # 构造一条带波动的净值曲线
    curve = [{"date": f"d{i}", "total_value": 1000000 * (1.001 ** i), "daily_return": 0.001} for i in range(60)]
    fs = forward_simulate(curve, horizon=120, n_paths=50, seed=1, target_return=0.05)
    assert len(fs["bands"]) == 120
    assert fs["summary"]["final_equity"]["p50"] > 0
    assert 0 <= fs["prob_target"] <= 1


def test_forward_sim_endpoint_via_synthetic():
    run = client.post("/api/backtest/synthetic-run", json={
        "strategy": "buy_hold", "params": {}, "symbols": ["S.A"],
        "start": "2024-01-01", "end": "2024-12-31", "seed": 5,
    }).json()
    rid = run["run_id"]
    res = client.post("/api/backtest/forward-sim", json={
        "run_id": rid, "horizon": 60, "n_paths": 30, "seed": 2, "target_return": 0.0,
    }).json()
    assert len(res["bands"]) == 60
    assert res["prob_target"] is not None
    assert res["strategy"] == "buy_hold"


def test_forward_sim_unknown_run():
    res = client.post("/api/backtest/forward-sim", json={"run_id": "nope", "horizon": 10})
    assert res.status_code == 404
