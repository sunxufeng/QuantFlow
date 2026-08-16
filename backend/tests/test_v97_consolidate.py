"""V97 综合报告聚合器测试。"""

from app.reports.consolidate import consolidate_report


def _rets(n=120, seed=1):
    import random
    r = random.Random(seed)
    return [round(0.0006 + (r.random() - 0.5) * 0.02, 6) for _ in range(n)]


def test_consolidate_keys():
    out = consolidate_report(_rets())
    assert set(["params", "summary", "performance", "risk", "dashboard", "export_sections"]).issubset(out.keys())
    assert out["params"]["n_observations"] == 120
    assert "年化收益" in out["summary"]
    assert out["dashboard"]["sharpe"] == out["performance"]["sharpe"]


def test_consolidate_with_benchmark():
    out = consolidate_report(_rets(), benchmark=_rets(seed=2))
    assert out["params"]["has_benchmark"] is True
    assert "beta" in out["dashboard"]
    assert "基准对比" in [s["title"] for s in out["export_sections"]]


def test_consolidate_with_weights_concentration():
    out = consolidate_report(_rets(), weights={"A": 0.5, "B": 0.3, "C": 0.2})
    assert out["params"]["n_assets"] == 3
    assert "concentration" in out["dashboard"]


def test_consolidate_export_sections_shape():
    out = consolidate_report(_rets())
    for sec in out["export_sections"]:
        assert "title" in sec and "kv" in sec
        assert isinstance(sec["kv"], dict)


def test_consolidate_too_few_returns():
    import pytest
    with pytest.raises(ValueError):
        consolidate_report([0.01])


def test_api_consolidate(client):
    res = client.post("/api/reports/consolidate", json={"returns": _rets()})
    assert res.status_code == 200
    body = res.json()
    assert "summary" in body and "export_sections" in body


def test_api_consolidate_bad_input(client):
    res = client.post("/api/reports/consolidate", json={"returns": [0.01]})
    assert res.status_code == 400


def test_api_consolidate_requires_auth(anon_client):
    res = anon_client.post("/api/reports/consolidate", json={"returns": _rets()})
    assert res.status_code == 401
