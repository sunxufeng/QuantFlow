"""V28 回测参数优化器 · 随机搜索增强测试。

覆盖：随机搜索抽样数量/去重、种子可复现、分布类型（int/float/choice）、
非法分布报错、与网格模式的兼容，以及 /optimize API 端点随机模式返回结构。
行情源以 synthetic 数据打桩，避免依赖外部数据源。
"""

from __future__ import annotations

import datetime as dt

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
    c.post("/api/auth/register", json={"username": "optr_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "optr_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _fake_market(monkeypatch):
    def fake_bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        closes = [
            10, 10.2, 10.5, 10.3, 10.8, 11.2, 11.0, 11.4, 11.1, 11.6,
            12.0, 11.8, 12.2, 12.5, 12.1, 12.6, 13.0, 12.7, 13.2, 13.5,
        ]
        base = dt.date(2024, 1, 2)
        return [
            Bar(
                symbol=symbol,
                date=(base + dt.timedelta(days=i)).isoformat(),
                open=float(c), high=float(c), low=float(c), close=float(c),
                volume=1e6,
            )
            for i, c in enumerate(closes)
        ]

    monkeypatch.setattr(optimize.__globals__["market_service"], "bars", fake_bars)


DIST = {
    "fast": {"type": "int", "low": 2, "high": 20},
    "slow": {"type": "int", "low": 10, "high": 40},
    "threshold": {"type": "float", "low": 0.1, "high": 0.5},
}


def test_random_returns_n_samples():
    res = optimize(
        strategy="ma_cross",
        method="random",
        distributions=DIST,
        n_samples=25,
        seed=42,
        symbols=["TEST.STOCK"],
        start="2024-01-02",
        end="2024-02-01",
    )
    assert res["method"] == "random"
    assert res["total_combos"] == 25
    assert res["completed"] == 25
    # 所有抽样参数落在分布范围内
    for row in res["top"]:
        p = row["params"]
        assert 2 <= int(p["fast"]) <= 20
        assert 10 <= int(p["slow"]) <= 40
        assert 0.1 <= float(p["threshold"]) <= 0.5


def test_random_seed_reproducible():
    kw = dict(
        strategy="ma_cross", method="random", distributions=DIST, n_samples=20,
        symbols=["TEST.STOCK"], start="2024-01-02", end="2024-02-01",
    )
    a = optimize(**kw, seed=7)
    b = optimize(**kw, seed=7)
    assert a["top"][0]["params"] == b["top"][0]["params"]
    # 不同种子大概率不同（抽样空间远大于样本数，几乎必然不同）
    c = optimize(**kw, seed=99)
    assert a["top"][0]["params"] != c["top"][0]["params"]


def test_random_dedup_and_choice():
    dist = {
        "fast": {"type": "choice", "values": [3, 5, 8]},
        "slow": {"type": "choice", "values": [10, 20]},
    }
    res = optimize(
        strategy="ma_cross", method="random", distributions=dist, n_samples=10,
        seed=1, symbols=["TEST.STOCK"], start="2024-01-02", end="2024-02-01",
    )
    combos = [tuple(sorted(r["params"].items())) for r in res["top"]]
    assert len(combos) == len(set(combos))  # 去重
    assert len(res["top"]) <= 6  # 组合空间上限 3*2=6
    for r in res["top"]:
        assert r["params"]["fast"] in [3, 5, 8]
        assert r["params"]["slow"] in [10, 20]


def test_random_requires_distributions():
    with pytest.raises(OptimizeConfigError):
        optimize(
            strategy="ma_cross", method="random", distributions={},
            n_samples=10, symbols=["TEST.STOCK"],
            start="2024-01-02", end="2024-02-01",
        )


def test_random_bad_distribution_type():
    with pytest.raises(OptimizeConfigError):
        optimize(
            strategy="ma_cross", method="random",
            distributions={"x": {"type": "unknown"}},
            n_samples=10, symbols=["TEST.STOCK"],
            start="2024-01-02", end="2024-02-01",
        )


def test_grid_still_works_alongside_random():
    res = optimize(
        strategy="ma_cross",
        grid={"fast": [3, 5], "slow": [10, 15]},
        symbols=["TEST.STOCK"],
        start="2024-01-02",
        end="2024-02-01",
    )
    assert res["method"] == "grid"
    assert res["total_combos"] == 4


def test_api_optimize_random_mode():
    r = client.post(
        "/api/backtest/optimize",
        json={
            "strategy": "ma_cross",
            "method": "random",
            "distributions": DIST,
            "n_samples": 15,
            "seed": 123,
            "symbols": ["TEST.STOCK"],
            "start": "2024-01-02",
            "end": "2024-02-01",
            "objective": "sharpe",
        },
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["method"] == "random"
    assert d["total_combos"] == 15
    assert d["completed"] == 15


def test_api_optimize_random_missing_dist_422():
    r = client.post(
        "/api/backtest/optimize",
        json={
            "strategy": "ma_cross",
            "method": "random",
            "distributions": {},
            "n_samples": 10,
            "symbols": ["TEST.STOCK"],
            "start": "2024-01-02",
            "end": "2024-02-01",
        },
    )
    assert r.status_code == 422
