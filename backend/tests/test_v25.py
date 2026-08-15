"""V25 成交分析测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.trade_analysis import analyze_from_dicts
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v25_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v25_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _store(tmp_path):
    monkeypatch_store = backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    backtest_api.report_store = monkeypatch_store


def _trades():
    return [
        {"symbol": "A", "side": "sell", "shares": 100, "price": 11, "costs": {}, "date": "2024-01-02", "pnl": 100},
        {"symbol": "A", "side": "sell", "shares": 100, "price": 9, "costs": {}, "date": "2024-01-03", "pnl": -50},
        {"symbol": "B", "side": "sell", "shares": 100, "price": 12, "costs": {}, "date": "2024-01-04", "pnl": 200},
    ]


def test_analyze_trades_summary():
    r = analyze_from_dicts(_trades())
    s = r["summary"]
    assert s["total_trades"] == 3
    assert abs(s["win_rate"] - 2 / 3) < 1e-3  # 摘要四舍五入到 4 位（0.6667）
    assert s["profit_factor"] == 6.0
    assert s["avg_win"] == 150.0
    assert s["avg_loss"] == -50.0
    assert abs(s["payoff_ratio"] - 3.0) < 1e-6
    assert s["largest_win"] == 200.0
    assert s["largest_loss"] == -50.0


def test_analyze_trades_blotter_cumulative():
    r = analyze_from_dicts(_trades())
    # 按日期排序后累计盈亏：100, 50, 250
    cum = [b["cumulative_pnl"] for b in r["blotter"]]
    assert cum == [100.0, 50.0, 250.0]


def test_analyze_trades_by_symbol():
    r = analyze_from_dicts(_trades())
    sym = {b["symbol"]: b for b in r["by_symbol"]}
    assert sym["A"]["trades"] == 2
    assert sym["A"]["total_pnl"] == 50.0
    assert sym["B"]["total_pnl"] == 200.0


def test_trade_analysis_endpoint_via_synthetic():
    run = client.post("/api/backtest/synthetic-run", json={
        "strategy": "ma_cross", "params": {}, "symbols": ["S.A"],
        "start": "2022-01-01", "end": "2024-12-31",
        "mu_annual": 0.12, "sigma_annual": 0.25, "seed": 4, "regime": True,
    })
    assert run.status_code == 200, run.text
    rid = run.json()["run_id"]
    res = client.post("/api/backtest/trade-analysis", json={"run_id": rid})
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["summary"]["total_trades"] > 0
    assert d["blotter"]


def test_trade_analysis_unknown_run():
    res = client.post("/api/backtest/trade-analysis", json={"run_id": "nope"})
    assert res.status_code == 404


def test_trade_analysis_no_trades():
    # 构造一份无成交的报告，触发端点 422（buy_hold 合成回测末期会清算产生成交，故直接落盘空 trades 报告）
    import app.api.backtest as bt
    rid = "empty_trades_report"
    bt.report_store.save({"run_id": rid, "strategy": "x", "symbols": ["S.A"], "trades": []})
    res = client.post("/api/backtest/trade-analysis", json={"run_id": rid})
    assert res.status_code == 422
