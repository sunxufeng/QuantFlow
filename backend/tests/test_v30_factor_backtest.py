"""V30 因子库扩展 · 因子多空组合回测测试。

覆盖：内置因子名回测、表达式回测、横截面中性化开关、分组数、离线合成行情、
IC/累计收益结构与指标合理性、API 端点。行情源以 synthetic 数据打桩。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.factors import backtest as fb
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "fbt_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "fbt_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


UNIV = ["TEST.STOCK", "TEST.BANK", "TEST.FUND", "TEST.FUTURE"]
BASE = dict(factor="momentum", universe=UNIV, start="2023-01-01", end="2023-12-31",
            quantiles=5, neutralized=False, source="synthetic", seed=12345)


def test_catalog_has_factors():
    cat = fb.factor_catalog()
    names = {f["name"] for f in cat}
    assert "momentum" in names
    assert len(cat) >= 5


def test_builtin_factor_backtest():
    res = fb.factor_long_short(**BASE)
    assert res["factor"] == "momentum"
    assert len(res["cum_return"]) == len(res["dates"])
    assert len(res["ls_returns"]) == len(res["cum_return"])
    assert res["metrics"]["n"] > 0
    # IC 序列与指标
    assert "ic_mean" in res["metrics"]
    assert "ir" in res["metrics"]
    # 累计收益末值应为 1+ann 路径的合理范围
    assert res["metrics"]["max_drawdown"] <= 0
    # 多空组合收益不应全为 0（实际分组构造生效，用小股票池也成立）
    import statistics
    sd = statistics.pstdev(res["ls_returns"])
    assert sd > 0, "多空日收益方差为 0，说明分组/多空构造未生效"


def test_expression_factor_backtest():
    res = fb.factor_long_short(factor="close.pct_change(20)", universe=UNIV,
                               start="2023-01-01", end="2023-12-31",
                               quantiles=5, neutralized=False, source="synthetic", seed=12345)
    assert len(res["cum_return"]) > 0
    assert res["metrics"]["n"] > 0


def test_neutralized_flag_reflected():
    a = fb.factor_long_short(**BASE)
    b = fb.factor_long_short(**{**BASE, "neutralized": True})
    assert a["neutralized"] is False
    assert b["neutralized"] is True
    # 两种模式都应产出合法结构（多空组合收益序列非空、指标完整）
    assert a["metrics"]["n"] > 0 and b["metrics"]["n"] > 0
    assert "ic_mean" in b["metrics"] and "sharpe" in b["metrics"]


def test_quantiles_bounds():
    with pytest.raises(ValueError):
        fb.factor_long_short(**{**BASE, "quantiles": 1})


def test_live_source_without_data_errors():
    with pytest.raises(ValueError):
        fb.factor_long_short(**{**BASE, "source": "live"})


def test_api_catalog():
    r = client.get("/api/factors/backtest/catalog")
    assert r.status_code == 200
    assert len(r.json()["factors"]) >= 5


def test_api_backtest():
    r = client.post("/api/factors/backtest", json=BASE)
    assert r.status_code == 200
    body = r.json()
    assert body["metrics"]["n"] > 0
    assert len(body["cum_return"]) > 0


def test_api_backtest_bad_factor():
    r = client.post("/api/factors/backtest", json={**BASE, "factor": "not a valid expr &&&"})
    assert r.status_code in (400, 422)
