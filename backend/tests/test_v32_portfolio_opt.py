"""V32–V36 组合优化增强测试。

覆盖：风险平价(ERC)/最大分散化/层次风险平价/再平衡引擎/风格因子暴露归因。
纯函数直接验证数学性质；另含一个 API 冒烟测试确认路由装配。
"""

import numpy as np
import pytest

from app.portfolio import optimize_ext as opt


@pytest.fixture
def sample_cov():
    # 3 资产，构造一个正定协方差
    rng = np.random.default_rng(42)
    A = rng.normal(size=(3, 3))
    return A @ A.T + np.eye(3) * 0.1


def test_risk_parity_equal_contributions(sample_cov):
    w = opt.risk_parity_weights(sample_cov)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= 0).all()
    rc = opt.risk_contributions(w, sample_cov)
    # 各资产风险贡献应近似相等
    assert rc.max() - rc.min() < 0.02


def test_risk_parity_with_budgets():
    cov = np.array([[0.04, 0.001], [0.001, 0.01]])
    w = opt.risk_parity_weights(cov, budgets=[0.75, 0.25])
    rc = opt.risk_contributions(w, cov)
    assert abs(rc[0] / rc[1] - 3.0) < 0.05


def test_max_diversification_weights(sample_cov):
    w = opt.max_diversification_weights(sample_cov)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= 0).all()
    dr = opt.diversification_ratio(w, sample_cov)
    # 最大分散化比率应不低于等权组合
    we = np.ones(3) / 3
    assert dr >= opt.diversification_ratio(we, sample_cov) - 1e-6


def test_hrp_weights_sum_one():
    cov = np.array([
        [0.04, 0.02, 0.01, 0.0],
        [0.02, 0.05, 0.01, 0.0],
        [0.01, 0.01, 0.03, 0.02],
        [0.0, 0.0, 0.02, 0.06],
    ])
    w = opt.hierarchical_risk_parity(cov)
    assert abs(w.sum() - 1.0) < 1e-6
    assert (w >= 0).all()
    assert w.shape[0] == 4


def test_rebalance_generates_trades_for_breach():
    plan = opt.rebalance_plan(
        current_weights={"A": 0.5, "B": 0.3, "C": 0.2},
        target_weights={"A": 0.33, "B": 0.33, "C": 0.34},
        threshold=0.0,
        base_value=1_000_000,
    )
    assert plan["n_breached"] == 3
    assert len(plan["trades"]) == 3
    # A 当前高于目标→卖出；B/C 当前低于目标→买入
    sides = {t["asset"]: t["side"] for t in plan["trades"]}
    assert sides["A"] == "sell"
    assert sides["B"] == "buy"
    assert sides["C"] == "buy"
    # 净现金应接近 0
    assert abs(plan["summary"]["net_cash"]) < 1.0


def test_rebalance_respects_threshold_band():
    plan = opt.rebalance_plan(
        current_weights={"A": 0.34, "B": 0.33, "C": 0.33},
        target_weights={"A": 0.33, "B": 0.33, "C": 0.34},
        threshold=0.05,
    )
    # 所有漂移 < 0.05，不应产生交易
    assert plan["n_breached"] == 0
    assert plan["trades"] == []


def test_style_exposure_computation():
    res = opt.style_exposure(
        weights={"A": 0.6, "B": 0.4},
        factor_betas={
            "A": {"value": 1.0, "growth": -0.5, "size": 0.2, "momentum": 0.3, "volatility": -0.1},
            "B": {"value": -0.4, "growth": 0.8, "size": -0.3, "momentum": 0.1, "volatility": 0.5},
        },
    )
    assert abs(sum(res["portfolio_exposure"].values()))  # 仅类型健全
    # 组合价值暴露 = 0.6*1.0 + 0.4*(-0.4) = 0.44
    assert abs(res["portfolio_exposure"]["value"] - 0.44) < 1e-6
    assert set(res["factors"]) == {"value", "growth", "size", "momentum", "volatility"}


def test_resolve_returns_synthetic():
    assets, R = opt.resolve_returns(
        universe=["X1", "X2", "X3"], start="2023-01-01", end="2023-03-31", seed=7
    )
    assert len(assets) == 3
    assert R.ndim == 2 and R.shape[1] == 3
    assert R.shape[0] > 10


def test_api_risk_parity_smoke(client):
    resp = client.post(
        "/api/portfolio/risk-parity",
        json={"universe": ["A1", "A2", "A3", "A4"], "start": "2023-01-01", "end": "2023-06-30", "seed": 11},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert len(body["weights"]) == 4
    assert abs(sum(w["weight"] for w in body["weights"]) - 1.0) < 1e-6
    # 等波动合成资产 → 风险贡献应接近相等
    rc = body["risk_contributions"]
    assert max(rc) - min(rc) < 0.05
