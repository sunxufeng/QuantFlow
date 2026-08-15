"""V29 压力测试 / 情景分析测试。

覆盖：预置情景清单、历史情景冲击 P&L 计算、自定义冲击、权重归一化、
最差情景排序、API 端点返回结构。纯函数，不依赖外部数据源。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.backtest import stress_test as st
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "stress_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "stress_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


HOLDINGS = [
    {"symbol": "AAPL", "asset_class": "tech", "weight": 0.25},
    {"symbol": "SP500", "asset_class": "equity", "weight": 0.35},
    {"symbol": "AGG", "asset_class": "bond", "weight": 0.25},
    {"symbol": "GLD", "asset_class": "gold", "weight": 0.10},
    {"symbol": "VNQ", "asset_class": "reit", "weight": 0.05},
]


def test_list_scenarios_nonempty():
    sc = st.list_scenarios()
    assert len(sc) >= 5
    names = {s["name"] for s in sc}
    assert "2008全球金融危机" in names
    assert "2020新冠冲击" in names


def test_2008_scenario_impact():
    res = st.run_stress_test(HOLDINGS, scenarios=["2008全球金融危机"], base_value=1_000_000)
    assert res["base_value"] == 1_000_000
    assert len(res["scenarios"]) == 1
    s = res["scenarios"][0]
    # 股票/科技/REIT 大跌，债券/黄金小涨 -> 组合应显著负收益
    assert s["impact_pct"] < 0
    assert s["post_value"] == res["base_value"] + s["impact_value"]
    # 最拖后腿持仓应为 tech 或 reit（跌幅最大）
    assert s["worst_holding"]["symbol"] in ("AAPL", "VNQ", "SP500")


def test_custom_shocks_override():
    res = st.run_stress_test(
        HOLDINGS, custom_shocks={"equity": -0.20, "AAPL": -0.35}, base_value=1_000_000
    )
    # 自定义情景应出现在结果中
    names = [s["name"] for s in res["scenarios"]]
    assert "自定义情景" in names
    custom = next(s for s in res["scenarios"] if s["name"] == "自定义情景")
    # AAPL 用 symbol 级覆盖 -0.35，tech 权重 0.25 -> 贡献 -0.25*0.35 = -0.0875
    aapl = next(c for c in custom["contributions"] if c["symbol"] == "AAPL")
    assert aapl["shock"] == -0.35
    assert abs(aapl["contribution"] - (-0.25 * 0.35 * 1_000_000)) < 1


def test_weight_normalization():
    # 未归一化权重应自动归一
    raw = [
        {"symbol": "X", "asset_class": "equity", "weight": 40},
        {"symbol": "Y", "asset_class": "bond", "weight": 60},
    ]
    res = st.run_stress_test(raw, scenarios=["2008全球金融危机"], base_value=1_000_000)
    contribs = res["scenarios"][0]["contributions"]
    total_w = sum(c["weight"] for c in contribs)
    assert abs(total_w - 1.0) < 1e-6


def test_worst_scenario_ranking():
    res = st.run_stress_test(HOLDINGS, base_value=1_000_000)
    pcts = [s["impact_pct"] for s in res["scenarios"]]
    # 结果应按 impact_pct 升序（最差在前）
    assert pcts == sorted(pcts)
    assert res["summary"]["worst_scenario"] == res["scenarios"][0]["name"]
    assert res["summary"]["max_loss_pct"] == min(pcts)


def test_api_stress_scenarios_endpoint():
    r = client.get("/api/backtest/stress-scenarios")
    assert r.status_code == 200
    assert len(r.json()["scenarios"]) >= 5


def test_api_stress_test_endpoint():
    r = client.post(
        "/api/backtest/stress-test",
        json={"holdings": HOLDINGS, "scenarios": ["2020新冠冲击"], "base_value": 1_000_000},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["scenarios"][0]["impact_pct"] < 0
    assert "worst" in body and "summary" in body


def test_api_stress_test_invalid_empty_holdings():
    r = client.post("/api/backtest/stress-test", json={"holdings": []})
    assert r.status_code in (422, 400)
