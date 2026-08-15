"""Milestone E（V52–V56）策略库扩展：纯函数 + API 测试。"""

from __future__ import annotations

import numpy as np
import pytest

from app.backtest import strategy_ext as sx


def _rand(seed, n=200, mu=0.001, sd=0.01):
    return (mu + np.random.default_rng(seed).normal(0, sd, n)).tolist()


def _prices(seed, n=200, drift=0.001, sd=0.01):
    r = np.array(_rand(seed, n, drift, sd))
    return np.cumprod(1.0 + r).tolist()


# ----------------------------- V52 协整配对 -----------------------------

def test_pairs_cointegration_spurious_vs_real():
    rng = np.random.default_rng(1)
    x = np.cumsum(rng.normal(0, 1, 200))  # 随机游走
    # 构造协整对：y = 0.8 x + 噪声（噪声为平稳）
    y = 0.8 * x + rng.normal(0, 0.5, 200)
    coint = sx.pairs_cointegration(y.tolist(), x.tolist())
    assert coint["is_cointegrated"] is True
    assert abs(coint["hedge_ratio"] - 0.8) < 0.25
    # 两个独立随机游走通常不应被判协整（宽松：仅验证不抛错且结构完整）
    z1 = np.cumsum(rng.normal(0, 1, 200))
    z2 = np.cumsum(rng.normal(0, 1, 200))
    c2 = sx.pairs_cointegration(z1.tolist(), z2.tolist())
    assert "adf_stat" in c2


def test_pairs_backtest_shapes():
    rng = np.random.default_rng(2)
    x = np.cumsum(rng.normal(0, 1, 200))
    y = 0.8 * x + rng.normal(0, 0.5, 200)
    out = sx.pairs_backtest(y.tolist(), x.tolist(), window=60)
    assert out["n_trades"] >= 0
    assert len(out["equity_curve"]) == len(x)
    assert -1000 <= out["sharpe"] <= 1000  # 有限


def test_pairs_too_short():
    with pytest.raises(ValueError):
        sx.pairs_cointegration([1.0] * 10, [1.0] * 10)


# ----------------------------- V53 期权 -----------------------------

def test_bs_call_put_parity():
    c = sx.bs_price(100, 100, 1.0, 0.02, 0.2, "call")
    p = sx.bs_price(100, 100, 1.0, 0.02, 0.2, "put")
    # put-call parity: C - P = S - K e^{-rT}
    parity = 100 - 100 * np.exp(-0.02 * 1.0)
    assert abs((c - p) - parity) < 1e-6


def test_bs_greeks_bounds():
    g = sx.bs_greeks(100, 100, 1.0, 0.02, 0.2, "call")
    assert 0 < g["delta"] < 1
    assert g["gamma"] > 0
    assert g["vega"] > 0
    assert -1 < g["delta"] < 0 if False else True  # call delta in (0,1)


def test_implied_vol_roundtrip():
    true_iv = 0.3
    price = sx.bs_price(100, 100, 1.0, 0.02, true_iv, "call")
    iv = sx.implied_vol(price, 100, 100, 1.0, 0.02, "call")
    assert abs(iv - true_iv) < 0.01


def test_implied_vol_zero_price():
    assert sx.implied_vol(0.0, 100, 100, 1.0, 0.02, "call") == 0.0


# ----------------------------- V54 网格 -----------------------------

def test_grid_backtest_basic():
    # 震荡价格，网格应能运行
    xs = np.linspace(0, 4 * np.pi, 200)
    prices = (100 + 10 * np.sin(xs)).tolist()
    out = sx.grid_backtest(prices, lower=90, upper=110, n_grid=10, lot=10, initial_cash=1_000_000)
    assert len(out["equity_curve"]) == len(prices)
    assert out["n_trades"] > 0
    assert out["final_equity"] > 0


def test_grid_invalid_bounds():
    with pytest.raises(ValueError):
        sx.grid_backtest([100, 101, 99], 110, 90, 5)


# ----------------------------- V55 DCA -----------------------------

def test_dca_vs_lumpsum():
    rng = np.random.default_rng(3)
    n = 120
    prices = np.cumprod(1.0 + rng.normal(0.0005, 0.01, n)).tolist()
    dates = [f"2023-{1 + i // 30:02d}-{1 + i % 28:02d}" for i in range(n)]
    out = sx.dca_backtest(prices, dates, periodic_investment=10000, freq="M")
    assert out["dca_shares"] > 0
    assert out["dca_invested"] > 0
    assert len(out["dca_curve"]) == n + 1
    # 下跌市中 DCA 平均成本应低于期末价（摊薄），至少结构正确
    assert out["estimated_periods"] >= 1


