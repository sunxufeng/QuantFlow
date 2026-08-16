"""V104 交易合规预检 + 市场时段（移植自 panda exchange/*_verify / TradeTimeManager）。"""
import datetime

from app.core.db import db
from app.market.session import is_market_open, next_trade_date, session_label
from app.trading.compliance import verify_order, infer_asset_type, LIMIT_PCT_BY_EXCHANGE


def _seed_price(symbol, price):
    db.execute(
        "INSERT OR REPLACE INTO market_bars(symbol, date, interval, open, high, low, close, volume, amount, source, adjustment) "
        "VALUES(?, '2026-01-02', 'daily', ?, ?, ?, ?, 0, 0, '', 'none')",
        (symbol, price, price, price, price),
    )


def _setup_user(user_id, cash=1_000_000.0, symbol=None, qty=0.0):
    from app.trading import store

    store.reset(user_id, cash)
    if symbol is not None:
        store.db.execute(
            "INSERT OR REPLACE INTO trading_positions(user_id, symbol, qty, avg_cost) VALUES(?, ?, ?, ?)",
            (user_id, symbol, qty, 0.0),
        )


# ---------------- 市场时段 ----------------
def test_is_market_open_stock():
    # 周四 10:00 开市；周四 03:00 休市；周六休市
    assert is_market_open("stock", datetime.datetime(2026, 1, 1, 10, 0)) is True
    assert is_market_open("stock", datetime.datetime(2026, 1, 1, 3, 0)) is False
    assert is_market_open("stock", datetime.datetime(2026, 1, 3, 10, 0)) is False  # 周六


def test_is_market_open_future_night():
    # 周四 22:00 属夜盘；周五 01:00 仍属夜盘（跨午夜）
    assert is_market_open("future_night", datetime.datetime(2026, 1, 1, 22, 0)) is True
    assert is_market_open("future_night", datetime.datetime(2026, 1, 2, 1, 0)) is True
    assert is_market_open("future_night", datetime.datetime(2026, 1, 1, 12, 0)) is False


def test_next_trade_date_skips_weekend():
    # 2026-01-02 是周五 -> 下一交易日为 2026-01-05（周一，跳过周六日）
    assert next_trade_date(datetime.datetime(2026, 1, 2, 15, 0)) == "2026-01-05"
    assert session_label("stock", datetime.datetime(2026, 1, 3, 10, 0)) == "休市（非交易日）"


def test_api_market_session(client):
    resp = client.get("/api/market/session?asset_type=stock")
    assert resp.status_code == 200
    body = resp.json()
    assert "open" in body and "next_trade_date" in body


# ---------------- 资产类型推断 ----------------
def test_infer_asset_type():
    assert infer_asset_type("600519.SH")["asset_type"] == "stock"
    assert infer_asset_type("AU2312.SHF")["asset_type"] == "future"
    assert infer_asset_type("AU2312.SHF")["exchange"] == "SHF"
    assert LIMIT_PCT_BY_EXCHANGE["SH"] == 0.10


# ---------------- 合规预检（单元） ----------------
def test_verify_not_trading_time():
    _seed_price("600519", 100.0)
    _setup_user("c1")
    # 周四 03:00 非交易时段
    res = verify_order("c1", "600519", "buy", "market", 10, now=datetime.datetime(2026, 1, 1, 3, 0))
    assert res["ok"] is False
    assert any(v["code"] == "NOT_TRADING_TIME" for v in res["violations"])


def test_verify_cash_not_enough():
    _seed_price("600519", 100.0)
    _setup_user("c2", cash=1000.0)
    # 周四 10:00 开市，买 100 股 * 100 = 10000 > 1000
    res = verify_order("c2", "600519", "buy", "market", 100, now=datetime.datetime(2026, 1, 1, 10, 0))
    assert res["ok"] is False
    assert any(v["code"] == "CASH_NOT_ENOUGH" for v in res["violations"])


def test_verify_position_not_enough():
    _seed_price("600519", 100.0)
    _setup_user("c3", symbol="600519", qty=5.0)
    # 卖 10 但只有 5 持仓
    res = verify_order("c3", "600519", "sell", "market", 10, now=datetime.datetime(2026, 1, 1, 10, 0))
    assert res["ok"] is False
    assert any(v["code"] == "POSITION_NOT_ENOUGH" for v in res["violations"])


def test_verify_limit_up_blocks_buy():
    _seed_price("600519", 100.0)
    _setup_user("c4")
    # 限价买 111 >= 涨停 110
    res = verify_order("c4", "600519", "buy", "limit", 1, price=111.0, now=datetime.datetime(2026, 1, 1, 10, 0))
    assert res["ok"] is False
    assert any(v["code"] == "LIMIT_UP" for v in res["violations"])


def test_verify_limit_down_blocks_sell():
    _seed_price("AU2312.SHF", 400.0)
    _setup_user("c4b", symbol="AU2312.SHF", qty=10.0)
    # 限价卖 350 <= 跌停 360
    res = verify_order("c4b", "AU2312.SHF", "sell", "limit", 1, price=350.0, now=datetime.datetime(2026, 1, 1, 10, 0))
    assert res["ok"] is False
    assert any(v["code"] == "LIMIT_DOWN" for v in res["violations"])


def test_verify_ok_during_session():
    _seed_price("600519", 100.0)
    _setup_user("c5")
    # 开市、资金足、价格未触涨跌停
    res = verify_order("c5", "600519", "buy", "limit", 10, price=100.0, now=datetime.datetime(2026, 1, 1, 10, 0))
    assert res["ok"] is True


def test_verify_shfe_split_suggestion():
    _seed_price("AU2312.SHF", 400.0)
    _setup_user("c6", symbol="AU2312.SHF", qty=10.0)
    # 平今拆单：今仓 4，昨仓 6；卖 8 -> 先平昨 6 再平今 2
    res = verify_order("c6", "AU2312.SHF", "sell", "market", 8, now=datetime.datetime(2026, 1, 1, 10, 0), today_qty=4.0)
    assert any("先平昨" in s for s in res["suggestions"])


# ---------------- API ----------------
def test_api_verify_requires_auth(anon_client):
    assert anon_client.post("/api/trading/verify", json={"symbol": "X", "side": "buy", "type": "market", "qty": 1}).status_code == 401


def test_api_verify_structure(client):
    _seed_price("600519", 100.0)
    _setup_user("c7")
    resp = client.post("/api/trading/verify", json={"symbol": "600519", "side": "buy", "type": "limit", "qty": 1, "price": 100.0})
    assert resp.status_code == 200
    body = resp.json()
    assert "ok" in body and "violations" in body and "suggestions" in body
