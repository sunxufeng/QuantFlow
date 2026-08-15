"""V42–V46 风险分析测试。"""

import numpy as np
import pytest

from app.risk import analytics as ra


def test_var_cvar_historical():
    rng = np.random.default_rng(1)
    r = rng.normal(0, 0.01, 5000).tolist()
    res = ra.var_cvar(r, confidence=0.95, method="historical")
    # 95% VaR ≈ 1.645*0.01 ≈ 0.0164
    assert 0.01 < res["var"] < 0.025
    assert res["cvar"] >= res["var"] - 1e-9


def test_var_cvar_methods_consistent():
    rng = np.random.default_rng(2)
    r = rng.normal(0, 0.01, 5000).tolist()
    h = ra.var_cvar(r, 0.99, "historical")
    p = ra.var_cvar(r, 0.99, "parametric")
    m = ra.var_cvar(r, 0.99, "montecarlo")
    # 三种方法在 99% 下应同量级
    vals = [h["var"], p["var"], m["var"]]
    assert max(vals) / min(vals) < 1.6


def test_var_backtest_runs():
    rng = np.random.default_rng(3)
    r = rng.normal(0, 0.01, 1000).tolist()
    res = ra.var_backtest(r, confidence=0.95)
    assert res["n"] == 1000
    assert 0 <= res["breaches"] <= 1000
    assert isinstance(res["passed"], bool)


def test_drawdown_analysis():
    # 构造一段明确回撤：先涨后大跌再回升
    r = [0.10, -0.20, 0.05, -0.10, 0.30, -0.05, 0.02]
    res = ra.drawdown_analysis(r)
    assert res["max_drawdown"] < 0
    assert res["n_episodes"] >= 1
    assert res["worst_episodes"]


def test_tail_risk_independent_low():
    rng = np.random.default_rng(4)
    a = rng.normal(0, 0.01, 2000).tolist()
    b = rng.normal(0, 0.01, 2000).tolist()
    res = ra.tail_risk(a, b, alpha=0.05)
    # 独立序列尾相依≈alpha(0.05)，应远小于 0.3
    assert 0 <= res["lower_tail_dependence"] < 0.3
    assert -1 <= res["normal_correlation"] <= 1


def test_liquidity_risk_cost_positive():
    positions = {"A": {"quantity": 100000, "price": 10.0}, "B": {"quantity": 50000, "price": 20.0}}
    adv = {"A": 1_000_000.0, "A_vol": 200000.0, "B": 2_000_000.0, "B_vol": 300000.0}
    res = ra.liquidity_risk(positions, adv, participation=0.1, impact_coef=0.1)
    assert res["total_market_value"] == 100000 * 10 + 50000 * 20
    assert res["total_impact_cost"] > 0
    # B 变现天数 = 50000/(0.1*300000) ≈ 1.67
    b_days = next(p["liquidation_days"] for p in res["positions"] if p["asset"] == "B")
    assert abs(b_days - 1.67) < 0.1


def test_concentration_equal_vs_concentrated():
    eq = ra.concentration({"A": 0.25, "B": 0.25, "C": 0.25, "D": 0.25})
    assert abs(eq["hhi"] - 0.25) < 1e-6
    assert abs(eq["effective_n"] - 4.0) < 1e-6
    conc = ra.concentration({"A": 0.8, "B": 0.1, "C": 0.1})
    assert conc["hhi"] > 0.6
    assert conc["effective_n"] < 2.0
    assert conc["top1"] == 0.8


def test_api_var_smoke(client):
    rng = np.random.default_rng(5)
    r = rng.normal(0, 0.01, 800).tolist()
    resp = client.post("/api/risk/var", json={"returns": r, "confidence": 0.95, "method": "historical"})
    assert resp.status_code == 200
    body = resp.json()
    assert "var" in body and "cvar" in body
