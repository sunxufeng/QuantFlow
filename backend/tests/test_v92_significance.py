import numpy as np
import pytest

from app.backtest import significance as sig


# ----------------------------- V92 Deflated Sharpe -----------------------------

def test_deflated_reduces_with_trials():
    base = sig.deflated_sharpe_ratio(1.5, 250, n_trials=1)
    multi = sig.deflated_sharpe_ratio(1.5, 250, n_trials=100)
    # 多次检验使 deflated 更低
    assert multi["deflated_sharpe"] < base["deflated_sharpe"]
    assert multi["p_lucky"] > base["p_lucky"]
    assert base["expected_max_sr"] == 0.0


def test_deflated_single_trial_value():
    out = sig.deflated_sharpe_ratio(2.0, 250, n_trials=1)
    assert out["deflated_sharpe"] == pytest.approx(2.0, abs=1e-6)
    # 强正夏普 + 单次检验 → 几乎不可能归因于运气
    assert out["p_lucky"] < 0.01


def test_deflated_bad_n():
    with pytest.raises(ValueError):
        sig.deflated_sharpe_ratio(1.0, 0)


# ----------------------------- V93 Probabilistic Sharpe -----------------------------

def test_psr_positive_sharpe():
    out = sig.probabilistic_sharpe_ratio(1.5, 250, target_sr=0.0)
    assert out["prob"] > 0.5
    # 目标越高概率越低
    low = sig.probabilistic_sharpe_ratio(1.5, 250, target_sr=0.0)
    high = sig.probabilistic_sharpe_ratio(1.5, 250, target_sr=1.0)
    assert high["prob"] < low["prob"]


def test_psr_target_equals_sharpe():
    out = sig.probabilistic_sharpe_ratio(1.0, 250, target_sr=1.0)
    assert out["prob"] == pytest.approx(0.5, abs=1e-6)


def test_psr_bad_n():
    with pytest.raises(ValueError):
        sig.probabilistic_sharpe_ratio(1.0, 0)


# ----------------------------- V94 策略容量 -----------------------------

def test_capacity_scales_with_adv():
    small = sig.strategy_capacity(adv=1e6, participation=0.1, annual_turnover=2.0)
    big = sig.strategy_capacity(adv=1e9, participation=0.1, annual_turnover=2.0)
    assert big["capacity"] == pytest.approx(1000 * small["capacity"])
    assert small["annual_tradable"] == pytest.approx(1e6 * 0.1 * 252)


def test_capacity_bad_inputs():
    with pytest.raises(ValueError):
        sig.strategy_capacity(adv=0)


# ----------------------------- V95 状态条件收益统计 -----------------------------

def test_regime_stats_splits():
    rng = np.random.default_rng(4)
    r = rng.normal(0.001, 0.01, 100)
    lab = ["bull" if x > 0.001 else "bear" for x in r]
    out = sig.regime_conditional_stats(r.tolist(), lab)
    assert set(out["per_regime"].keys()) == {"bull", "bear"}
    total_n = sum(v["n"] for v in out["per_regime"].values())
    assert total_n == 100


def test_regime_stats_dim_mismatch():
    with pytest.raises(ValueError):
        sig.regime_conditional_stats([0.01, 0.02], ["a"])


# ----------------------------- V96 策略分散度 -----------------------------

def test_diversification_perfect_corr():
    # 非恒定、完全正相关
    curves = {"A": [1, 2, 4, 3, 5], "B": [1, 2, 4, 3, 5]}
    out = sig.strategy_diversification(curves)
    assert out["avg_correlation"] == pytest.approx(1.0, abs=1e-6)
    assert out["effective_strategies"] == pytest.approx(1.0, abs=1e-6)


def test_diversification_zero_corr():
    # 非恒定、完全负相关（收益互为相反数）
    curves = {"A": [1, 2, 4, 3, 5], "B": [1, 0, -2, -1, -3]}
    out = sig.strategy_diversification(curves)
    assert out["avg_correlation"] == pytest.approx(-1.0, abs=1e-6)
    # 完全反向：k=2 → 2/(1+1*(-1)) = 2/0 → 上限为 k
    assert out["effective_strategies"] == pytest.approx(2.0, abs=1e-6)


def test_diversification_uncorrelated():
    curves = {"A": [1, 2, 1, 2, 1], "B": [1, 1, 2, 1, 2]}
    out = sig.strategy_diversification(curves)
    # 弱相关时应接近 2
    assert out["effective_strategies"] > 1.0


def test_diversification_too_few():
    with pytest.raises(ValueError):
        sig.strategy_diversification({"A": [1, 2, 3]})


# ----------------------------- API 路由 / 鉴权 -----------------------------

def test_deflated_endpoint_ok(client):
    r = client.post("/api/sig/deflated-sharpe", json={"sharpe": 1.5, "n_obs": 250, "n_trials": 10})
    assert r.status_code == 200
    assert "deflated_sharpe" in r.json()


def test_capacity_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/sig/capacity", json={"adv": 1e6})
    assert r.status_code == 401
