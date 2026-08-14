"""V2.1 回测参数优化器测试。

覆盖：网格展开、绩效排序、单组失败隔离、组合上限保护、API 端点鉴权与返回结构。
行情源以 synthetic 数据打桩，避免依赖外部数据源。
"""

from __future__ import annotations

import datetime as dt
from typing import List

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest import optimize
from app.backtest.optimizer import OptimizeConfigError
from app.main import app
from app.market import Bar

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "opt_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "opt_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


def _bars(closes, symbol, volume=1e6):
    base = dt.date(2024, 1, 2)
    return [
        Bar(
            symbol=symbol,
            date=(base + dt.timedelta(days=i)).isoformat(),
            open=float(c),
            high=float(c),
            low=float(c),
            close=float(c),
            volume=float(volume),
        )
        for i, c in enumerate(closes)
    ]


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch):
    def fake_bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        if symbol == "NODATA.SH":
            return []
        # 一段有明显趋势的收盘价，便于均线策略产生差异
        closes = [
            10, 10.2, 10.5, 10.3, 10.8, 11.2, 11.0, 11.4, 11.1, 11.6,
            12.0, 11.8, 12.2, 12.5, 12.1, 12.6, 13.0, 12.7, 13.2, 13.5,
        ]
        return _bars(closes, symbol)

    monkeypatch.setattr(optimize.__globals__["market_service"], "bars", fake_bars)


# --------------------------------------------------------------------------- #
# 纯函数测试
# --------------------------------------------------------------------------- #
def test_optimize_ranks_by_objective():
    res = optimize(
        strategy="ma_cross",
        fixed_params={},
        grid={"fast": [3, 5], "slow": [10, 15, 20]},
        symbols=["TEST.STOCK"],
        start="2024-01-02",
        end="2024-02-01",
    )
    assert res["total_combos"] == 6
    assert res["completed"] == 6
    assert res["failed"] == 0
    # 按目标（默认 sharpe）降序
    sharpe_vals = [r["metrics"]["sharpe"] for r in res["top"]]
    assert sharpe_vals == sorted(sharpe_vals, reverse=True)
    assert res["top"][0]["rank"] == 1
    assert set(res["top"][0]["params"].keys()) >= {"fast", "slow"}


def test_optimize_respects_top_n():
    res = optimize(
        strategy="ma_cross",
        grid={"fast": [3, 5, 7], "slow": [10, 15, 20]},
        symbols=["TEST.STOCK"],
        start="2024-01-02",
        end="2024-02-01",
        top_n=2,
    )
    assert len(res["top"]) == 2


def test_optimize_unknown_strategy():
    with pytest.raises(OptimizeConfigError):
        optimize(
            strategy="nope",
            symbols=["TEST.STOCK"],
            start="2024-01-02",
            end="2024-02-01",
        )


def test_optimize_combo_limit():
    with pytest.raises(OptimizeConfigError):
        optimize(
            strategy="ma_cross",
            grid={"fast": list(range(1, 30)), "slow": list(range(1, 40))},
            symbols=["TEST.STOCK"],
            start="2024-01-02",
            end="2024-02-01",
            max_combos=10,
        )


def test_optimize_isolates_failures():
    # 注入一个会在运行中抛错的策略工厂
    from app.backtest import strategies as strat_mod

    original = strat_mod.STRATEGY_REGISTRY["ma_cross"]

    def boom_factory(params):
        raise RuntimeError("boom at build")

    strat_mod.STRATEGY_REGISTRY["ma_cross"] = boom_factory
    try:
        res = optimize(
            strategy="ma_cross",
            grid={"fast": [3], "slow": [10]},
            symbols=["TEST.STOCK"],
            start="2024-01-02",
            end="2024-02-01",
        )
        assert res["completed"] == 0
        assert res["failed"] == 1
        assert res["failures"][0]["error"]
    finally:
        strat_mod.STRATEGY_REGISTRY["ma_cross"] = original


# --------------------------------------------------------------------------- #
# API 测试
# --------------------------------------------------------------------------- #
def test_api_optimize_success():
    resp = client.post(
        "/api/backtest/optimize",
        json={
            "strategy": "ma_cross",
            "grid": {"fast": [3, 5], "slow": [10, 15]},
            "symbols": ["TEST.STOCK"],
            "start": "2024-01-02",
            "end": "2024-02-01",
            "objective": "total_return",
        },
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()
    assert data["objective"] == "total_return"
    assert data["total_combos"] == 4
    rets = [r["metrics"]["total_return"] for r in data["top"]]
    assert rets == sorted(rets, reverse=True)


def test_api_optimize_requires_auth():
    anon = TestClient(app)
    resp = anon.post(
        "/api/backtest/optimize",
        json={
            "strategy": "ma_cross",
            "grid": {"fast": [3], "slow": [10]},
            "symbols": ["TEST.STOCK"],
            "start": "2024-01-02",
            "end": "2024-02-01",
        },
    )
    assert resp.status_code == 401


def test_api_optimize_bad_objective():
    resp = client.post(
        "/api/backtest/optimize",
        json={
            "strategy": "ma_cross",
            "grid": {"fast": [3], "slow": [10]},
            "symbols": ["TEST.STOCK"],
            "start": "2024-01-02",
            "end": "2024-02-01",
            "objective": "invalid",
        },
    )
    assert resp.status_code == 422
