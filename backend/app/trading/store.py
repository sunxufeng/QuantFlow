"""V1.8 模拟交易持久化层（SQLite）。

表结构幂等创建；首次访问时确保存在。模拟账户以用户维度隔离：
- ``trading_cash``：现金余额（初始 1,000,000）
- ``trading_positions``：持仓（qty 有正负，正为多/long，负为空/short）
- ``trading_orders``：委托单（market 即时成交；limit 挂单，可撤）
- ``trading_fills``：成交明细
"""

from __future__ import annotations

import threading
import time
import uuid

from ..core.db import db

_SCHEMA = """
CREATE TABLE IF NOT EXISTS trading_cash (
    user_id TEXT PRIMARY KEY,
    cash REAL NOT NULL DEFAULT 1000000
);
CREATE TABLE IF NOT EXISTS trading_positions (
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    qty REAL NOT NULL,
    avg_cost REAL NOT NULL DEFAULT 0,
    realized_pnl REAL NOT NULL DEFAULT 0,
    PRIMARY KEY (user_id, symbol)
);
CREATE TABLE IF NOT EXISTS trading_orders (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    type TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL,
    status TEXT NOT NULL,
    filled_qty REAL NOT NULL DEFAULT 0,
    avg_fill_price REAL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS trading_fills (
    id TEXT PRIMARY KEY,
    order_id TEXT NOT NULL,
    user_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    qty REAL NOT NULL,
    price REAL NOT NULL,
    ts REAL NOT NULL
);
"""

_lock = threading.RLock()
_initialized = False


def init() -> None:
    """确保模拟交易相关表存在（幂等）。"""
    global _initialized
    if _initialized:
        return
    with _lock:
        if _initialized:
            return
        # 多语句 DDL 必须用 executescript（db.execute 仅支持单语句）
        db._ensure().executescript(_SCHEMA)
        _initialized = True


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _uid() -> str:
    return uuid.uuid4().hex


def reset(user_id: str) -> None:
    """重置某用户的模拟账户（现金/持仓/委托/成交）。"""
    init()
    with _lock:
        db.execute("DELETE FROM trading_fills WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM trading_orders WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM trading_positions WHERE user_id=?", (user_id,))
        db.execute("DELETE FROM trading_cash WHERE user_id=?", (user_id,))


def get_cash(user_id: str) -> float:
    init()
    row = db.query_one("SELECT cash FROM trading_cash WHERE user_id=?", (user_id,))
    if row is None:
        db.execute("INSERT INTO trading_cash(user_id, cash) VALUES(?, 1000000)", (user_id,))
        return 1_000_000.0
    return float(row["cash"])


def last_price(symbol: str):
    """取该标的的最新收盘价（来自 market_bars）。"""
    row = db.query_one(
        "SELECT close FROM market_bars WHERE symbol=? ORDER BY date DESC LIMIT 1",
        (symbol,),
    )
    return float(row["close"]) if row else None


def get_position(user_id: str, symbol: str):
    return db.query_one(
        "SELECT * FROM trading_positions WHERE user_id=? AND symbol=?",
        (user_id, symbol),
    )


def list_positions(user_id: str):
    return db.query("SELECT * FROM trading_positions WHERE user_id=? AND qty != 0", (user_id,))


def list_orders(user_id: str, status=None, limit=100):
    if status:
        return db.query(
            "SELECT * FROM trading_orders WHERE user_id=? AND status=? ORDER BY created_at DESC LIMIT ?",
            (user_id, status, limit),
        )
    return db.query(
        "SELECT * FROM trading_orders WHERE user_id=? ORDER BY created_at DESC LIMIT ?",
        (user_id, limit),
    )


def list_fills(user_id: str, limit=100):
    return db.query(
        "SELECT * FROM trading_fills WHERE user_id=? ORDER BY ts DESC LIMIT ?",
        (user_id, limit),
    )
