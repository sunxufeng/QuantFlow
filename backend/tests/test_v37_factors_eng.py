"""V37–V41 因子工程深化测试。"""

import numpy as np
import pytest

from app.factors import engineering as eng


@pytest.fixture
def synth_factors():
    rng = np.random.default_rng(0)
    x1 = rng.normal(size=200)
    x2 = rng.normal(size=200)
    noise = rng.normal(scale=0.1, size=200)
    y = 3.0 * x1 - 2.0 * x2 + noise
    return {"y": y.tolist(), "x1": x1.tolist(), "x2": x2.tolist()}


def test_orthogonalize_factor_removes_redundancy(synth_factors):
    res = eng.orthogonalize_factor("y", synth_factors)
    resid = np.array(res["orthogonal_series"])
    # 残差应与控制变量 x1/x2 近似不相关（冗余已剔除）
    for c in res["controls"]:
        cs = np.array(synth_factors[c])[-len(resid):]
        assert abs(np.corrcoef(resid, cs)[0, 1]) < 0.1
    assert len(resid) == 200


def test_orthogonalize_all_mutually_uncorrelated():
    rng = np.random.default_rng(3)
    fr = {f"f{i}": rng.normal(size=120) for i in range(4)}
    out = eng.orthogonalize_all(fr)
    of = {k: np.array(v) for k, v in out["orthogonal_factors"].items()}
    names = list(of.keys())
    for i in range(len(names)):
        for j in range(i + 1, len(names)):
            corr = np.corrcoef(of[names[i]], of[names[j]])[0, 1]
            assert abs(corr) < 1e-2


def test_factor_timing_returns_sharpe():
    rng = np.random.default_rng(5)
    r = rng.normal(0.001, 0.02, 300)
    res = eng.factor_timing({"mom": r.tolist()}, method="vol", halflife=21)
    assert len(res["weights"]) == 300
    assert abs(res["avg_weight"] - 1.0) < 1e-6
    assert isinstance(res["static_sharpe"], float)
    assert isinstance(res["timed_sharpe"], float)


def test_factor_crowding_bounds():
    rng = np.random.default_rng(7)
    r = rng.normal(0.0005, 0.015, 250)
    res = eng.factor_crowding({"f": r.tolist()}, lags=[1, 2])
    assert 0 <= res["crowding_index"] <= 100
    assert "autocorr_lag1" in res["autocorr"]


def test_combine_factors_equal_weights():
    rng = np.random.default_rng(9)
    fr = {f"f{i}": rng.normal(0.001, 0.01, 200) for i in range(3)}
    res = eng.combine_factors(fr, method="equal")
    assert abs(sum(res["weights"].values()) - 1.0) < 1e-2
    assert len(res["composite_returns"]) == 200
    assert "sharpe" in res["metrics"]


def test_combine_factors_orthogonal_runs():
    rng = np.random.default_rng(11)
    fr = {f"f{i}": rng.normal(0.001, 0.01, 200) for i in range(3)}
    res = eng.combine_factors(fr, method="orthogonal")
    assert res["method"] == "orthogonal"
    assert len(res["composite_returns"]) == 200


def test_factor_turnover_stable_ranks():
    # 两资产序列排序恒定 → 换手率为 0、稳定性为 1
    a = list(range(10, 20))   # 始终更高
    b = list(range(0, 10))    # 始终更低
    res = eng.factor_turnover({"A": a, "B": b})
    assert res["avg_turnover"] == 0.0
    assert res["stability"] == 1.0


def test_api_combine_smoke(client):
    rng = np.random.default_rng(13)
    fr = {f"f{i}": rng.normal(0.001, 0.01, 150).tolist() for i in range(3)}
    resp = client.post("/api/factors/combine", json={"factor_returns": fr, "method": "vol_inverse"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["method"] == "vol_inverse"
    assert len(body["weights"]) == 3
