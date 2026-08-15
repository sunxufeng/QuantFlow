import numpy as np
import pytest

from app.portfolio import portfolio_i as pi


# ----------------------------- API 路由 / 鉴权 -----------------------------

def test_aggregate_endpoint_ok(client):
    payload = {"accounts": [
        {"name": "主", "positions": {"股票A": 6000, "债券B": 4000}},
        {"name": "子", "positions": [{"asset": "股票A", "value": 2000}, {"asset": "黄金C", "value": 3000}]},
    ]}
    r = client.post("/api/portfolioi/aggregate", json=payload)
    assert r.status_code == 200
    assert r.json()["total_value"] == pytest.approx(15000)


def test_aggregate_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/portfolioi/aggregate", json={"accounts": [{"name": "A", "positions": {"x": 1}}]})
    assert r.status_code == 401


def test_rebalance_endpoint_constraint(client):
    payload = {
        "current_weights": [0.5, 0.5, 0.0],
        "target_weights": [0.0, 0.0, 1.0],
        "turnover_limit": 0.4,
    }
    r = client.post("/api/portfolioi/rebalance", json=payload)
    assert r.status_code == 200
    assert r.json()["constrained"] is True



def _cov(n=3, seed=1):
    rng = np.random.default_rng(seed)
    A = rng.normal(0, 1, (n, n))
    return (A @ A.T / n + np.eye(n) * 0.01).tolist()


def _w(n, seed=2):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.1, 1.0, n)
    return (x / x.sum()).tolist()


# ----------------------------- V72 Black-Litterman -----------------------------

def test_bl_no_views_returns_equilibrium():
    cov = _cov(3)
    out = pi.black_litterman(cov, asset_names=["A", "B", "C"])
    assert out["views_processed"] == 0
    # 无观点：后验收益 == 均衡收益
    assert out["posterior_returns"] == pytest.approx(out["equilibrium_returns"])
    # 组合权重接近等权（无观点时反优化回均衡权重）
    assert sum(out["bl_weights"]) == pytest.approx(1.0)
    assert all(w >= 0 for w in out["bl_weights"])


def test_bl_with_view_shifts_returns():
    cov = _cov(3, seed=5)
    q = 0.10
    out = pi.black_litterman(
        cov,
        views=[{"assets": [0], "q": q, "confidence": 0.9}],
        asset_names=["A", "B", "C"],
    )
    assert out["views_processed"] == 1
    # 单一资产看涨观点下，后验收益应为均衡收益与观点值之间的插值（同向移动）
    pi0 = out["equilibrium_returns"][0]
    post0 = out["posterior_returns"][0]
    lo, hi = sorted([pi0, q])
    assert lo - 1e-9 <= post0 <= hi + 1e-9
    assert sum(out["bl_weights"]) == pytest.approx(1.0)
    assert all(w >= 0 for w in out["bl_weights"])


def test_bl_relative_view():
    cov = _cov(4, seed=3)
    out = pi.black_litterman(
        cov,
        views=[{"assets": [0, 1], "coefs": [1.0, -1.0], "q": 0.05, "confidence": 0.7}],
        asset_names=[f"X{i}" for i in range(4)],
    )
    assert out["views_processed"] == 1
    assert len(out["bl_weights"]) == 4


def test_bl_bad_confidence():
    with pytest.raises(ValueError):
        pi.black_litterman(_cov(2), views=[{"assets": [0], "q": 0.1, "confidence": 1.5}])


def test_bl_dim_mismatch():
    with pytest.raises(ValueError):
        pi.black_litterman([[0.1, 0.0], [0.0, 0.1]], prior_weights=[0.5, 0.3, 0.2])


# ----------------------------- V73 因子组合构建 -----------------------------

def test_factor_neutral_achieves_target():
    # 3 资产 × 2 因子，目标中性（与基准相同）
    B = [[1.0, 0.2], [0.5, 0.8], [0.3, 0.4]]
    out = pi.factor_portfolio(B, base_weights=[0.5, 0.3, 0.2], method="neutral")
    assert out["method"] == "neutral"
    assert len(out["new_weights"]) == 3
    assert sum(out["new_weights"]) == pytest.approx(1.0)
    # 主动权重和为 0
    assert sum(out["active_weights"]) == pytest.approx(0.0, abs=1e-6)


def test_factor_tilt_towards_target():
    B = [[1.0, 0.0], [0.0, 1.0], [0.5, 0.5]]
    out = pi.factor_portfolio(B, target_bets=[1.0, 0.0], base_weights=[1/3, 1/3, 1/3])
    achieved = out["achieved_exposure"]
    # 倾斜第一个因子 -> 资产 0 权重应上升
    assert out["new_weights"][0] > 1/3


def test_factor_tracking_error():
    B = [[1.0, 0.2], [0.5, 0.8], [0.3, 0.4]]
    cov = _cov(3, seed=11)
    out = pi.factor_portfolio(B, cov=cov, base_weights=[0.5, 0.3, 0.2])
    assert out["tracking_error"] is not None
    assert out["tracking_error"] >= 0


def test_factor_long_only_clip():
    B = [[1.0, 0.0], [0.0, 1.0]]
    out = pi.factor_portfolio(B, target_bets=[-1.0, 1.0], base_weights=[0.5, 0.5], long_only=True)
    assert all(w >= -1e-9 for w in out["new_weights"])


def test_factor_dim_mismatch():
    with pytest.raises(ValueError):
        pi.factor_portfolio([[1.0, 0.2], [0.5, 0.8]], target_bets=[1.0, 0.0, 0.5])


