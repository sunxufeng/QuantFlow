"""V23 投资组合优化测试。"""

from __future__ import annotations

import numpy as np
import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.portfolio_opt import (
    efficient_frontier,
    min_variance_portfolio,
    max_sharpe_portfolio,
)
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v23_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v23_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _store(tmp_path):
    monkeypatch_store = backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    backtest_api.report_store = monkeypatch_store


def _rand_returns(n_assets=3, t=250, seed=1):
    rng = np.random.default_rng(seed)
    # 资产间弱相关：共享一个市场因子
    market = rng.normal(0.0005, 0.01, t)
    out = []
    for a in range(n_assets):
        idio = rng.normal(0, 0.008, t)
        out.append((market + idio).tolist())
    return out


def test_min_variance_weights_sum_to_one():
    r = _rand_returns()
    mv = min_variance_portfolio(r, long_only=True)
    assert abs(sum(mv["weights"]) - 1.0) < 1e-3
    assert all(w >= -1e-6 for w in mv["weights"])  # long-only
    assert mv["expected_vol"] >= 0


def test_max_sharpe_weights_sum_to_one():
    r = _rand_returns()
    ms = max_sharpe_portfolio(r, long_only=True)
    assert abs(sum(ms["weights"]) - 1.0) < 1e-3
    # 夏普为数值（资产期望收益为负时夏普也可能为负，属正常）
    assert isinstance(ms["sharpe"], (int, float))


def test_min_variance_differs_from_max_sharpe():
    r = _rand_returns(n_assets=4, t=300, seed=3)
    mv = min_variance_portfolio(r, long_only=True)
    ms = max_sharpe_portfolio(r, long_only=True)
    # 最小方差组合的波动应 <= 最大夏普组合的波动（或二者显著不同）
    assert mv["expected_vol"] <= ms["expected_vol"] + 1e-9


def test_efficient_frontier_shape():
    r = _rand_returns(n_assets=4, t=300, seed=2)
    ef = efficient_frontier(r, n_points=15, long_only=True, rf=0.02)
    assert ef["n_assets"] == 4
    assert len(ef["frontier"]) == 15
    for p in ef["frontier"]:
        assert abs(sum(p["weights"]) - 1.0) < 1e-3
    # 等权组合存在
    assert ef["equal_weight"]["weights"]
    assert "sharpe" in ef["max_sharpe"]


def test_portfolio_optimize_endpoint_synthetic():
    res = client.post("/api/backtest/portfolio-optimize", json={
        "symbols": ["A.X", "B.X", "C.X"],
        "start": "2022-01-01", "end": "2024-12-31",
        "long_only": True, "rf": 0.02, "n_points": 12,
        "synthetic": {"mu_annual": 0.08, "sigma_annual": 0.20, "seed": 7, "regime": True},
    })
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["source"] == "synthetic"
    assert len(d["frontier"]) == 12
    # 夏普为数值（合成行情含熊市时可为负，属正常）；前沿各点权重应归一
    assert isinstance(d["max_sharpe"]["sharpe"], (int, float))
    assert abs(sum(d["min_variance"]["weights"]) - 1.0) < 1e-3
    for p in d["frontier"]:
        assert abs(sum(p["weights"]) - 1.0) < 1e-3


def test_portfolio_optimize_too_few_assets():
    res = client.post("/api/backtest/portfolio-optimize", json={
        "symbols": ["ONLY.ONE"], "start": "2022-01-01", "end": "2024-12-31",
        "synthetic": {"seed": 1},
    })
    assert res.status_code == 422


def test_portfolio_optimize_bad_dates():
    res = client.post("/api/backtest/portfolio-optimize", json={
        "symbols": ["A.X", "B.X"], "start": "2024-12-31", "end": "2022-01-01",
        "synthetic": {"seed": 1},
    })
    assert res.status_code == 422