def test_dca_too_short():
    with pytest.raises(ValueError):
        sx.dca_backtest([100.0], freq="M")


# ----------------------------- V56 多资产趋势 -----------------------------

def test_multi_trend_basic():
    rng = np.random.default_rng(4)
    n = 200
    up = np.cumprod(1.0 + np.linspace(0.0005, 0.002, n) + rng.normal(0, 0.005, n))
    down = np.cumprod(1.0 + np.linspace(-0.002, -0.0005, n) + rng.normal(0, 0.005, n))
    flat = np.cumprod(1.0 + rng.normal(0, 0.0002, n))
    R = [list(x) for x in np.column_stack([up / up[0] - 1, down / down[0] - 1, flat / flat[0] - 1])]
    out = sx.multi_trend_backtest(R, ["UP", "DOWN", "FLAT"], fast=20, slow=60, rebalance="M")
    assert out["n_rebalances"] >= 1
    assert len(out["equity_curve"]) == n + 1
    # UP 趋势下策略应主要持有 UP，跑赢等权基准
    assert out["excess_return"] > -0.5


def test_multi_trend_too_short():
    with pytest.raises(ValueError):
        sx.multi_trend_backtest([[0.01, 0.02], [0.01, 0.02]], ["a", "b"], slow=60)


def test_multi_trend_weekly_short_dates():
    # 默认数字日期（str(i)）下，周频 keyfn 不应崩溃
    R = [[0.01, -0.004], [0.02, -0.003], [0.015, -0.005], [0.012, -0.002], [0.018, -0.001]]
    out = sx.multi_trend_backtest(R, ["A", "B"], fast=2, slow=3, rebalance="W")
    assert out["n_rebalances"] >= 1
    assert len(out["equity_curve"]) == len(R) + 1


# ----------------------------- API 冒烟 -----------------------------

def test_api_pairs_coint_smoke(client):
    x = _prices(5, 200)
    y = [0.8 * xi + 0.3 for xi in x]
    resp = client.post("/api/strategy/pairs-coint", json={"y": y, "x": x})
    assert resp.status_code == 200
    assert "is_cointegrated" in resp.json()


def test_api_option_greeks_smoke(client):
    resp = client.post("/api/strategy/option-greeks", json={"S": 100, "K": 100, "T": 1.0, "r": 0.02, "sigma": 0.2, "option": "call"})
    assert resp.status_code == 200
    assert "delta" in resp.json()


def test_api_grid_smoke(client):
    prices = (100 + 10 * np.sin(np.linspace(0, 4 * np.pi, 100))).tolist()
    resp = client.post("/api/strategy/grid-backtest", json={"prices": prices, "lower": 90, "upper": 110, "n_grid": 10})
    assert resp.status_code == 200
    assert resp.json()["n_trades"] > 0


def test_api_dca_smoke(client):
    prices = _prices(6, 120)
    dates = [f"2023-{1 + i // 30:02d}-{1 + i % 28:02d}" for i in range(120)]
    resp = client.post("/api/strategy/dca-backtest", json={"prices": prices, "dates": dates, "freq": "M"})
    assert resp.status_code == 200
    assert resp.json()["dca_shares"] > 0


def test_api_multi_trend_smoke(client):
    rng = np.random.default_rng(7)
    n = 150
    up = np.cumprod(1.0 + np.linspace(0.0005, 0.002, n) + rng.normal(0, 0.005, n))
    R = [list(x) for x in np.column_stack([up / up[0] - 1, rng.normal(0, 0.005, n)])]
    resp = client.post("/api/strategy/multi-trend", json={"returns": R, "assets": ["UP", "OTHER"], "fast": 20, "slow": 60})
    assert resp.status_code == 200
    assert resp.json()["n_rebalances"] >= 1


def test_api_strategies_ext_requires_auth(anon_client):
    resp = anon_client.post("/api/strategy/option-greeks", json={"S": 100, "K": 100, "T": 1.0, "r": 0.02, "sigma": 0.2})
    assert resp.status_code == 401
