"""实盘前哨：执行网关（Paper + Live 桩）单元测试（V1.3 工程化收尾第二阶段）。

覆盖：
- Paper 网关买入/卖出成交价、成本、持仓均价、账户净值
- 期货按手成本与空头（负持仓）
- Live 桩未配置凭证抛 GatewayNotConfigured
- 工厂默认 paper / live 切换
- REST 端点：/execution/mode、/execution/order、/execution/account
"""

from __future__ import annotations

import pytest

from app.execution import (
    GatewayNotConfigured,
    LiveExecutionGateway,
    Order,
    OrderSide,
    PaperExecutionGateway,
    get_execution_gateway,
)
from app.execution import gateway as gateway_mod


@pytest.fixture(autouse=True)
def _reset_gateway_singleton():
    """隔离进程内网关单例，避免用例间相互影响。"""
    gateway_mod._GATEWAY = None
    yield
    gateway_mod._GATEWAY = None


# --------------------------------------------------------------------------- #
# Paper 网关：股票
# --------------------------------------------------------------------------- #
def test_paper_buy_fill_and_cost():
    g = PaperExecutionGateway(initial_cash=1_000_000)
    fill = g.submit_order(Order("TEST.STOCK", OrderSide.BUY, 1000, market="stock", price=10.0))
    assert fill.price == 10.0
    # 佣金 = max(10000*0.00025, 5) = 5.0；过户费 = 10000*0.00001 = 0.1；买入无印花税
    assert fill.cost == pytest.approx(5.1)
    acct = g.get_account()
    # 现金 = 1_000_000 - 10000 - 5.1 = 989994.9
    assert acct["cash"] == pytest.approx(989994.9)
    assert len(acct["positions"]) == 1
    pos = acct["positions"][0]
    assert pos["quantity"] == 1000
    assert pos["avg_cost"] == 10.0
    # 净值 = 现金 + 持仓市值(10*1000) = 989994.9 + 10000 = 999994.9
    assert acct["equity"] == pytest.approx(999994.9)


def test_paper_sell_closes_position_and_realizes_cash():
    g = PaperExecutionGateway(initial_cash=1_000_000)
    g.submit_order(Order("TEST.STOCK", OrderSide.BUY, 1000, market="stock", price=10.0))
    fill = g.submit_order(Order("TEST.STOCK", OrderSide.SELL, 1000, market="stock", price=11.0))
    # 卖出成本：佣金 5.0 + 印花税 11000*0.0005=5.5 + 过户费 0.11 = 10.61
    assert fill.cost == pytest.approx(10.61)
    acct = g.get_account()
    # 现金 = 989994.9（买后） + (11000 - 10.61)（卖后） = 1000984.29
    assert acct["cash"] == pytest.approx(1000984.29)
    assert acct["positions"] == []  # 清仓


def test_paper_requires_price():
    g = PaperExecutionGateway(initial_cash=1_000_000)
    with pytest.raises(ValueError):
        g.submit_order(Order("TEST.STOCK", OrderSide.BUY, 100, market="stock"))


def test_paper_rejects_nonpositive_quantity():
    g = PaperExecutionGateway(initial_cash=1_000_000)
    with pytest.raises(ValueError):
        g.submit_order(Order("TEST.STOCK", OrderSide.BUY, 0, market="stock", price=10.0))


# --------------------------------------------------------------------------- #
# Paper 网关：期货（按手成本 + 空头）
# --------------------------------------------------------------------------- #
def test_paper_futures_per_lot_commission_and_short():
    g = PaperExecutionGateway(initial_cash=1_000_000)
    # 卖空 2 手（期货），按手手续费 3 元/手
    fill = g.submit_order(Order("TEST.FUTURE", OrderSide.SELL, 2, market="future", price=3500.0))
    assert fill.cost == pytest.approx(6.0)  # 3 * 2
    acct = g.get_account()
    # 开空：现金增加 3500*2 - 6 = 6994
    assert acct["cash"] == pytest.approx(1_006_994.0)
    pos = acct["positions"][0]
    assert pos["quantity"] == -2  # 空头持仓为负


# --------------------------------------------------------------------------- #
# Live 桩
# --------------------------------------------------------------------------- #
def test_live_gateway_not_configured(monkeypatch):
    monkeypatch.setenv("QF_BROKER_API_KEY", "")
    gw = LiveExecutionGateway()
    with pytest.raises(GatewayNotConfigured):
        gw.submit_order(Order("TEST.STOCK", OrderSide.BUY, 100, market="stock", price=10.0))
    with pytest.raises(GatewayNotConfigured):
        gw.get_account()
    with pytest.raises(GatewayNotConfigured):
        gw.get_positions()


# --------------------------------------------------------------------------- #
# 工厂：默认 paper / live 切换
# --------------------------------------------------------------------------- #
def test_factory_default_paper(monkeypatch):
    monkeypatch.delenv("QF_EXECUTION_GATEWAY", raising=False)
    gateway_mod._GATEWAY = None
    gw = get_execution_gateway()
    assert gw.mode == "paper"
    assert isinstance(gw, PaperExecutionGateway)


def test_factory_live(monkeypatch):
    monkeypatch.setenv("QF_EXECUTION_GATEWAY", "live")
    monkeypatch.setenv("QF_BROKER_API_KEY", "")
    gateway_mod._GATEWAY = None
    gw = get_execution_gateway()
    assert gw.mode == "live"
    assert isinstance(gw, LiveExecutionGateway)


# --------------------------------------------------------------------------- #
# REST 端点
# --------------------------------------------------------------------------- #
def test_execution_mode_paper(client):
    resp = client.get("/api/execution/mode")
    assert resp.status_code == 200
    body = resp.json()
    assert body["mode"] == "paper"
    assert body["live_configured"] is False


def test_execution_order_limit_price(client):
    resp = client.post(
        "/api/execution/order",
        json={"symbol": "TEST.STOCK", "side": "buy", "quantity": 100, "market": "stock", "price": 10.0},
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["fill"]["price"] == 10.0
    assert body["fill"]["quantity"] == 100
    # 账户快照应反映持仓
    acct = body["account"]
    assert acct["positions"][0]["quantity"] == 100


def test_execution_order_invalid_side(client):
    resp = client.post(
        "/api/execution/order",
        json={"symbol": "TEST.STOCK", "side": "hold", "quantity": 100, "price": 10.0},
    )
    assert resp.status_code == 400


def test_execution_order_market_resolves_fixture_price(client):
    # 不传 price，网关应回退到 fixture 最新价成交
    resp = client.post(
        "/api/execution/order",
        json={"symbol": "TEST.STOCK", "side": "buy", "quantity": 100, "market": "stock"},
    )
    assert resp.status_code == 200
    assert resp.json()["fill"]["price"] > 0


def test_execution_account_snapshot(client):
    client.post(
        "/api/execution/order",
        json={"symbol": "TEST.STOCK", "side": "buy", "quantity": 100, "market": "stock", "price": 10.0},
    )
    resp = client.get("/api/execution/account")
    assert resp.status_code == 200
    body = resp.json()
    assert "cash" in body and "equity" in body and "positions" in body
    assert body["positions"][0]["quantity"] == 100


def test_execution_live_unconfigured_returns_503(client, monkeypatch):
    monkeypatch.setenv("QF_EXECUTION_GATEWAY", "live")
    monkeypatch.setenv("QF_BROKER_API_KEY", "")
    gateway_mod._GATEWAY = None
    # 触发单例重建为 live
    client.get("/api/execution/mode")
    resp = client.get("/api/execution/account")
    assert resp.status_code == 503
