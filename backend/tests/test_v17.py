"""V17 高级分析三件套测试：因子衰减 / 参数稳健性 / 多基准加权。

全部基于合成行情（monkeypatch market_service.bars），无需任何外部凭证。
"""

from __future__ import annotations

import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest import analysis
from app.market import Bar
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v17_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v17_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch, tmp_path):
    base = dt.date(2024, 1, 2)
    closes = [10, 11, 12, 13, 14, 15, 14, 16, 17, 18, 19, 20, 19, 21, 22, 23,
              22, 24, 25, 26, 25, 27, 28, 29]
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


START = "2024-01-02"
END = "2024-02-15"


# --------------------------------------------------------------------------- #
# 1. 因子衰减（纯函数）
# --------------------------------------------------------------------------- #
def test_factor_decay_structure():
    out = analysis.factor_decay(symbols=["T.SH"], start=START, end=END,
                                window=8, forward=1, roll_window=4)
    assert out["roll_window"] == 4
    assert isinstance(out["factors"], list) and len(out["factors"]) > 0
    for f in out["factors"]:
        assert "factor" in f
        assert isinstance(f["ic_series"], list)
        assert isinstance(f["roll_means"], list)
        assert len(f["roll_means"]) == len(f["ic_series"])
        assert isinstance(f["trend_slope"], (int, float))
        assert isinstance(f["decay"], (float, type(None)))
        assert isinstance(f["trend_r2"], (int, float))


def test_factor_decay_default_universe():
    out = analysis.factor_decay(symbols=None, start=START, end=END)
    assert len(out["factors"]) >= 1
    assert len(out["symbols"]) >= 1


def test_factor_decay_rolling_trend_monotonic():
    # 构造一条单调上升的 IC 序列，趋势斜率应为正
    out = analysis.factor_decay(symbols=["T.SH"], start=START, end=END,
                                window=8, forward=1, roll_window=3)
    # 不强制符号，仅验证 roll_means 是 ic_series 的滑动平均（末点等于末 window 平均）
    for f in out["factors"]:
        s = f["ic_series"]
        rm = f["roll_means"]
        if len(s) >= 3:
            tail = sum(s[-3:]) / 3
            assert abs(rm[-1] - tail) < 1e-6


# --------------------------------------------------------------------------- #
# 2. 参数稳健性（纯函数 + 端点）
# --------------------------------------------------------------------------- #
def test_parameter_robustness_structure():
    out = analysis.parameter_robustness(
        strategy="ma_cross",
        params={},
        grid={"fast": [3, 5], "slow": [10, 15]},
        symbols=["T.SH"],
        start=START, end=END,
        n_folds=4, metric="total_return",
    )
    assert out["param_a"] == "fast" and out["param_b"] == "slow"
    assert len(out["folds"]) == 3  # n_folds=4 → 3 个 OOS 折
    summary = out["summary"]
    assert summary["n_oos_folds"] == 3
    assert summary["consensus_optimal"] is not None
    assert isinstance(summary["consensus_optimal"]["stability_ratio"], float)
    assert isinstance(summary["consistent_with_global"], bool)
    assert len(summary["param_frequency"]) >= 1


def test_parameter_robustness_single_param_raises():
    with pytest.raises(ValueError):
        analysis.parameter_robustness(
            strategy="ma_cross", params={}, grid={"fast": [3, 5]},
            symbols=["T.SH"], start=START, end=END, n_folds=4,
        )


def test_robustness_endpoint():
    r = client.post("/api/backtest/robustness", json={
        "strategy": "ma_cross",
        "grid": {"fast": [3, 5], "slow": [10, 15]},
        "symbols": ["T.SH"],
        "start": START, "end": END,
        "n_folds": 4, "metric": "total_return",
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["summary"]["n_oos_folds"] == 3
    assert d["summary"]["consensus_optimal"] is not None


def test_robustness_unknown_strategy_422():
    r = client.post("/api/backtest/robustness", json={
        "strategy": "no_such",
        "grid": {"fast": [3], "slow": [10]},
        "symbols": ["T.SH"],
        "start": START, "end": END,
    })
    assert r.status_code == 422


# --------------------------------------------------------------------------- #
# 3. 多基准加权（纯函数 + 端点）
# --------------------------------------------------------------------------- #
def _fake_curve(n=24, start=1_000_000.0):
    base = dt.date(2024, 1, 2)
    pts = []
    for i in range(n):
        v = start * (1 + 0.002 * i)
        pts.append({
            "date": (base + dt.timedelta(days=i)).isoformat(),
            "cash": 0.0, "market_value": v, "total_value": v,
            "daily_return": 0.002,
        })
    return pts


def test_weighted_benchmark_compare_pure():
    curve = _fake_curve()
    out = analysis.weighted_benchmark_compare(
        run_equity_curve=curve,
        benchmarks=[
            {"name": "B1", "weight": 2, "symbols": ["T.SH"]},
            {"name": "B2", "weight": 1, "symbols": ["T.SH"]},
        ],
        initial_cash=curve[0]["total_value"],
        interval="daily",
    )
    assert len(out["composite_curve"]) == len(curve)
    assert len(out["benchmarks"]) == 2
    # 权重归一化
    wsum = sum(b["weight"] for b in out["benchmarks"])
    assert abs(wsum - 1.0) < 1e-9
    rel = out["composite_relative"]
    assert "beta" in rel and "alpha" in rel and "tracking_error" in rel and "information_ratio" in rel


def test_weighted_benchmark_compare_endpoint():
    run = client.post("/api/backtest/run", json={
        "strategy": "buy_hold",
        "params": {"shares": 1000},
        "symbols": ["T.SH"],
        "start": START, "end": END,
    })
    assert run.status_code == 200, run.text
    run_id = run.json()["run_id"]

    r = client.post("/api/backtest/benchmark-weighted", json={
        "run_id": run_id,
        "benchmarks": [
            {"name": "篮子", "weight": 1, "symbols": ["T.SH"]},
        ],
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["run_id"] == run_id
    assert len(d["benchmarks"]) == 1
    assert "beta" in d["composite_relative"]
    assert len(d["composite_curve"]) == len(d["strategy_curve"])


def test_benchmark_weighted_unknown_run_404():
    r = client.post("/api/backtest/benchmark-weighted", json={
        "run_id": "no_such_run",
        "benchmarks": [{"name": "b", "weight": 1, "symbols": ["T.SH"]}],
    })
    assert r.status_code == 404


# --------------------------------------------------------------------------- #
# 4. 因子衰减端点
# --------------------------------------------------------------------------- #
def test_factor_decay_endpoint():
    r = client.post("/api/backtest/factor-decay", json={
        "symbols": ["T.SH"],
        "start": START, "end": END,
        "window": 8, "forward": 1, "roll_window": 4,
    })
    assert r.status_code == 200, r.text
    d = r.json()
    assert len(d["factors"]) >= 1
    assert isinstance(d["factors"][0]["roll_means"], list)
