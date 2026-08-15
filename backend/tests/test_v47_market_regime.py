"""Milestone D（V47–V51）市场状态与择时：纯函数 + API 测试。"""

from __future__ import annotations

import math

import numpy as np
import pytest

from app.market import regime as mr


def _gen(seed, n=300, drift=0.0005, vol=0.01):
    rng = np.random.default_rng(seed)
    r = drift + rng.normal(0, vol, n)
    return r.tolist()


def _matrix(seed, n=120, k=4):
    rng = np.random.default_rng(seed)
    return (rng.normal(0, 0.01, (n, k))).tolist(), [f"A{i}" for i in range(k)]


# ----------------------------- V47 市场状态检测 -----------------------------

def test_detect_regime_shapes_and_labels():
    r = _gen(1, n=120)
    out = mr.detect_regime(r, long_ma=60)
    assert out["regime"] in mr.REGIME_LABELS
    assert out["score"] >= -1 and out["score"] <= 1
    assert len(out["series"]) == 120
    assert set(out["regime_counts"].values())  # 计数覆盖所有期


def test_detect_regime_bull_vs_bear():
    up = [0.01] * 120
    down = [-0.01] * 120
    bull = mr.detect_regime(up, long_ma=60)
    bear = mr.detect_regime(down, long_ma=60)
    assert bull["regime"] in ("bull", "volatile_up")
    assert bear["regime"] in ("bear", "volatile_down")


def test_detect_regime_too_short():
    with pytest.raises(ValueError):
        mr.detect_regime([0.01] * 30, long_ma=60)


# ----------------------------- V48 波动率预测 -----------------------------

def test_forecast_ewma_constant():
    r = _gen(2, n=120)
    out = mr.forecast_volatility(r, method="ewma", horizon=10)
    assert out["method"] == "ewma"
    assert len(out["forecasts"]) == 10
    # EWMA 多步预测为同一常数
    first = out["forecasts"][0]["annualized_vol"]
    last = out["forecasts"][-1]["annualized_vol"]
    assert abs(first - last) < 1e-9


def test_forecast_garch_mean_reverting():
    r = _gen(3, n=300, vol=0.02)
    out = mr.forecast_volatility(r, method="garch", garch_alpha=0.08, garch_beta=0.90, horizon=20)
    assert out["method"] == "garch"
    # 长期方差应小于短期极端波动预测的首项（均值回复）
    assert out["long_run_annualized_vol"] > 0
    assert len(out["forecasts"]) == 20


def test_forecast_vol_too_short():
    with pytest.raises(ValueError):
        mr.forecast_volatility([0.01] * 10, method="ewma")


# ----------------------------- V49 板块轮动 -----------------------------

def test_sector_rotation_signals():
    secs = {
        "tech": [0.01] * 60,
        "fin": [0.002] * 60,
        "energy": [-0.008] * 60,
    }
    out = mr.sector_rotation(secs, window=60)
    assert out["signals"]["tech"] == "overweight"
    assert out["signals"]["energy"] == "underweight"
    # ranked 按动量降序，tech 第一
    assert out["ranked"][0]["sector"] == "tech"
    assert abs(sum(out["tilt_weights"].values()) - 1.0) < 1e-6


def test_sector_rotation_empty():
    with pytest.raises(ValueError):
        mr.sector_rotation({}, window=60)


# ----------------------------- V50 相关性聚类网络 -----------------------------

def test_correlation_network_clusters():
    rng = np.random.default_rng(7)
    n = 100
    # 构造两组高相关资产
    base1 = rng.normal(0, 0.01, n)
    base2 = rng.normal(0, 0.01, n)
    R = np.column_stack([base1 + rng.normal(0, 0.002, n), base1 + rng.normal(0, 0.002, n),
                         base2 + rng.normal(0, 0.002, n), base2 + rng.normal(0, 0.002, n)])
    out = mr.correlation_network(R.tolist(), ["x1", "x2", "y1", "y2"], n_clusters=2)
    assert out["n_clusters"] <= 4
    # x1,x2 同簇，y1,y2 同簇
    assert out["asset_cluster"]["x1"] == out["asset_cluster"]["x2"]
    assert out["asset_cluster"]["y1"] == out["asset_cluster"]["y2"]
    assert out["avg_intra_cluster_corr"] > out["avg_inter_cluster_corr"]


def test_correlation_network_dim_mismatch():
    with pytest.raises(ValueError):
        mr.correlation_network([[0.01, 0.02], [0.01, 0.02]], ["a", "b", "c"])


# ----------------------------- V51 ETF 动量轮动回测 -----------------------------

def test_etf_rotation_basic():
    rng = np.random.default_rng(11)
    n = 250
    # A 持续上涨，B 持续下跌，C/D 震荡
    A = (np.linspace(0.001, 0.003, n) + rng.normal(0, 0.005, n)).tolist()
    B = (-np.linspace(0.001, 0.003, n) + rng.normal(0, 0.005, n)).tolist()
    C = rng.normal(0.0005, 0.01, n).tolist()
    D = rng.normal(-0.0005, 0.01, n).tolist()
    R = [list(x) for x in np.column_stack([A, B, C, D])]
    dates = [f"2023-{1 + i // 30:02d}-{1 + i % 28:02d}" for i in range(n)]
    out = mr.etf_momentum_rotation(R, ["A", "B", "C", "D"], dates, lookback=20, hold_top=1, rebalance="M")
    assert out["n_rebalances"] >= 1
    assert len(out["equity_curve"]) == n + 1
    assert len(out["benchmark_curve"]) == n + 1
    # 动量轮动应抓住 A，跑赢等权基准
    assert out["excess_return"] > -0.5


def test_etf_rotation_too_short():
    with pytest.raises(ValueError):
        mr.etf_momentum_rotation([[0.01, 0.02], [0.01, 0.02]], ["a", "b"], lookback=20)


# ----------------------------- API 冒烟 -----------------------------

def test_api_regime_smoke(client):
    r = _gen(5, n=120)
    resp = client.post("/api/market/regime", json={"returns": r})
    assert resp.status_code == 200
    assert resp.json()["regime"] in mr.REGIME_LABELS


def test_api_vol_forecast_smoke(client):
    resp = client.post("/api/market/vol-forecast", json={"returns": _gen(6, n=120), "method": "ewma"})
    assert resp.status_code == 200
    assert resp.json()["method"] == "ewma"


def test_api_sector_rotation_smoke(client):
    resp = client.post("/api/market/sector-rotation", json={"sector_returns": {"a": [0.01] * 40, "b": [-0.01] * 40}, "window": 40})
    assert resp.status_code == 200
    assert "signals" in resp.json()


def test_api_correlation_network_smoke(client):
    R, assets = _matrix(8)
    resp = client.post("/api/market/correlation-network", json={"returns": R, "assets": assets})
    assert resp.status_code == 200
    assert resp.json()["n_clusters"] >= 1


def test_api_etf_rotation_smoke(client):
    rng = np.random.default_rng(9)
    n = 200
    A = (np.linspace(0.001, 0.004, n) + rng.normal(0, 0.005, n)).tolist()
    B = rng.normal(0, 0.01, n).tolist()
    R = [list(x) for x in np.column_stack([A, B])]
    resp = client.post("/api/market/etf-rotation", json={"returns": R, "assets": ["A", "B"], "lookback": 20, "rebalance": "M"})
    assert resp.status_code == 200
    assert resp.json()["n_rebalances"] >= 1


def test_api_market_regime_requires_auth(anon_client):
    resp = anon_client.post("/api/market/regime", json={"returns": [0.01] * 120})
    assert resp.status_code == 401
