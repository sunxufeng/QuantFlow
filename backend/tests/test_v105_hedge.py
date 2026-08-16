"""V105 对冲 / 反向交易计算器（移植自 panda reverse_operation 计算内核）。"""
from app.trading.hedge import (
    beta_neutral_hedge,
    reverse_position,
    group_order,
    compute_hedge,
)


def test_beta_neutral_hedge_short_when_portfolio_beta_positive():
    # 组合贝塔 1.11、市值 50 万；用 IF(乘数300, 点位3800) 完全中性对冲 -> 应开空
    res = beta_neutral_hedge(
        portfolio=[
            {"symbol": "600519.SH", "market_value": 300000, "beta": 1.05},
            {"symbol": "000001.SZ", "market_value": 200000, "beta": 1.20},
        ],
        future_price=3800,
        multiplier=300,
        target_beta=0.0,
    )
    assert round(res["portfolio_beta"], 2) == 1.11
    assert res["portfolio_value"] == 500000
    assert res["side"] == "sell"
    # contracts = 1.11 * 500000 / (3800*300) ≈ 0.486 -> 向下取整为 0（不足 1 手）
    assert res["contracts"] == 0
    assert res["residual_beta"] == res["portfolio_beta"]


def test_beta_neutral_hedge_large_portfolio_rounds_up():
    # 放大组合市值到 5000 万 -> contracts ≈ 48.6 -> 取 49 手
    res = beta_neutral_hedge(
        portfolio=[{"symbol": "X.SH", "market_value": 50_000_000, "beta": 1.11}],
        future_price=3800,
        multiplier=300,
    )
    assert res["side"] == "sell"
    assert res["contracts"] == 49
    assert res["hedge_notional"] == 49 * 3800 * 300


def test_beta_neutral_hedge_buy_when_negative_beta():
    # 组合贝塔为负 -> 需开多把贝塔抬到 0
    res = beta_neutral_hedge(
        portfolio=[{"symbol": "X", "market_value": 1_000_000, "beta": -0.5}],
        future_price=3800,
        multiplier=300,
        target_beta=0.0,
    )
    assert res["side"] == "buy"


def test_reverse_position_close():
    res = reverse_position(100, mode="close")
    assert res["order_side"] == "sell"
    assert res["order_qty"] == 100


def test_reverse_position_flip():
    # 多仓 100 -> 反手需卖出 200（平多+开空）
    res = reverse_position(100, mode="flip")
    assert res["order_side"] == "sell"
    assert res["order_qty"] == 200


def test_reverse_position_short_close():
    res = reverse_position(-50, mode="close")
    assert res["order_side"] == "buy"
    assert res["order_qty"] == 50


def test_group_order_basic():
    res = group_order(
        long_dict={"AG2110.SHF": 15},
        short_dict={"MA2105.CZC": 30},
        prices={"AG2110.SHF": 5000, "MA2105.CZC": 2500},
    )
    assert res["long_count"] == 1 and res["short_count"] == 1
    assert res["orders"][0] == {"symbol": "AG2110.SHF", "side": "buy", "qty": 15}
    assert res["orders"][1] == {"symbol": "MA2105.CZC", "side": "sell", "qty": 30}
    assert res["long_notional"] == 75000
    assert res["short_notional"] == 75000
    assert res["net_notional"] == 0


def test_compute_hedge_dispatch_errors():
    import pytest
    with pytest.raises(ValueError):
        compute_hedge({"kind": "unknown"})
    with pytest.raises(ValueError):
        # beta 缺 multiplier
        compute_hedge({"kind": "beta", "portfolio": [], "future_price": 1})


def test_api_hedge_beta(client):
    resp = client.post(
        "/api/trading/hedge",
        json={
            "kind": "beta",
            "portfolio": [{"symbol": "X.SH", "market_value": 50_000_000, "beta": 1.11}],
            "future_price": 3800,
            "multiplier": 300,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "beta"
    assert body["contracts"] == 49


def test_api_hedge_requires_auth(anon_client):
    resp = anon_client.post(
        "/api/trading/hedge",
        json={"kind": "reverse", "current_qty": 100, "mode": "close"},
    )
    assert resp.status_code == 401


def test_api_hedge_group(client):
    resp = client.post(
        "/api/trading/hedge",
        json={"kind": "group", "long_dict": {"A": 10}, "short_dict": {"B": 5}, "prices": {}},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["kind"] == "group"
    assert len(body["orders"]) == 2
