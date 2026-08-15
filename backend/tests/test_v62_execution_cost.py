import numpy as np
import pytest

from app.execution import cost as ec


def test_transaction_cost_basic():
    trades = [
        {"price": 10.0, "shares": 1000, "side": "buy"},
        {"price": 11.0, "shares": 500, "side": "sell"},
    ]
    out = ec.transaction_cost(trades)
    assert out["n_trades"] == 2
    assert out["total_notional"] == 1000 * 10 + 500 * 11
    assert out["total_cost"] > 0
    assert 0 < out["total_cost_pct"] < 0.05
    # 卖出含印花税
    sell = out["details"][1]
    assert sell["stamp_tax"] > 0
    buy = out["details"][0]
    assert buy["stamp_tax"] == 0
    assert abs(sum(out["components"].values()) - out["total_cost"]) < 1e-6


def test_transaction_cost_min_commission():
    out = ec.transaction_cost([{"price": 1.0, "shares": 10, "side": "buy"}])
    # 成交额 10，rate 0.0003 -> 0.003 < min 5 -> 取 5
    assert out["details"][0]["commission"] == 5.0


def test_transaction_cost_empty():
    with pytest.raises(ValueError):
        ec.transaction_cost([])


def test_market_impact_basic():
    out = ec.market_impact(shares=50000, price=20.0, adv=1_000_000, volatility=0.02)
    assert out["turnover"] == 0.05
    assert out["temporary_impact_pct"] > 0
    assert out["permanent_impact_pct"] > 0
    assert out["impact_cost"] > 0
    assert out["liquidation_days"] > 0


def test_market_impact_participation_bounds():
    with pytest.raises(ValueError):
        ec.market_impact(100, 10, 1000, 0.02, participation=0)
    with pytest.raises(ValueError):
        ec.market_impact(100, 10, 1000, 0.02, participation=2)


def test_market_impact_larger_trade_more_cost():
    small = ec.market_impact(10000, 20, 1_000_000, 0.02)
    big = ec.market_impact(200000, 20, 1_000_000, 0.02)
    assert big["total_impact_pct"] > small["total_impact_pct"]


def test_twap_schedule():
    out = ec.twap_schedule(parent_qty=1000, n_slices=5, interval_seconds=60)
    assert out["n_slices"] == 5
    assert len(out["children"]) == 5
    assert all(abs(c["qty"] - 200) < 1e-6 for c in out["children"])
    assert out["total_seconds"] == 300
    assert out["children"][-1]["end_sec"] == 300


def test_twap_invalid():
    with pytest.raises(ValueError):
        ec.twap_schedule(0, 5)
    with pytest.raises(ValueError):
        ec.twap_schedule(100, 0)


def test_vwap_schedule_default_profile():
    out = ec.vwap_schedule(parent_qty=600, n_slices=6)
    assert len(out["children"]) == 6
    total_qty = sum(c["qty"] for c in out["children"])
    assert abs(total_qty - 600) < 1e-6
    # 权重和=1
    assert abs(sum(out["weights"]) - 1.0) < 1e-9


def test_vwap_schedule_custom_profile():
    out = ec.vwap_schedule(parent_qty=100, n_slices=3, volume_profile=[1, 2, 1])
    weights = out["weights"]
    assert abs(weights[1] - 0.5) < 1e-9
    assert abs(weights[0] - 0.25) < 1e-9


def test_vwap_profile_length_mismatch():
    with pytest.raises(ValueError):
        ec.vwap_schedule(100, n_slices=4, volume_profile=[1, 2, 1])


def test_slippage_attribution_buy():
    out = ec.slippage_attribution(arrival_mid=100.0, fill_price=100.2, side="buy", shares=1000, fee_bps=3.0, impact_bps=10.0)
    # 买入 fill>arrival -> 正滑点
    assert out["total_slippage_bps"] == pytest.approx(20.0, abs=1e-6)
    assert out["fee_bps"] == 3.0
    assert out["impact_bps"] == 10.0


def test_slippage_attribution_sell_sign():
    buy = ec.slippage_attribution(100.0, 100.2, "buy", 1000)
    sell = ec.slippage_attribution(100.0, 100.2, "sell", 1000)
    assert sell["total_slippage_bps"] == -buy["total_slippage_bps"]


def test_slippage_with_vwap():
    out = ec.slippage_attribution(
        arrival_mid=100.0, fill_price=100.2, side="buy", shares=1000,
        vwap_benchmark=99.8, impact_bps=10.0, fee_bps=3.0,
    )
    # 择时 = (100-99.8)/99.8*1e4 ≈ 20.04
    assert out["timing_bps"] > 0
    # 残差 = 总 - 择时 - 冲击 - 费
    assert abs(out["residual_bps"] - (out["total_slippage_bps"] - out["timing_bps"] - out["impact_bps"] - out["fee_bps"])) < 1e-6


# ---------- API 冒烟 ----------

def _auth(client):
    u = f"ex_{np.random.default_rng().integers(1e9)}"
    client.post("/api/auth/register", json={"username": u, "password": "P@w0rd123"})
    r = client.post("/api/auth/login", json={"username": u, "password": "P@w0rd123"})
    return r.json()["token"]


def test_api_cost_smoke(client):
    tok = _auth(client)
    r = client.post("/api/execution/cost", json={
        "trades": [{"price": 10, "shares": 1000, "side": "buy"}, {"price": 11, "shares": 500, "side": "sell"}]
    }, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["n_trades"] == 2


def test_api_impact_smoke(client):
    tok = _auth(client)
    r = client.post("/api/execution/impact", json={"shares": 50000, "price": 20, "adv": 1_000_000, "volatility": 0.02}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["turnover"] == 0.05


def test_api_twap_smoke(client):
    tok = _auth(client)
    r = client.post("/api/execution/twap", json={"parent_qty": 1000, "n_slices": 4}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert len(r.json()["children"]) == 4


def test_api_vwap_smoke(client):
    tok = _auth(client)
    r = client.post("/api/execution/vwap", json={"parent_qty": 600, "n_slices": 6}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert len(r.json()["children"]) == 6


def test_api_slippage_smoke(client):
    tok = _auth(client)
    r = client.post("/api/execution/slippage", json={"arrival_mid": 100, "fill_price": 100.2, "side": "buy", "shares": 1000}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["total_slippage_bps"] == 20.0


def test_api_execution_requires_auth(anon_client):
    r = anon_client.post("/api/execution/cost", json={"trades": [{"price": 10, "shares": 100, "side": "buy"}]})
    assert r.status_code in (401, 403)
