import pytest
"""V1.8 模拟交易引擎 + API 测试。"""

from app.core.db import db


def _authed(username="trade_u"):
    from app.main import app
    from fastapi.testclient import TestClient

    c = TestClient(app)
    c.post("/api/auth/register", json={"username": username, "password": "secret123"})
    token = c.post("/api/auth/login", json={"username": username, "password": "secret123"}).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    return c


def _seed_price(symbol, price):
    db.execute(
        "INSERT OR REPLACE INTO market_bars(symbol, date, interval, open, high, low, close, volume, amount, source, adjustment) "
        "VALUES(?, '2026-01-01', 'daily', ?, ?, ?, ?, 0, 0, '', 'none')",
        (symbol, price, price, price, price),
    )


def test_trading_requires_auth(anon_client):
    assert anon_client.get("/api/trading/summary").status_code == 401
    assert anon_client.post("/api/trading/orders", json={"symbol": "X", "side": "buy", "type": "market", "qty": 1}).status_code == 401


def test_market_order_fills_and_updates_position():
    _seed_price("600519", 100.0)
    c = _authed("trade_mkt")
    resp = c.post("/api/trading/orders", json={"symbol": "600519", "side": "buy", "type": "market", "qty": 10})
    assert resp.status_code == 200
    body = resp.json()
    assert body["status"] == "filled"
    assert float(body["avg_fill_price"]) == 100.0

    pos = c.get("/api/trading/positions").json()
    assert len(pos) == 1
    assert float(pos[0]["qty"]) == 10

    summary = c.get("/api/trading/summary").json()
    # 现金 = 初始 - 成交额 - 手续费（佣金最低 5 元 + 过户费 0.01）
    assert summary["cash"] == pytest.approx(1_000_000 - 1000 - 5.01, abs=0.02)
    assert summary["position_count"] == 1


def test_limit_order_rests_and_simulate_fills():
    _seed_price("000001", 50.0)
    c = _authed("trade_lmt")
    # 限价买 45，当前价 50 不成交 → 挂单
    resp = c.post("/api/trading/orders", json={"symbol": "000001", "side": "buy", "type": "limit", "qty": 5, "price": 45})
    assert resp.status_code == 200
    assert resp.json()["status"] == "open"

    # 行情推进到 44 → 触发成交
    sim = c.post("/api/trading/simulate", json={"price_overrides": {"000001": 44.0}})
    assert sim.status_code == 200
    assert sim.json()["filled"]  # filled list non-empty

    orders = c.get("/api/trading/orders").json()
    assert any(o["status"] == "filled" and float(o["avg_fill_price"]) == 45.0 for o in orders)


def test_realized_pnl_on_close():
    _seed_price("AAPL", 100.0)
    c = _authed("trade_pnl")
    c.post("/api/trading/orders", json={"symbol": "AAPL", "side": "buy", "type": "market", "qty": 10})
    # 价格涨到 110 后卖出
    _seed_price("AAPL", 110.0)
    sell = c.post("/api/trading/orders", json={"symbol": "AAPL", "side": "sell", "type": "market", "qty": 10})
    assert sell.json()["status"] == "filled"
    summary = c.get("/api/trading/summary").json()
    assert summary["realized_pnl"] == (110 - 100) * 10  # 100
    assert summary["position_count"] == 0


def test_cancel_open_order():
    _seed_price("600519", 100.0)
    c = _authed("trade_cancel")
    o = c.post("/api/trading/orders", json={"symbol": "600519", "side": "buy", "type": "limit", "qty": 1, "price": 1}).json()
    cancel = c.post(f"/api/trading/orders/{o['id']}/cancel")
    assert cancel.status_code == 200
    assert cancel.json()["status"] == "cancelled"
    # 已撤单不能再撤
    again = c.post(f"/api/trading/orders/{o['id']}/cancel")
    assert again.status_code == 400


def test_reset_clears_account():
    _seed_price("600519", 100.0)
    c = _authed("trade_reset")
    c.post("/api/trading/orders", json={"symbol": "600519", "side": "buy", "type": "market", "qty": 1})
    resp = c.delete("/api/trading/reset")
    assert resp.status_code == 200
    summary = c.get("/api/trading/summary").json()
    assert summary["cash"] == 1_000_000
    assert summary["position_count"] == 0
    assert summary["open_orders"] == 0


def test_fees_and_equity_curve():
    _seed_price("600519", 100.0)
    c = _authed("trade_fees")
    c.delete("/api/trading/reset")  # 重置产生基线快照
    c.post("/api/trading/orders", json={"symbol": "600519", "side": "buy", "type": "market", "qty": 10})
    s = c.get("/api/trading/summary").json()
    # 买入手续费：佣金 max(1000*0.00025, 5)=5，过户费 1000*0.00001=0.01，共 5.01
    assert s["total_fees"] == pytest.approx(5.01, abs=0.02)
    assert s["cash"] == pytest.approx(1_000_000 - 1000 - 5.01, abs=0.02)
    # 权益曲线：基线 + 本次成交共 2 点
    assert len(s["equity_curve"]) >= 2
    assert s["equity_curve"][0]["equity"] == 1_000_000
    assert "daily_pnl" in s
    assert "win_rate" in s
    assert "exposure" in s


def test_win_rate_and_exposure_after_round_trip():
    _seed_price("AAPL", 100.0)
    c = _authed("trade_winrate")
    c.delete("/api/trading/reset")
    c.post("/api/trading/orders", json={"symbol": "AAPL", "side": "buy", "type": "market", "qty": 10})
    _seed_price("AAPL", 120.0)
    c.post("/api/trading/orders", json={"symbol": "AAPL", "side": "sell", "type": "market", "qty": 10})
    s = c.get("/api/trading/summary").json()
    assert s["position_count"] == 0
    assert s["realized_pnl"] == pytest.approx((120 - 100) * 10, abs=0.01)
    assert s["win_rate"] == 1.0  # 单笔平仓盈利
    assert s["exposure"] == pytest.approx(0.0, abs=0.001)  # 已平仓，无敞口


def test_live_mode_default_is_paper():
    c = _authed("trade_live_mode")
    r = c.get("/api/trading/mode")
    assert r.status_code == 200
    body = r.json()
    assert body["paper"] is True
    assert body["live_capable"] is False


def test_live_order_requires_config():
    c = _authed("trade_live_401")
    r = c.post("/api/trading/live/orders", json={"symbol": "AAPL", "side": "buy", "type": "market", "qty": 10})
    assert r.status_code == 409
    assert "券商设置" in r.json()["detail"]


def test_live_order_configured_wires_gateway():
    from app.trading import engine

    class FakeFill:
        symbol = "AAPL"
        side = "buy"
        quantity = 10
        price = 123.0
        cost = 1.0

    class FakeGateway:
        mode = "live"

        def submit_order(self, order, last_price=None):
            return FakeFill()

    orig_gw = engine.LiveExecutionGateway
    orig_cfg = engine.load_broker_config
    engine.LiveExecutionGateway = FakeGateway
    engine.load_broker_config = lambda: {
        "broker": "universal", "api_key": "x", "api_secret": "", "base_url": "", "account_id": ""
    }
    try:
        res = engine.place_live_order("u_demo", "AAPL", "buy", "market", 10)
        assert res["mode"] == "live"
        assert res["price"] == 123.0
        assert res["symbol"] == "AAPL"
    finally:
        engine.LiveExecutionGateway = orig_gw
        engine.load_broker_config = orig_cfg
