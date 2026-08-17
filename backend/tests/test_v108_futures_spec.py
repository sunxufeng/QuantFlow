"""V108 期货品种规格与计算器测试。"""

import pytest

from app.trading.futures_spec import (
    SpecNotFound,
    compute_futures,
    contract_value,
    limit_price,
    list_specs,
    margin_required,
    resolve_spec,
)


def test_resolve_strips_contract_month():
    spec = resolve_spec("IF2409")
    assert spec.code == "IF"
    assert spec.multiplier == 300.0
    assert spec.exchange == "CFFEX"


def test_resolve_lowercase_and_suffix():
    # 中国期货品种前缀本为小写（如 cu/r 等），解析应保留规格表中的规范小写键
    assert resolve_spec("cu2501").code == "cu"
    assert resolve_spec("sc2501.CFFEX").code == "sc"


def test_resolve_pure_letter():
    assert resolve_spec("IC").code == "IC"


def test_resolve_unknown_raises():
    with pytest.raises(SpecNotFound):
        resolve_spec("ZZ9999")


def test_contract_value():
    # IF 乘数 300，价格 3800 -> 1,140,000
    assert contract_value("IF2409", 3800) == 300 * 3800


def test_margin_required_default_and_override():
    # IF 默认保证金率 0.12
    assert margin_required("IF2409", 3800, 2) == 300 * 3800 * 2 * 0.12
    # 覆盖为 0.15
    assert margin_required("IF2409", 3800, 2, 0.15) == 300 * 3800 * 2 * 0.15


def test_limit_price_rounded_to_tick():
    # IF 涨跌停 ±10%，最小价位 0.2；昨结算 3800 -> 涨停 4180.0
    assert limit_price("IF2409", 3800, "up") == 4180.0
    assert limit_price("IF2409", 3800, "down") == 3420.0


def test_limit_price_commission_and_total():
    r = compute_futures("IF2409", 3800, 2, prev_close=3800)
    assert r["contract_value_per_lot"] == 1_140_000
    assert r["total_contract_value"] == 2_280_000
    assert r["margin_required"] == 300 * 3800 * 2 * 0.12
    # 股指按成交额万0.23：2_280_000 * 0.000023
    assert r["commission"] == pytest.approx(2_280_000 * 0.000023)
    assert r["limit_up"] == 4180.0
    assert r["limit_down"] == 3420.0


def test_compute_commodity_per_lot():
    # 沪铜 cu 乘数 5，每手 5 元；价格 70000，1 手 -> 合约价值 350000，手续费 5
    r = compute_futures("cu2501", 70000, 1)
    assert r["contract_value_per_lot"] == 5 * 70000
    assert r["commission"] == 5.0


def test_compute_missing_prev_close_no_limit():
    r = compute_futures("IF2409", 3800, 1)
    assert r["limit_up"] is None
    assert r["limit_down"] is None


def test_list_specs_nonempty_and_has_exchanges():
    specs = list_specs()
    assert len(specs) >= 20
    codes = {s["code"] for s in specs}
    for c in ("IF", "IC", "cu", "au", "m", "SR", "sc", "si"):
        assert c in codes


def test_api_futures_calc(client):
    r = client.post(
        "/api/trading/futures_calc",
        json={"symbol": "IF2409", "price": 3800, "qty": 2, "prev_close": 3800},
    )
    assert r.status_code == 200, r.text
    d = r.json()
    assert d["margin_required"] == 300 * 3800 * 2 * 0.12
    assert d["limit_up"] == 4180.0


def test_api_futures_calc_unknown_400(client):
    r = client.post(
        "/api/trading/futures_calc",
        json={"symbol": "ZZ9999", "price": 100, "qty": 1},
    )
    assert r.status_code == 400


def test_api_futures_calc_requires_auth(anon_client):
    r = anon_client.post(
        "/api/trading/futures_calc",
        json={"symbol": "IF2409", "price": 3800, "qty": 1},
    )
    assert r.status_code == 401


def test_api_futures_specs_requires_auth(anon_client):
    r = anon_client.get("/api/trading/futures_specs")
    assert r.status_code == 401
