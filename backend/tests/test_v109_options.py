"""V109 期权定价与希腊值计算器测试。"""

import math
import pytest
from app.trading.options import (
    bs_price,
    bs_greeks,
    implied_vol,
    compute_options,
    InvalidOptionInput,
)


def test_bs_call_put_parity():
    # 看涨 + 看跌 = 标的价格 - 行权价贴现（看跌看涨平价）
    s, k, t, r, sigma = 100.0, 100.0, 1.0, 0.05, 0.2
    c = bs_price(s, k, t, r, sigma, "call")
    p = bs_price(s, k, t, r, sigma, "put")
    parity = c - p
    expected = s - k * math.exp(-r * t)
    assert abs(parity - expected) < 1e-6


def test_bs_call_known_value():
    # S=100 K=100 T=1 r=5% sigma=20% -> call ~= 10.4506
    c = bs_price(100.0, 100.0, 1.0, 0.05, 0.2, "call")
    assert abs(c - 10.4506) < 1e-3


def test_bs_put_known_value():
    p = bs_price(100.0, 100.0, 1.0, 0.05, 0.2, "put")
    assert abs(p - 5.5735) < 1e-3


def test_greeks_call_delta_in_range():
    g = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.2, "call")
    assert 0 < g["delta"] < 1
    # 平值看涨 delta ~ 0.6368
    assert abs(g["delta"] - 0.6368) < 1e-2
    assert g["gamma"] > 0
    assert g["vega"] > 0
    assert g["theta"] < 0  # 看涨 theta 为负
    # 友好单位一致性
    assert abs(g["vega_per_1pct"] * 100 - g["vega"]) < 1e-6
    assert abs(g["theta_per_day"] * 365 - g["theta"]) < 1e-6


def test_put_delta_negative():
    g = bs_greeks(100.0, 100.0, 1.0, 0.05, 0.2, "put")
    assert -1 < g["delta"] < 0


def test_expired_option_intrinsic():
    # T=0：内在价值，希腊值退化
    assert abs(bs_price(110.0, 100.0, 0.0, 0.05, 0.2, "call") - 10.0) < 1e-9
    assert abs(bs_price(90.0, 100.0, 0.0, 0.05, 0.2, "put") - 10.0) < 1e-9
    g = bs_greeks(110.0, 100.0, 0.0, 0.05, 0.2, "call")
    assert g["gamma"] == 0.0 and g["vega"] == 0.0


def test_implied_vol_recovers_sigma():
    s, k, t, r, sigma = 100.0, 100.0, 0.5, 0.03, 0.25
    price = bs_price(s, k, t, r, sigma, "call")
    iv = implied_vol(price, s, k, t, r, "call")
    assert iv is not None
    assert abs(iv - sigma) < 1e-4


def test_implied_vol_below_intrinsic_returns_none():
    # 实值看涨：内在价值 = S-K = 20，市价 1.0 低于内在价值 -> 无套利解
    iv = implied_vol(1.0, 100.0, 80.0, 1.0, 0.05, "call")
    assert iv is None


def test_invalid_inputs():
    with pytest.raises(InvalidOptionInput):
        bs_price(-1, 100, 1, 0.05, 0.2, "call")
    with pytest.raises(InvalidOptionInput):
        bs_price(100, 100, 1, 0.05, 0.2, "bad")


def test_compute_options_structure():
    out = compute_options(100.0, 100.0, 1.0, 0.05, 0.2, "call", market_price=10.5)
    assert "price" in out and "greeks" in out
    assert out["option_type"] == "call"
    assert out["implied_volatility"] is not None
    assert abs(out["implied_volatility"] - 0.2) < 1e-2


def test_api_options_calc(client):
    resp = client.post(
        "/api/trading/options_calc",
        json={"spot": 100, "strike": 100, "maturity": 1.0,
              "rate": 0.05, "volatility": 0.2, "option_type": "call"},
    )
    assert resp.status_code == 200
    data = resp.json()
    assert abs(data["price"] - 10.4506) < 1e-2
    assert "delta" in data["greeks"]


def test_api_options_invalid(client):
    resp = client.post(
        "/api/trading/options_calc",
        json={"spot": 100, "strike": 100, "maturity": 1.0,
              "rate": 0.05, "volatility": -0.2, "option_type": "call"},
    )
    assert resp.status_code == 400
