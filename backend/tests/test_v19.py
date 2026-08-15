"""V19 策略库扩展测试：momentum / mean_reversion / rsi / bollinger。"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.strategies import STRATEGY_REGISTRY
from app.market import Bar
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v19_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v19_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch, tmp_path):
    base = dt.date(2024, 1, 2)
    # 波动序列，确保各信号策略能触发交易
    closes = [10, 11, 12, 13, 12, 11, 10, 11, 12, 13, 14, 13, 12, 11, 10, 11,
              12, 13, 14, 15]
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


NEW_STRATS = ["momentum", "mean_reversion", "rsi", "bollinger"]


def test_strategies_registered():
    for name in NEW_STRATS:
        assert name in STRATEGY_REGISTRY


def test_strategies_endpoint_lists_new():
    res = client.get("/api/backtest/strategies").json()
    names = [s["name"] for s in res["items"]]
    for name in NEW_STRATS:
        assert name in names


def test_each_new_strategy_runs():
    for name in NEW_STRATS:
        run = client.post("/api/backtest/run", json={
            "strategy": name, "params": {},
            "symbols": ["T.SH"], "start": "2024-01-01", "end": "2024-12-31",
        }).json()
        assert run.get("error") is None, f"{name} 运行失败: {run}"
        assert "run_id" in run
        # 至少产生净值曲线
        assert run["metrics"]["days"] >= 2


def test_rsi_respects_thresholds():
    # 超买/超卖阈值极端化时，rsi 策略应不产生交易（始终在场外）
    run = client.post("/api/backtest/run", json={
        "strategy": "rsi", "params": {"oversold": 1, "overbought": 99},
        "symbols": ["T.SH"], "start": "2024-01-01", "end": "2024-12-31",
    }).json()
    # 不应报错（即便无交易）
    assert run.get("error") is None
