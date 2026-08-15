import numpy as np
import pytest

from app.reports import analytics as rep


def _rets(n=120, seed=1, drift=0.0005, vol=0.01):
    rng = np.random.default_rng(seed)
    return (drift + rng.normal(0, vol, n)).tolist()


def _bench(n=120, seed=2):
    rng = np.random.default_rng(seed)
    return (0.0003 + rng.normal(0, 0.01, n)).tolist()


def test_performance_report_basic():
    r = _rets()
    out = rep.build_performance_report(r)
    assert "performance" in out and "risk" in out
    assert "sharpe" in out["performance"]
    assert "var" in out["risk"]
    assert "max_drawdown" in out["risk"]
    assert out["n_observations"] == 120
    assert isinstance(out["calmar"], (int, float))


def test_performance_report_with_benchmark():
    r = _rets()
    b = _bench()
    out = rep.build_performance_report(r, benchmark=b)
    assert "benchmark" in out
    assert "beta" in out["benchmark"]
    assert "alpha" in out["benchmark"]
    assert "information_ratio" in out["benchmark"]


def test_performance_report_with_equity():
    r = _rets()
    eq = np.cumprod(1 + np.array(r)).tolist()
    out = rep.build_performance_report(r, equity=eq)
    assert "equity_stats" in out
    assert out["equity_stats"]["final"] == pytest.approx(eq[-1], abs=1e-3)


def test_performance_report_too_short():
    with pytest.raises(ValueError):
        rep.build_performance_report([0.01])


def test_compare_reports():
    ra = rep.build_performance_report(_rets(seed=1))
    rb = rep.build_performance_report(_rets(seed=3))
    out = rep.compare_reports(ra, rb, "A", "B")
    assert out["name_a"] == "A"
    assert out["n_metrics"] > 0
    assert "comparisons" in out
    # 每个 comparison 含 delta 与 improved 布尔
    assert "delta" in out["comparisons"][0]
    assert "improved" in out["comparisons"][0]


def test_compare_reports_detects_drawdown_worse_up():
    a = {"risk": {"max_drawdown": -0.1}}
    b = {"risk": {"max_drawdown": -0.2}}
    out = rep.compare_reports(a, b, "A", "B")
    dd = [c for c in out["comparisons"] if c["metric"] == "risk.max_drawdown"][0]
    assert dd["delta"] == 0.1  # b - a
    assert dd["improved"] is True  # B 回撤更深 -> A 更优


def test_multi_compare_ranking():
    curves = {
        "good": [0.01] * 100,                       # 高且稳定正收益 -> sharpe 最高
        "mid": [0.004 if i % 2 == 0 else -0.002 for i in range(100)],  # 温和正
        "bad": [-0.005] * 100,                      # 稳定负 -> sharpe 最低
    }
    out = rep.multi_compare(curves)
    assert out["n_strategies"] == 3
    # 按 sharpe 降序：good 第一、bad 末位
    assert out["ranking_by_sharpe"][0] == "good"
    assert out["ranking_by_sharpe"][-1] == "bad"


def test_multi_compare_empty():
    with pytest.raises(ValueError):
        rep.multi_compare({})


def test_periodic_report_monthly():
    n = 90
    dates = []
    import datetime
    d = datetime.date(2024, 1, 1)
    for _ in range(n):
        dates.append(d.isoformat())
        d += datetime.timedelta(days=1)
    r = _rets(n=n, seed=5)
    out = rep.periodic_report(r, dates, freq="M")
    assert out["freq"] == "M"
    assert out["n_periods"] >= 2
    assert "overall" in out
    # 各期含 sharpe
    assert "sharpe" in out["periods"][0]


def test_periodic_report_quarterly():
    n = 200
    dates = []
    import datetime
    d = datetime.date(2023, 1, 1)
    for _ in range(n):
        dates.append(d.isoformat())
        d += datetime.timedelta(days=1)
    r = _rets(n=n, seed=9)
    out = rep.periodic_report(r, dates, freq="Q")
    assert out["freq"] == "Q"
    assert all(p["period"].startswith("202") and "-Q" in p["period"] for p in out["periods"])


def test_periodic_report_length_mismatch():
    with pytest.raises(ValueError):
        rep.periodic_report([0.01, 0.02], ["2024-01-01"])


def test_risk_dashboard():
    r = _rets()
    out = rep.risk_dashboard(r, benchmark=_bench())
    assert "dashboard" in out
    d = out["dashboard"]
    for k in ("ann_vol", "sharpe", "max_drawdown", "var_pct", "cvar_pct", "calmar", "beta", "correlation"):
        assert k in d


def test_risk_dashboard_with_weights():
    r = _rets()
    w = {"A": 0.4, "B": 0.3, "C": 0.3}
    out = rep.risk_dashboard(r, weights=w)
    assert "concentration" in out["dashboard"]
    assert "hhi" in out["dashboard"]["concentration"]


def test_risk_dashboard_too_short():
    with pytest.raises(ValueError):
        rep.risk_dashboard([0.01])


# ---------- API 冒烟 ----------

def _auth(client):
    u = f"rp_{np.random.default_rng().integers(1e9)}"
    client.post("/api/auth/register", json={"username": u, "password": "P@w0rd123"})
    r = client.post("/api/auth/login", json={"username": u, "password": "P@w0rd123"})
    return r.json()["token"]


def test_api_report_smoke(client):
    tok = _auth(client)
    r = client.post("/api/reports/performance", json={"returns": _rets()}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert "performance" in r.json()


def test_api_compare_smoke(client):
    tok = _auth(client)
    ra = rep.build_performance_report(_rets(seed=1))
    rb = rep.build_performance_report(_rets(seed=2))
    r = client.post("/api/reports/compare", json={"report_a": ra, "report_b": rb}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["n_metrics"] > 0


def test_api_multi_smoke(client):
    tok = _auth(client)
    r = client.post("/api/reports/multi-compare", json={"curves": {"x": _rets(seed=1), "y": _rets(seed=2)}}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["n_strategies"] == 2


def test_api_periodic_smoke(client):
    tok = _auth(client)
    import datetime
    dates = [(datetime.date(2024, 1, 1) + datetime.timedelta(days=i)).isoformat() for i in range(90)]
    r = client.post("/api/reports/periodic", json={"returns": _rets(n=90), "dates": dates, "freq": "M"}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert r.json()["n_periods"] >= 2


def test_api_dashboard_smoke(client):
    tok = _auth(client)
    r = client.post("/api/reports/dashboard", json={"returns": _rets(), "benchmark": _bench()}, headers={"Authorization": f"Bearer {tok}"})
    assert r.status_code == 200
    assert "dashboard" in r.json()


def test_api_reports_requires_auth(anon_client):
    r = anon_client.post("/api/reports/performance", json={"returns": [0.01, 0.02, 0.03]})
    assert r.status_code in (401, 403)
