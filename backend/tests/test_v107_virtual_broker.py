"""V107 虚拟券商（B 类实盘功能化）测试。

覆盖：
- VirtualBrokerConnector 接口等价 CTP/QMT，is_configured 恒 True，无需凭证/SDK；
- registry 对 virtual/simulated 返回虚拟连接器；
- live_capable / live_status 在 broker=virtual 时判定就绪；
- 经 LiveExecutionGateway + engine.place_live_order 端到端：下单→持仓→盈亏持久化；
- gateway.reset 委托到虚拟连接器（清空本地账本）；
- 真实券商（qmt/ctp）不受影响，仍按需 gated。

虚拟账本为进程级共享单例，每个用例前 reset 以保证隔离。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.broker.registry import get_live_connector
from app.core.broker.config import SUPPORTED_BROKERS
from app.core.broker.virtual import VirtualBrokerConnector, _book
from app.execution.gateway import Order, OrderSide
from app.main import app
from app.trading import engine


def _reset_book():
    _book().reset(1_000_000.0)


@pytest.fixture(autouse=True)
def _reset_virtual_book():
    _reset_book()
    yield
    _reset_book()


client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v107_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v107_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    return c


# --- 连接器本身 ---
def test_virtual_in_supported_brokers():
    assert "virtual" in SUPPORTED_BROKERS


def test_virtual_connector_always_configured():
    conn = VirtualBrokerConnector()
    assert conn.is_configured() is True
    assert conn.mode == "virtual"


def test_virtual_connector_submits_and_tracks():
    conn = VirtualBrokerConnector()
    fill = conn.submit_order(Order("600519.SH", OrderSide.BUY, 100, market="stock"), last_price=1700.0)
    assert fill.quantity == 100
    assert fill.price == 1700.0
    pos = conn.get_positions()
    assert len(pos) == 1
    assert pos[0].symbol == "600519.SH"
    assert pos[0].quantity == 100


def test_registry_returns_virtual_for_virtual_and_simulated():
    assert isinstance(get_live_connector({"broker": "virtual"}), VirtualBrokerConnector)
    assert isinstance(get_live_connector({"broker": "simulated"}), VirtualBrokerConnector)
    assert isinstance(get_live_connector({"broker": "simulated-broker"}), VirtualBrokerConnector)


# --- engine 就绪判定 ---
def test_live_capable_true_for_virtual(monkeypatch):
    monkeypatch.setenv("QF_BROKER", "virtual")
    _reset_book()
    assert engine.live_capable() is True


def test_live_status_virtual_branch(monkeypatch):
    monkeypatch.setenv("QF_BROKER", "virtual")
    st = engine.live_status()
    assert st["broker"] == "virtual"
    assert st["live_capable"] is True
    assert st["missing"] == []
    assert "虚拟" in st["message"]


# --- 端到端：经 engine + LiveExecutionGateway ---
def test_place_live_order_via_virtual(monkeypatch):
    monkeypatch.setenv("QF_BROKER", "virtual")
    _reset_book()
    fill = engine.place_live_order("u1", "000001.SZ", "buy", "limit", 200, 12.0)
    assert fill["quantity"] == 200
    assert fill["price"] == 12.0
    # 持仓持久化（跨 LiveExecutionGateway 实例共享账本）
    positions = engine.live_positions()
    assert any(p["symbol"] == "000001.SZ" and p["quantity"] == 200 for p in positions)
    # 账户快照含盈亏
    acc = engine.live_account()
    assert acc["mode"] == "virtual"
    assert acc["initial_cash"] == 1_000_000.0
    assert "pnl" in acc and "pnl_pct" in acc


def test_live_market_order_requires_quote(monkeypatch):
    from fastapi import HTTPException as FastAPIHTTPException

    monkeypatch.setenv("QF_BROKER", "virtual")
    _reset_book()
    # 无最新行情时，市价单应清晰提示改用限价单（409）
    with pytest.raises(FastAPIHTTPException) as exc:
        engine.place_live_order("u1", "600519.SH", "buy", "market", 100, None)
    assert exc.value.status_code == 409


def test_gateway_reset_delegates_to_virtual(monkeypatch):
    from app.execution.gateway import LiveExecutionGateway

    monkeypatch.setenv("QF_BROKER", "virtual")
    gw = LiveExecutionGateway()
    gw.submit_order(Order("IF2409", OrderSide.BUY, 1, market="future"), last_price=3800.0)
    assert len(gw.get_positions()) == 1
    gw.reset(500_000.0)
    assert len(gw.get_positions()) == 0
    assert gw.get_account()["initial_cash"] == 500_000.0


# --- 真实券商不受影响，仍 gated ---
def test_real_broker_still_gated(monkeypatch):
    monkeypatch.setenv("QF_BROKER", "none")
    _reset_book()
    with pytest.raises(Exception):
        # broker=none 且无 api_key -> GatewayNotConfigured
        engine.live_positions()


# --- API 端到端 ---
def test_api_enable_virtual_then_trade():
    # 启用虚拟券商
    r = client.put("/api/settings/broker", json={"broker": "virtual"})
    assert r.status_code == 200
    # mode 端点应判定就绪
    r = client.get("/api/trading/mode")
    assert r.status_code == 200 and r.json()["live_capable"] is True
    # 实盘下单（限价，无需行情依赖）
    r = client.post(
        "/api/trading/live/orders",
        json={"symbol": "600519.SH", "side": "buy", "type": "limit", "qty": 100, "price": 1700.0},
    )
    assert r.status_code == 200, r.text
    fill = r.json()
    assert fill["quantity"] == 100
    # 持仓 / 账户
    r = client.get("/api/trading/live/positions")
    assert r.status_code == 200 and any(p["symbol"] == "600519.SH" for p in r.json())
    r = client.get("/api/trading/live/account")
    assert r.status_code == 200
    acc = r.json()
    assert acc["mode"] == "virtual"
    assert "pnl" in acc
    # 还原为 none，避免影响其他 suite
    client.put("/api/settings/broker", json={"broker": "none"})


def test_api_live_account_401_when_anon():
    anon = TestClient(app)
    r = anon.get("/api/trading/live/account")
    assert r.status_code == 401
