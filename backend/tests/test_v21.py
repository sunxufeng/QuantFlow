"""V21 季节性 / 日历效应分析测试。"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.analysis import seasonality
from app.market import synthetic
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v21_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v21_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _store(tmp_path):
    monkeypatch_store = backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    backtest_api.report_store = monkeypatch_store


def _synth_bars(seed=7):
    return synthetic.generate_symbol(
        "SYN.X", "2022-01-01", "2024-12-31", initial_price=100.0,
        mu_annual=0.08, sigma_annual=0.25, seed=seed, regime=True,
    )


def test_seasonality_pure():
    bars = _synth_bars()
    res = seasonality(symbol="SYN.X", start="2022-01-01", end="2024-12-31", bars=bars)
    assert res["n_days"] == len(bars) - 1
    # 12 个月 + 5 个工作日聚合
    assert len(res["by_month"]) == 12
    assert len(res["by_weekday"]) == 5
    # 每个有数据的桶都有均值/计数/胜率
    for m in res["by_month"]:
        if m["count"] > 0:
            assert m["mean_return"] is not None
            assert 0.0 <= (m["win_rate"] or 0) <= 1.0
    # 月初/月末效应结构完整
    tom = res["turn_of_month"]
    assert "turn" in tom and "non_turn" in tom
    assert "edge" in tom
    assert tom["turn"]["count"] + tom["non_turn"]["count"] == res["n_days"]
    # 摘要存在最佳/最差月
    assert res["summary"]["best_month"] is not None
    assert res["summary"]["worst_month"] is not None


def test_seasonality_insufficient_data():
    bars = _synth_bars()[:1]  # 只有一个 bar，无法计算收益
    with pytest.raises(ValueError):
        seasonality(symbol="SYN.X", bars=bars)


def test_seasonality_endpoint_synthetic():
    res = client.post("/api/backtest/seasonality", json={
        "symbol": "SYN.X", "start": "2022-01-01", "end": "2024-12-31",
        "synthetic": {"mu_annual": 0.08, "sigma_annual": 0.25, "seed": 11, "regime": True},
    })
    assert res.status_code == 200, res.text
    data = res.json()
    assert data["source"] == "synthetic"
    assert len(data["by_month"]) == 12
    assert data["turn_of_month"]["interpretation"]


def test_seasonality_endpoint_bad_dates():
    res = client.post("/api/backtest/seasonality", json={
        "symbol": "SYN.X", "start": "2024-12-31", "end": "2022-01-01",
        "synthetic": {"seed": 1},
    })
    assert res.status_code == 422


def test_seasonality_endpoint_empty_live(monkeypatch):
    # 模拟真实行情为空 -> 无法计算（InsufficientData -> 422）
    import app.api.backtest as bt
    monkeypatch.setattr(bt.market_service, "bars", lambda *a, **k: [])
    res = client.post("/api/backtest/seasonality", json={
        "symbol": "EMPTY", "start": "2022-01-01", "end": "2024-12-31",
    })
    assert res.status_code == 422


def test_seasonality_endpoint_fetch_error(monkeypatch):
    # 模拟行情拉取抛错 -> 503
    import app.api.backtest as bt
    def _boom(*a, **k):
        raise RuntimeError("行情服务不可用")
    monkeypatch.setattr(bt.market_service, "bars", _boom)
    res = client.post("/api/backtest/seasonality", json={
        "symbol": "ERR", "start": "2022-01-01", "end": "2024-12-31",
    })
    assert res.status_code == 503
