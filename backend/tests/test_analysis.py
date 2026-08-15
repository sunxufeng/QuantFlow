"""V16 高级回测分析测试：多参数敏感性网格 / walk-forward / 自定义基准。"""

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
    c.post("/api/auth/register", json={"username": "an_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "an_u", "password": "secret123"}
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


# --------------------------------------------------------------------------- #
# 纯函数
# --------------------------------------------------------------------------- #
class TestSplitWalkForward:
    def test_even_splits(self):
        dates = [f"2024-01-{i:02d}" for i in range(1, 21)]  # 20 天
        folds = analysis.split_walkforward(dates, 5)
        assert len(folds) == 4  # N-1 个样本外折
        # 扩张窗口：每折训练起点相同
        assert all(f[0] == dates[0] for f in folds)
        # 测试区间依次后移且不重叠错位
        assert folds[0][2] == dates[4]
        assert folds[-1][3] == dates[19]

    def test_too_few_dates_returns_empty(self):
        assert analysis.split_walkforward(["2024-01-01", "2024-01-02"], 5) == []

    def test_caps_folds_by_length(self):
        dates = [f"d{i}" for i in range(6)]
        folds = analysis.split_walkforward(dates, 20)
        assert len(folds) <= 5


class TestBuildBenchmarkValues:
    def test_explicit_values_length_mismatch(self):
        with pytest.raises(ValueError):
            analysis.build_benchmark_values(
                {"values": [1, 2, 3]}, ["d0", "d1"], 1_000_000.0
            )

    def test_explicit_values_aligned(self):
        # 显式序列按原值返回（相对指标与缩放无关）
        out = analysis.build_benchmark_values(
            {"values": [100, 110, 121]}, ["d0", "d1", "d2"], 1_000_000.0
        )
        assert out == [100, 110, 121]

    def test_basket_equal_weight(self):
        # 单标的篮子应等于其买入持有净值（按 initial 缩放）
        out = analysis.build_benchmark_values(
            {"symbols": ["T.SH"]},
            [f"2024-01-{i:02d}" for i in range(2, 22)],
            1_000_000.0,
        )
        assert len(out) == 20
        assert out[0] == 1_000_000.0
        # 末值 = 首值 * (末收盘价/首收盘价)
        assert out[-1] == pytest.approx(2_600_000.0, rel=1e-6)


# --------------------------------------------------------------------------- #
# API 端点
# --------------------------------------------------------------------------- #
class TestSensitivityGridAPI:
    def test_grid_scan(self):
        resp = client.post("/api/backtest/sensitivity-grid", json={
            "strategy": "ma_cross",
            "params": {},
            "grid": {"fast": [3, 5, 8], "slow": [15, 20, 30]},
            "symbols": ["T.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
            "metric": "total_return",
        })
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["param_a"] == "fast"
        assert d["param_b"] == "slow"
        assert len(d["grid"]) == 3 and len(d["grid"][0]) == 3
        assert d["best"]["value"] is not None
        # 矩阵元素均为数值或 None
        for row in d["grid"]:
            for v in row:
                assert v is None or isinstance(v, (int, float))

    def test_unknown_strategy_422(self):
        resp = client.post("/api/backtest/sensitivity-grid", json={
            "strategy": "nope", "grid": {"a": [1, 2], "b": [3, 4]},
            "symbols": ["T.SH"], "start": "2024-01-01", "end": "2024-02-01",

        })
        assert resp.status_code == 422

    def test_single_param_422(self):
        resp = client.post("/api/backtest/sensitivity-grid", json={
            "strategy": "ma_cross", "grid": {"a": [1, 2]},
            "symbols": ["T.SH"], "start": "2024-01-01", "end": "2024-02-01",
        })
        assert resp.status_code == 422


class TestWalkForwardAPI:
    def test_walkforward(self):
        resp = client.post("/api/backtest/walkforward", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["T.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
            "n_folds": 5,
        })
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["n_folds"] == 5
        assert len(d["folds"]) == 4
        s = d["summary"]
        assert s["n_oos_folds"] == 4
        assert s["mean_is_return"] is not None
        assert s["mean_oos_return"] is not None
        # 每折含样本内/样本外指标
        f0 = d["folds"][0]
        assert "is_metrics" in f0 and "oos_metrics" in f0
        assert "degradation_total_return" in f0

    def test_unknown_strategy_422(self):
        resp = client.post("/api/backtest/walkforward", json={
            "strategy": "nope", "symbols": ["T.SH"],
            "start": "2024-01-01", "end": "2024-02-01",
        })
        assert resp.status_code == 422


class TestBenchmarkCompareAPI:
    def _make_report(self):
        run = client.post("/api/backtest/run", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["T.SH"],
            "start": "2024-01-01",
            "end": "2024-02-01",
        })
        assert run.status_code == 200
        return run.json()["run_id"]

    def test_compare_with_basket(self):
        rid = self._make_report()
        resp = client.post("/api/backtest/benchmark-compare", json={
            "run_id": rid,
            "benchmarks": [{"name": "自身基准", "symbols": ["T.SH"]}],
        })
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["run_id"] == rid
        assert len(d["benchmarks"]) == 1
        b = d["benchmarks"][0]
        assert b["name"] == "自身基准"
        assert "relative" in b and "curve" in b
        rel = b["relative"]
        # 自身 vs 自身篮子：beta≈1, alpha≈0, 跟踪误差≈0
        assert rel["beta"] is not None
        assert rel["tracking_error"] is not None
        assert len(b["curve"]) == len(d["strategy_curve"])

    def test_compare_explicit_values(self):
        rid = self._make_report()
        strat = client.get(f"/api/backtest/reports/{rid}").json()
        n = len(strat["equity_curve"])
        vals = [1_000_000.0 * (1 + 0.001 * i) for i in range(n)]
        resp = client.post("/api/backtest/benchmark-compare", json={
            "run_id": rid,
            "benchmarks": [{"name": "平稳基准", "values": vals}],
        })
        assert resp.status_code == 200, resp.text
        b = resp.json()["benchmarks"][0]
        assert b["relative"]["beta"] is not None

    def test_unknown_run_id_404(self):
        resp = client.post("/api/backtest/benchmark-compare", json={
            "run_id": "missing", "benchmarks": [{"name": "x", "symbols": ["T.SH"]}],
        })
        assert resp.status_code == 404