# ----------------------------- V74 组合压力测试 -----------------------------

def test_stress_preset_scenario():
    w = [0.5, 0.2, 0.3]
    names = ["股票A", "债券B", "黄金C"]
    out = pi.stress_test(w, asset_names=names, scenario="gfc_2008")
    assert out["scenario"] == "gfc_2008"
    # 权益 -50% 主导 -> 组合显著负
    assert out["portfolio_pnl_pct"] < 0
    assert out["worst_asset"] == "股票A"
    assert out["best_asset"] == "黄金C"
    assert abs(sum(out["per_asset_pnl"].values()) - out["portfolio_pnl_pct"]) < 1e-9


def test_stress_custom_shocks():
    w = [0.5, 0.5]
    out = pi.stress_test(w, asset_names=["x", "y"], shocks={"x": -0.1, "y": 0.2})
    assert out["portfolio_pnl_pct"] == pytest.approx(0.05)


def test_stress_factor_shock():
    w = [0.6, 0.4]
    B = [[1.0, 0.0], [0.0, 1.0]]
    out = pi.stress_test(w, asset_names=["a", "b"], factor_exposures=B, factor_shocks={"factor_0": -0.2})
    assert out["scenario"] == "factor_shock"
    assert out["portfolio_pnl_pct"] == pytest.approx(-0.12)


def test_stress_unknown_scenario():
    with pytest.raises(ValueError):
        pi.stress_test([1.0], asset_names=["a"], scenario="doom")


def test_stress_no_input():
    with pytest.raises(ValueError):
        pi.stress_test([1.0], asset_names=["a"])


# ----------------------------- V75 带约束再平衡 -----------------------------

def test_rebalance_basic():
    cur = [0.5, 0.3, 0.2]
    tgt = [0.4, 0.4, 0.2]
    out = pi.constrained_rebalance(cur, tgt)
    assert out["n_trades"] == 2
    assert out["adjusted_weights"] == pytest.approx(tgt, abs=1e-6)
    assert out["turnover"] == pytest.approx(0.2)


def test_rebalance_turnover_limit():
    cur = [0.5, 0.5, 0.0]
    tgt = [0.0, 0.0, 1.0]
    out = pi.constrained_rebalance(cur, tgt, turnover_limit=0.4)
    assert out["constrained"] is True
    assert out["turnover"] <= 0.4 + 1e-6
    assert sum(out["adjusted_weights"]) == pytest.approx(1.0)


def test_rebalance_no_trade_band():
    cur = [0.5, 0.5]
    tgt = [0.52, 0.48]
    out = pi.constrained_rebalance(cur, tgt, no_trade_band=0.05)
    # 漂移在带内 -> 不交易
    assert out["n_trades"] == 0
    assert out["adjusted_weights"] == pytest.approx(cur)


def test_rebalance_min_trade():
    cur = [0.5, 0.5]
    tgt = [0.51, 0.49]
    out = pi.constrained_rebalance(cur, tgt, min_trade=0.03)
    assert out["n_trades"] == 0


def test_rebalance_max_weight():
    cur = [0.3, 0.3, 0.4]
    tgt = [0.8, 0.1, 0.1]
    out = pi.constrained_rebalance(cur, tgt, max_weight=0.5)
    assert max(out["adjusted_weights"]) <= 0.5 + 1e-6


def test_rebalance_dim_mismatch():
    with pytest.raises(ValueError):
        pi.constrained_rebalance([0.5, 0.5], [1.0, 0.0, 0.0])


# ----------------------------- V76 多账户聚合 -----------------------------

def test_aggregate_basic():
    accounts = [
        {"name": "主账户", "positions": {"股票A": 6000, "债券B": 4000}},
        {"name": "子账户", "positions": [{"asset": "股票A", "value": 2000}, {"asset": "黄金C", "value": 3000}]},
    ]
    out = pi.aggregate_accounts(accounts)
    assert out["total_value"] == pytest.approx(15000)
    assert out["n_accounts"] == 2
    assert out["n_assets"] == 3
    # 股票A 合并市值 8000
    assert out["asset_values"]["股票A"] == pytest.approx(8000)
    assert out["asset_weights"]["股票A"] == pytest.approx(8000 / 15000)


def test_aggregate_with_cash():
    accounts = [
        {"name": "A", "positions": {"股票": 7000}, "cash": 3000},
    ]
    out = pi.aggregate_accounts(accounts)
    assert out["total_value"] == pytest.approx(10000)
    assert out["asset_weights"]["现金"] == pytest.approx(0.3)


def test_aggregate_account_weights_sum_one():
    accounts = [
        {"name": "A", "positions": {"x": 500}},
        {"name": "B", "positions": {"y": 500}},
    ]
    out = pi.aggregate_accounts(accounts)
    assert sum(out["account_weights"].values()) == pytest.approx(1.0)


def test_aggregate_hhi_in_range():
    accounts = [{"name": "A", "positions": {"x": 500, "y": 500}}]
    out = pi.aggregate_accounts(accounts)
    # 两等权资产 -> HHI = 0.5
    assert out["concentration_hhi"] == pytest.approx(0.5)


def test_aggregate_empty():
    with pytest.raises(ValueError):
        pi.aggregate_accounts([])


def test_aggregate_zero_value():
    with pytest.raises(ValueError):
        pi.aggregate_accounts([{"name": "A", "positions": {"x": 0}}])
