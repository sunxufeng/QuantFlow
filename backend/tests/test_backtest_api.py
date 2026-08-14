"""回测交易 API 测试（M2 核心引擎交付）。"""

from __future__ import annotations

import datetime as dt
from typing import List

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.main import app
from app.market import Bar

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    """V1.7 起回测接口需登录，模块级 client 改为自带合法令牌。"""
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "bt_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "bt_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def _bars(closes: List[float], symbol: str, volume: float = 1e6) -> List[Bar]:
    base = dt.date(2024, 1, 2)
    return [
        Bar(symbol=symbol, date=(base + dt.timedelta(days=i)).isoformat(),
            open=float(c), high=float(c), low=float(c), close=float(c), volume=float(volume))
        for i, c in enumerate(closes)
    ]


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch, tmp_path):
    """隔离行情源与报告存储。"""
    def fake_bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        if symbol == "NODATA.SH":
            return []
        if symbol == "FUND.X":
            return _bars([1.0 + i * 0.001 for i in range(60)], symbol, volume=0.0)
        return _bars([10, 11, 12, 13, 14], symbol)

    monkeypatch.setattr(backtest_api.market_service, "bars", fake_bars)
    monkeypatch.setattr(
        backtest_api, "report_store", backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    )


class TestStrategiesEndpoint:
    def test_list_strategies(self):
        resp = client.get("/api/backtest/strategies")
        assert resp.status_code == 200
        names = {i["name"] for i in resp.json()["items"]}
        assert names == {"buy_hold", "ma_cross", "fund_dingtou", "fund_value_avg", "futures_ma_cross"}


class TestRunBacktest:
    def test_buy_hold_report(self):
        resp = client.post("/api/backtest/run", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["TEST.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
        })
        assert resp.status_code == 200
        report = resp.json()
        assert report["type"] == "backtest_report"
        assert len(report["trades"]) == 2
        assert len(report["equity_curve"]) == 5
        assert report["metrics"]["days"] == 5
        assert report["run_id"]

    def test_fund_dingtou_report(self):
        resp = client.post("/api/backtest/run", json={
            "strategy": "fund_dingtou",
            "params": {"amount": 1000},
            "symbols": ["FUND.X"],
            "start": "2024-01-01",
            "end": "2024-04-01",
            "asset_types": {"FUND.X": "fund"},
        })
        assert resp.status_code == 200
        report = resp.json()
        assert "fund_account" in report
        subs = [t for t in report["trades"] if t["side"] == "subscribe"]
        assert len(subs) == 3

    def test_unknown_strategy_422(self):
        resp = client.post("/api/backtest/run", json={
            "strategy": "nope", "symbols": ["TEST.SH"],
            "start": "2024-01-01", "end": "2024-02-01",
        })
        assert resp.status_code == 422

    def test_futures_backtest_report(self):
        # 期货回测：futures_ma_cross + asset_type future，应返回含 futures_account 的报告
        resp = client.post("/api/backtest/run", json={
            "strategy": "futures_ma_cross",
            "params": {"contracts": 1},
            "symbols": ["TEST.FUT"],
            "start": "2024-01-01",
            "end": "2024-02-01",
            "asset_types": {"TEST.FUT": "future"},
            "multipliers": {"TEST.FUT": 10.0},
        })
        assert resp.status_code == 200
        report = resp.json()
        assert report["type"] == "backtest_report"
        assert "futures_account" in report
        assert report["futures_account"]["initial_cash"] == pytest.approx(1_000_000)

    def test_no_data_422(self):
        resp = client.post("/api/backtest/run", json={
            "strategy": "buy_hold", "symbols": ["NODATA.SH"],
            "start": "2024-01-01", "end": "2024-02-01",
        })
        assert resp.status_code == 422

    def test_invalid_date_range_422(self):
        resp = client.post("/api/backtest/run", json={
            "strategy": "buy_hold", "symbols": ["TEST.SH"],
            "start": "2024-02-01", "end": "2024-01-01",
        })
        assert resp.status_code == 422


class TestReportsEndpoint:
    def test_report_roundtrip(self):
        resp = client.post("/api/backtest/run", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["TEST.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
        })
        run_id = resp.json()["run_id"]

        listed = client.get("/api/backtest/reports").json()
        assert run_id in listed["items"]

        detail = client.get(f"/api/backtest/reports/{run_id}")
        assert detail.status_code == 200
        assert detail.json()["run_id"] == run_id

    def test_report_not_found_404(self):
        resp = client.get("/api/backtest/reports/does-not-exist")
        assert resp.status_code == 404
