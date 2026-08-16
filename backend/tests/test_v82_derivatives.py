import math

import numpy as np
import pytest

from app.derivatives import hedging as dh


# ----------------------------- V82 期权盈亏图 -----------------------------

def test_payoff_long_call():
    out = dh.option_payoff([
        {"type": "call", "side": "long", "strike": 100, "premium": 5, "qty": 1},
    ], spot_min=80, spot_max=120, n_points=41)
    # 行权价 100、权利金 5 的多头 call：spot=120 时 pnl = 20-5 = 15
    assert out["pnl"][-1] == pytest.approx(15.0, abs=1e-6)
    assert out["max_loss"] == pytest.approx(-5.0)
    assert out["max_profit"] == pytest.approx(15.0)  # 采样区间内最大


def test_payoff_bull_call_spread_breakeven():
    out = dh.option_payoff([
        {"type": "call", "side": "long", "strike": 100, "premium": 5, "qty": 1},
        {"type": "call", "side": "short", "strike": 110, "premium": 2, "qty": 1},
    ], spot_min=90, spot_max=120, n_points=61)
    # 牛市价差最大亏损 = -(5-2) = -3；最大盈利 = (110-100)-(5-2) = 7
    assert out["max_loss"] == pytest.approx(-3.0)
    assert out["max_profit"] == pytest.approx(7.0)
    assert len(out["breakeven"]) >= 1


def test_payoff_empty():
    with pytest.raises(ValueError):
        dh.option_payoff([])


# ----------------------------- V83 Delta 对冲 -----------------------------

def test_delta_hedge_recovers_premium():
    # 用 BS 路径：对冲损益应接近 0（理想对冲）
    rng = np.random.default_rng(1)
    steps = 50
    dt = 1.0 / steps
    S0 = 100.0; sigma = 0.2; r = 0.0; K = 100.0
    path = [S0]
    s = S0
    for _ in range(steps):
        z = rng.normal()
        s = s * math.exp((r - 0.5 * sigma ** 2) * dt + sigma * math.sqrt(dt) * z)
        path.append(s)
    out = dh.delta_hedge(path, K, r, sigma, rebalance_every=1, option_type="call")
    # 完美再平衡下对冲损益应很小
    assert abs(out["hedge_pnl"]) < 2.0
    assert out["n_rebalances"] == steps


def test_delta_hedge_dim():
    with pytest.raises(ValueError):
        dh.delta_hedge([100.0], 100.0)


def test_delta_hedge_bad_strike():
    with pytest.raises(ValueError):
        dh.delta_hedge([100.0, 101.0, 102.0], 0.0)


# ----------------------------- V84 组合保险 -----------------------------

def test_insurance_put_floor():
    risky = [100, 90, 80, 70, 85, 95]
    out = dh.portfolio_insurance(risky, method="put", floor=0.8)
    floor_val = 0.8 * 100
    # 保险价值不低于 floor
    assert min(out["insured_value"]) >= floor_val - 1e-9
    assert out["min_value"] >= floor_val - 1e-9


def test_insurance_cppi_never_below_floor():
    risky = [100, 60, 40, 30, 50, 80]
    out = dh.portfolio_insurance(risky, method="cppi", floor=0.8, cppi_multiplier=4.0)
    floor_val = 0.8 * 100
    assert min(out["insured_value"]) >= floor_val - 1e-6


def test_insurance_collar_caps():
    risky = [100, 200, 300, 150, 100]
    out = dh.portfolio_insurance(risky, method="collar", floor=0.8, collar_cap=1.5)
    cap = 1.5 * 100
    assert max(out["insured_value"]) <= cap + 1e-9


def test_insurance_bad_method():
    with pytest.raises(ValueError):
        dh.portfolio_insurance([100, 90], method="foo")


def test_insurance_bad_floor():
    with pytest.raises(ValueError):
        dh.portfolio_insurance([100, 90], floor=1.2)


# ----------------------------- V85 组合 Greeks -----------------------------

def test_portfolio_greeks_long_call():
    out = dh.portfolio_greeks([
        {"type": "call", "strike": 100, "t": 1.0, "sigma": 0.2, "qty": 1, "side": "long"},
    ], spot=100, r=0.0)
    assert 0 < out["delta"] <= 1.0
    assert out["gamma"] > 0
    assert out["vega"] > 0


def test_portfolio_greeks_offsetting():
    # 多头 call + 空头 call 同参数 -> 净 Greek ≈ 0
    pos = [
        {"type": "call", "strike": 100, "t": 1.0, "sigma": 0.2, "qty": 1, "side": "long"},
        {"type": "call", "strike": 100, "t": 1.0, "sigma": 0.2, "qty": 1, "side": "short"},
    ]
    out = dh.portfolio_greeks(pos, spot=100)
    assert out["delta"] == pytest.approx(0.0, abs=1e-9)
    assert out["gamma"] == pytest.approx(0.0, abs=1e-9)


def test_portfolio_greeks_empty():
    with pytest.raises(ValueError):
        dh.portfolio_greeks([], spot=100)


# ----------------------------- V86 隐含波动率曲面 -----------------------------

def test_vol_surface_atm_and_skew():
    strikes = [90, 100, 110]
    mats = [0.25, 0.5, 1.0]
    iv = [
        [0.22, 0.21, 0.20],
        [0.20, 0.19, 0.18],
        [0.18, 0.17, 0.16],
    ]
    out = dh.implied_vol_surface(strikes, mats, iv, spot=100)
    assert len(out["atm_term_structure"]) == 3
    assert len(out["skew_by_maturity"]) == 3
    # ATM 在 spot=100（中间行权价）
    assert out["atm_term_structure"][0] == pytest.approx(0.20)


def test_vol_surface_dim_mismatch():
    with pytest.raises(ValueError):
        dh.implied_vol_surface([90, 100], [0.25, 0.5], [[0.2, 0.21], [0.19, 0.18], [0.17, 0.16]])


# ----------------------------- API 路由 / 鉴权 -----------------------------

def test_payoff_endpoint_ok(client):
    r = client.post("/api/deriv/payoff", json={
        "legs": [{"type": "call", "side": "long", "strike": 100, "premium": 5, "qty": 1}],
        "spot_min": 80, "spot_max": 120,
    })
    assert r.status_code == 200
    assert "pnl" in r.json()


def test_surface_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/deriv/vol-surface", json={
        "strikes": [90, 100], "maturities": [0.25], "iv": [[0.2], [0.18]],
    })
    assert r.status_code == 401
