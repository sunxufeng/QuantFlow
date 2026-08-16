import numpy as np
import pytest

from app.monitoring import alerts as ma


# ----------------------------- V87 持仓偏离监控 -----------------------------

def test_drift_flags_and_trades():
    w = [0.4, 0.4, 0.2]
    t = [0.33, 0.33, 0.34]
    out = ma.drift_monitor(w, t, asset_names=["A", "B", "C"], threshold=0.05)
    assert out["n_flagged"] == 3
    assert len(out["trades"]) == 3
    assert sum(d["weight_delta"] for d in out["trades"]) == pytest.approx(0.0)


def test_drift_no_flag():
    w = [0.34, 0.33, 0.33]
    t = [0.33, 0.33, 0.34]
    out = ma.drift_monitor(w, t, threshold=0.05)
    assert out["n_flagged"] == 0


def test_drift_dim_mismatch():
    with pytest.raises(ValueError):
        ma.drift_monitor([0.5, 0.5], [0.33, 0.33, 0.34])


def test_drift_not_normalized():
    with pytest.raises(ValueError):
        ma.drift_monitor([0.5, 0.4], [0.6, 0.4])


# ----------------------------- V88 收益质量监控 -----------------------------

def test_return_quality_flags_low_hitrate():
    rng = np.random.default_rng(3)
    r = rng.normal(-0.001, 0.01, 100)  # 负漂移 -> 低胜率
    out = ma.return_quality_monitor(r.tolist(), hit_rate_limit=0.45)
    assert 0 <= out["hit_rate"] <= 1
    assert out["max_win_streak"] >= 0
    assert isinstance(out["payoff_ratio"], float)


def test_return_quality_payoff_ratio():
    r = [0.02, 0.02, -0.01, -0.01, -0.01]  # 胜率 0.4, 盈亏比 2/3
    out = ma.return_quality_monitor(r)
    assert out["hit_rate"] == pytest.approx(0.4)
    assert out["payoff_ratio"] == pytest.approx(2.0)


def test_return_quality_short():
    with pytest.raises(ValueError):
        ma.return_quality_monitor([0.01])


# ----------------------------- V89 跟踪误差监控 -----------------------------

def test_tracking_error_detects_breach():
    rng = np.random.default_rng(2)
    rb = rng.normal(0.0005, 0.01, 60)
    rp = rb.copy()
    rp[40:] = rb[40:] + 0.02
    out = ma.tracking_error_monitor(rp.tolist(), rb.tolist(), window=20, limit=0.05)
    assert out["n_breaches"] >= 1
    assert out["max_te"] >= out["mean_te"]


def test_tracking_error_dim():
    with pytest.raises(ValueError):
        ma.tracking_error_monitor([0.01, 0.02], [0.01])


# ----------------------------- V90 行业敞口监控 -----------------------------

def test_sector_exposure_breach():
    gw = {"金融": 0.7, "科技": 0.2, "消费": 0.1}
    out = ma.sector_exposure_monitor(gw, limit=0.6)
    assert out["over_limit"] == {"金融": 0.7}
    assert len(out["breaches"]) == 1
    assert out["max_exposure"] == 0.7


def test_sector_exposure_clean():
    gw = {"金融": 0.5, "科技": 0.3, "消费": 0.2}
    out = ma.sector_exposure_monitor(gw, limit=0.6)
    assert out["breaches"] == []


def test_sector_exposure_not_normalized():
    with pytest.raises(ValueError):
        ma.sector_exposure_monitor({"A": 0.5, "B": 0.4})


# ----------------------------- V91 风险预算监控 -----------------------------

def test_risk_budget_percent_sum_to_one():
    w = [0.5, 0.5]
    cov = [[0.04, 0.01], [0.01, 0.02]]
    out = ma.risk_budget_monitor(w, cov)
    assert sum(out["risk_contrib_pct"]) == pytest.approx(1.0, abs=1e-9)


def test_risk_budget_deviation_flag():
    w = [0.5, 0.5]
    cov = [[0.04, 0.0], [0.0, 0.0001]]
    out = ma.risk_budget_monitor(w, cov, target_budget=[0.5, 0.5])
    assert out["max_deviation"] > 0.1
    assert len(out["breaches"]) >= 1


def test_risk_budget_dim_mismatch():
    with pytest.raises(ValueError):
        ma.risk_budget_monitor([0.5, 0.5], [[0.04, 0.01]])


# ----------------------------- API 路由 / 鉴权 -----------------------------

def test_drift_endpoint_ok(client):
    r = client.post("/api/monalert/drift", json={
        "weights": [0.4, 0.4, 0.2], "target": [0.33, 0.33, 0.34], "threshold": 0.05,
    })
    assert r.status_code == 200
    assert r.json()["n_flagged"] == 3


def test_budget_endpoint_requires_auth(anon_client):
    r = anon_client.post("/api/monalert/risk-budget", json={"weights": [0.5, 0.5], "cov": [[0.04, 0.01], [0.01, 0.02]]})
    assert r.status_code == 401
