import numpy as np
import pytest

from app.risk import risk_attrib as ra


def _cov(n=4, seed=1):
    rng = np.random.default_rng(seed)
    A = rng.normal(0, 1, (n, n))
    return (A @ A.T / n + np.eye(n) * 0.01).tolist()


def _w(n, seed=2):
    rng = np.random.default_rng(seed)
    x = rng.uniform(0.1, 1.0, n)
    return (x / x.sum()).tolist()


def _ret_mat(n=4, t=120, seed=3):
    rng = np.random.default_rng(seed)
    return (0.0005 + rng.normal(0, 0.01, (t, n))).tolist()


# ----------------------------- V77 因子风险分解 -----------------------------

def test_factor_risk_decomp_basic():
    B = [[1.0, 0.2], [0.5, 0.8], [0.3, 0.4], [0.9, 0.1]]
    F = [[0.04, 0.01], [0.01, 0.02]]
    out = ra.factor_risk_decomposition([0.25, 0.25, 0.25, 0.25], B, F, factor_names=["Mkt", "Val"])
    assert out["total_variance"] == pytest.approx(out["factor_variance"] + out["specific_variance"])
    assert 0.0 <= out["pct_factor"] <= 1.0 + 1e-9
    assert len(out["factor_contrib"]) == 2
    assert len(out["factor_names"]) == 2


def test_factor_risk_decomp_no_specific():
    B = [[1.0, 0.0], [0.0, 1.0]]
    F = [[0.04, 0.0], [0.0, 0.02]]
    out = ra.factor_risk_decomposition([0.5, 0.5], B, F, specific_var=[0.0, 0.0])
    # 特异性方差显式置 0 时，因子方差 = 总方差，pct_factor = 1
    assert out["specific_variance"] == pytest.approx(0.0, abs=1e-6)
    assert out["pct_factor"] == pytest.approx(1.0, abs=1e-6)


def test_factor_risk_decomp_dim_mismatch():
    with pytest.raises(ValueError):
        ra.factor_risk_decomposition([0.5, 0.5], [[1.0, 0.0], [0.0, 1.0]], [[0.04, 0.0], [0.0, 0.02], [0.0, 0.0]])


# ----------------------------- V78 因子收益归因 -----------------------------

def test_factor_return_attr_basic():
    B = [[1.0, 0.2], [0.5, 0.8], [0.3, 0.4]]
    Fr = [[0.01, 0.0], [0.0, 0.02], [0.005, 0.01]]
    out = ra.factor_return_attribution([0.5, 0.3, 0.2], B, Fr, factor_names=["Mkt", "Val"])
    # 总收益 = 因子贡献和 + 特异性贡献
    assert out["total_return"] == pytest.approx(sum(out["factor_contrib"]) + out["specific_contrib"])
    assert out["n_periods"] == 3
    assert len(out["factor_contrib"]) == 2


def test_factor_return_attr_with_specific():
    B = [[1.0, 0.0], [0.0, 1.0]]
    Fr = [[0.01, 0.0], [0.0, 0.02]]
    out = ra.factor_return_attribution([0.5, 0.5], B, Fr, specific_returns=[0.003, 0.001])
    assert out["specific_contrib"] == pytest.approx(0.5 * 0.003 + 0.5 * 0.001)


def test_factor_return_attr_dim_mismatch():
    with pytest.raises(ValueError):
        ra.factor_return_attribution([0.5, 0.5], [[1.0, 0.0], [0.0, 1.0]], [[0.01]])


# ----------------------------- V79 成分 VaR -----------------------------

def test_component_var_sum_equals_cvar():
    R = _ret_mat(4, 120, seed=5)
    out = ra.component_var(R, weights=[0.25, 0.25, 0.25, 0.25], alpha=0.05)
    # 成分 VaR 之和 = 组合 CVaR
    assert sum(out["component_var"]) == pytest.approx(out["portfolio_cvar"], abs=1e-6)
    assert len(out["component_var"]) == 4
    assert len(out["marginal_var"]) == 4
    assert out["alpha"] == 0.05


def test_component_var_equal_weights():
    # 等权 + 同分布 -> 各成分 VaR 接近（允许采样噪声）
    rng = np.random.default_rng(7)
    R = (0.0005 + rng.normal(0, 0.01, (400, 3))).tolist()
    out = ra.component_var(R)
    assert max(out["component_var"]) - min(out["component_var"]) < 0.01


def test_component_var_bad_alpha():
    with pytest.raises(ValueError):
        ra.component_var([[0.01, 0.02], [0.0, -0.01]], alpha=1.5)


def test_component_var_dim_mismatch():
    with pytest.raises(ValueError):
        ra.component_var([[0.01, 0.02], [0.0, -0.01]], weights=[0.5])


# ----------------------------- V80 风险分解树 -----------------------------

def test_risk_tree_grouping():
    cov = _cov(4, seed=9)
    groups = ["金融", "金融", "科技", "科技"]
    out = ra.risk_decomposition_tree([0.25] * 4, cov, groups)
    # 组内风险贡献之和 = 总和（约 1，因为 RC 归一化和=1）
    grp_sum = sum(out["by_group"].values())
    assert grp_sum == pytest.approx(1.0, abs=1e-6)
    assert set(out["groups"]) == {"金融", "科技"}
    assert len(out["per_asset"]) == 4


def test_risk_tree_rc_sums_to_one():
    cov = _cov(3, seed=4)
    out = ra.risk_decomposition_tree([0.5, 0.3, 0.2], cov, ["A", "B", "A"])
    rc_sum = sum(p["risk_contrib"] for p in out["per_asset"])
    assert rc_sum == pytest.approx(1.0, abs=1e-6)


def test_risk_tree_dim_mismatch():
    with pytest.raises(ValueError):
        ra.risk_decomposition_tree([0.5, 0.5], [[0.04, 0.0], [0.0, 0.03]], ["A", "B", "C"])


# ----------------------------- V81 尾部风险指标 -----------------------------

def test_tail_metrics_basic():
    rng = np.random.default_rng(11)
    r = (0.0006 + rng.normal(0, 0.01, 250)).tolist()
    out = ra.tail_risk_metrics(r)
    assert out["n"] == 250
    assert out["ann_vol"] > 0
    assert out["max_drawdown"] <= 0
    assert out["sortino"] != 0
    assert out["cvar"] <= out["var"]  # CVaR 更极端
    assert out["calmar"] >= 0


def test_tail_metrics_calmar_positive():
    r = [0.001] * 100  # 单调上涨，无回撤
    out = ra.tail_risk_metrics(r)
    assert out["max_drawdown"] == 0.0
    assert out["calmar"] == 0.0  # 代码约定无回撤时 calmar=0


def test_tail_metrics_too_short():
    with pytest.raises(ValueError):
        ra.tail_risk_metrics([0.01])


# ----------------------------- API 路由 / 鉴权 -----------------------------

def test_factor_risk_endpoint_ok(client):
    r = client.post("/api/riskattr/factor-risk", json={
        "weights": [0.25, 0.25, 0.25, 0.25],
        "factor_exposures": [[1.0, 0.2], [0.5, 0.8], [0.3, 0.4], [0.9, 0.1]],
        "factor_cov": [[0.04, 0.01], [0.01, 0.02]],
        "factor_names": ["Mkt", "Val"],
    })
    assert r.status_code == 200
    assert "total_variance" in r.json()


def test_tail_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/riskattr/tail", json={"returns": [0.01, -0.02, 0.005]})
    assert r.status_code == 401
