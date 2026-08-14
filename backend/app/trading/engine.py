"""V1.8 模拟交易撮合引擎（纯内存 + SQLite 持久化，无真实券商）。

- 市价单（market）：以最新收盘价即时成交。
- 限价单（limit）：挂单（open），可被撤单；由 ``simulate_tick`` 按行情推进撮合。
- 持仓以有符号数量表示：正为多（long），负为空（short）；成交时滚动计算开仓均价与已实现盈亏。
"""

from __future__ import annotations

from fastapi import HTTPException

from ..core.broker.config import load_broker_config
from ..backtest.costs import CostCalculator
from ..execution.gateway import (
    LiveExecutionGateway,
    Order as LiveOrder,
    OrderSide as LiveOrderSide,
    GatewayNotConfigured,
)

import time

from . import store as _store

# 与回测/执行网关一致的 A 股成本模型（佣金万 2.5、最低 5 元、印花税卖出 0.05%、过户费双边 0.001%）
_CALC = CostCalculator()
_INITIAL_CASH = 1_000_000.0


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _apply_fill(pos_qty: float, pos_avg: float, realized: float, delta: float, price: float):
    """更新持仓数量、均价与已实现盈亏（delta>0 买，<0 卖）。"""
    if pos_qty == 0:
        return delta, price, realized
    same_dir = (pos_qty > 0 and delta > 0) or (pos_qty < 0 and delta < 0)
    if same_dir:
        total_old = abs(pos_qty) * pos_avg
        total_new = abs(delta) * price
        new_qty = pos_qty + delta
        new_avg = (total_old + total_new) / abs(new_qty)
        return new_qty, new_avg, realized
    # 反向：平仓/反手
    close_qty = min(abs(delta), abs(pos_qty))
    pnl = (price - pos_avg) * close_qty if pos_qty > 0 else (pos_avg - price) * close_qty
    realized += pnl
    remaining = delta + pos_qty
    if remaining == 0:
        return 0, 0.0, realized
    if (remaining > 0 and pos_qty < 0) or (remaining < 0 and pos_qty > 0):
        # 反手，剩余部分以成交价开新仓
        return remaining, price, realized
    return remaining, pos_avg, realized


def _compute_fee(side: str, qty: float, price: float) -> float:
    """按 A 股成本模型计算单笔费用（与执行网关 PaperExecutionGateway 一致）。"""
    is_buy = side == "buy"
    costs = _CALC.transaction_costs(price, int(round(abs(qty))), is_buy)
    return float(costs["total"])


def _record_fill(user_id: str, order_id: str, symbol: str, side: str, qty: float, price: float, fee: float = 0.0):
    _store.db.execute(
        "INSERT INTO trading_fills(id, order_id, user_id, symbol, side, qty, price, fee, ts) VALUES(?,?,?,?,?,?,?,?,?)",
        (_store._uid(), order_id, user_id, symbol, side, qty, price, fee, time.time()),
    )


def _snapshot(user_id: str) -> None:
    """记录当前权益快照（每次成交后调用），供权益曲线/日盈亏使用。"""
    s = summary(user_id)
    _store.record_equity_snapshot(user_id, s["equity"], s["cash"], s["market_value"], s["realized_pnl"])


def _update_position(user_id: str, symbol: str, delta: float, price: float):
    """应用一笔成交到持仓（含现金变动由调用方处理）。"""
    pos = _store.get_position(user_id, symbol)
    qty = float(pos["qty"]) if pos else 0.0
    avg = float(pos["avg_cost"]) if pos else 0.0
    realized = float(pos["realized_pnl"]) if pos else 0.0
    new_qty, new_avg, realized = _apply_fill(qty, avg, realized, delta, price)
    if new_qty == 0:
        # 平仓后保留已实现盈亏（数量归零），便于累计统计
        _store.db.execute(
            "UPDATE trading_positions SET qty=0, avg_cost=0, realized_pnl=? WHERE user_id=? AND symbol=?",
            (realized, user_id, symbol),
        )
    elif pos:
        _store.db.execute(
            "UPDATE trading_positions SET qty=?, avg_cost=?, realized_pnl=? WHERE user_id=? AND symbol=?",
            (new_qty, new_avg, realized, user_id, symbol),
        )
    else:
        _store.db.execute(
            "INSERT INTO trading_positions(user_id, symbol, qty, avg_cost, realized_pnl) VALUES(?,?,?,?,?)",
            (user_id, symbol, new_qty, new_avg, realized),
        )


def submit_order(user_id: str, symbol: str, side: str, otype: str, qty: float, price=None):
    _store.init()
    symbol = (symbol or "").strip().upper()
    side = (side or "").lower()
    otype = (otype or "").lower()
    if not symbol:
        raise ValueError("标的代码不能为空")
    if side not in ("buy", "sell"):
        raise ValueError("side 必须为 buy 或 sell")
    if otype not in ("market", "limit"):
        raise ValueError("type 必须为 market 或 limit")
    qty = float(qty)
    if qty <= 0:
        raise ValueError("数量必须为正数")
    price = float(price) if price not in (None, "") else None
    if otype == "limit":
        if price is None or price <= 0:
            raise ValueError("限价单必须填写有效价格")
        # 挂单
        order_id = _store._uid()
        _store.db.execute(
            "INSERT INTO trading_orders(id, user_id, symbol, side, type, qty, price, status, filled_qty, avg_fill_price, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?, 'open', 0, NULL, ?, ?)",
            (order_id, user_id, symbol, side, otype, qty, price, _now(), _now()),
        )
        return get_order(user_id, order_id)

    # 市价单：即时以最新价成交
    mkt = _store.last_price(symbol)
    if mkt is None:
        order_id = _store._uid()
        _store.db.execute(
            "INSERT INTO trading_orders(id, user_id, symbol, side, type, qty, price, status, filled_qty, avg_fill_price, created_at, updated_at) "
            "VALUES(?,?,?,?,?,?,?, 'rejected', 0, NULL, ?, ?)",
            (order_id, user_id, symbol, side, otype, qty, price, _now(), _now()),
        )
        return get_order(user_id, order_id)
    return _fill_order(user_id, symbol, side, qty, mkt)


def _fill_order(user_id, symbol, side, qty, price):
    delta = qty if side == "buy" else -qty
    fee = _compute_fee(side, qty, price)
    # 现金变动（含费用）
    cash = _store.get_cash(user_id)
    if side == "buy":
        cash -= qty * price + fee
    else:
        cash += qty * price - fee
    _store.db.execute("UPDATE trading_cash SET cash=? WHERE user_id=?", (cash, user_id))
    _update_position(user_id, symbol, delta, price)
    _record_fill(user_id, "na", symbol, side, qty, price, fee)
    order_id = _store._uid()
    _store.db.execute(
        "INSERT INTO trading_orders(id, user_id, symbol, side, type, qty, price, status, filled_qty, avg_fill_price, created_at, updated_at) "
        "VALUES(?,?,?,?,?,?,?, 'filled', ?, ?, ?, ?)",
        (order_id, user_id, symbol, side, "market", qty, price, qty, price, _now(), _now()),
    )
    _snapshot(user_id)
    return get_order(user_id, order_id)


def cancel_order(user_id: str, order_id: str):
    _store.init()
    order = _store.db.query_one(
        "SELECT * FROM trading_orders WHERE id=? AND user_id=?", (order_id, user_id)
    )
    if not order:
        raise HTTPException(status_code=404, detail="委托不存在")
    if order["status"] != "open":
        raise HTTPException(status_code=400, detail=f"委托状态为 {order['status']}，无法撤销")
    _store.db.execute(
        "UPDATE trading_orders SET status='cancelled', updated_at=? WHERE id=?",
        (_now(), order_id),
    )
    return get_order(user_id, order_id)


def simulate_tick(user_id: str, price_overrides: dict = None):
    """按行情推进撮合挂单：价格越过限价即成交（buy≤limit，sell≥limit）。"""
    _store.init()
    price_overrides = price_overrides or {}
    open_orders = _store.list_orders(user_id, status="open")
    filled = []
    for o in open_orders:
        sym = o["symbol"]
        mkt = price_overrides.get(sym, _store.last_price(sym))
        if mkt is None:
            continue
        limit = float(o["price"])
        side = o["side"]
        cross = (side == "buy" and mkt <= limit) or (side == "sell" and mkt >= limit)
        if not cross:
            continue
        qty = float(o["qty"])
        fee = _compute_fee(side, qty, limit)
        # 现金变动（含费用）
        cash = _store.get_cash(user_id)
        cash += (-qty * limit - fee) if side == "buy" else (qty * limit - fee)
        _store.db.execute("UPDATE trading_cash SET cash=? WHERE user_id=?", (cash, user_id))
        _update_position(user_id, sym, qty if side == "buy" else -qty, limit)
        _record_fill(user_id, o["id"], sym, side, qty, limit, fee)
        _store.db.execute(
            "UPDATE trading_orders SET status='filled', filled_qty=?, avg_fill_price=?, updated_at=? WHERE id=?",
            (qty, limit, _now(), o["id"]),
        )
        filled.append(o["id"])
    if filled:
        _snapshot(user_id)
    return filled


def live_capable() -> bool:
    """是否具备实盘条件：配置了真实券商且已填 api_key。"""
    cfg = load_broker_config()
    return cfg.get("broker") in ("universal", "easytrade", "xuntou") and bool(cfg.get("api_key"))


def live_broker() -> str:
    return load_broker_config().get("broker", "none")


def place_live_order(user_id, symbol, side, otype, qty, price=None):
    """实盘下单：接入 LiveExecutionGateway；凭证/SDK 就绪前返回结构化的 4xx/5xx。"""
    if not live_capable():
        raise HTTPException(
            status_code=409,
            detail="实盘未配置：请在「券商设置」中配置真实券商凭证（universal/easytrade/xuntou）",
        )
    gw = LiveExecutionGateway()
    order = LiveOrder(
        symbol=symbol,
        side=LiveOrderSide(side),
        quantity=float(qty),
        price=float(price) if price not in (None, "") else None,
    )
    try:
        fill = gw.submit_order(order)
    except NotImplementedError:
        raise HTTPException(
            status_code=501,
            detail="实盘下单已接入执行网关，真实券商 SDK 待凭证就绪后启用",
        )
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    # 实盘成交记录到模拟成交表（统一查询），并标记为实盘来源
    _store.db.execute(
        "INSERT INTO trading_fills(id, order_id, user_id, symbol, side, qty, price, ts) VALUES(?,?,?,?,?,?,?,?)",
        (_store._uid(), "live", user_id, symbol, side, float(qty), fill.price, time.time()),
    )
    return {
        "mode": "live",
        "symbol": fill.symbol,
        "side": fill.side,
        "quantity": fill.quantity,
        "price": fill.price,
        "cost": fill.cost,
    }


def get_order(user_id: str, order_id: str):
    return _store.db.query_one(
        "SELECT * FROM trading_orders WHERE id=? AND user_id=?", (order_id, user_id)
    )


def summary(user_id: str):
    _store.init()
    cash = _store.get_cash(user_id)
    positions = _store.list_positions(user_id)
    market_value = 0.0
    for p in positions:
        px = _store.last_price(p["symbol"])
        if px is not None:
            market_value += float(p["qty"]) * px
    equity = cash + market_value
    realized_row = _store.db.query_one(
        "SELECT COALESCE(SUM(realized_pnl),0) AS r FROM trading_positions WHERE user_id=?", (user_id,)
    )
    realized = float(realized_row["r"]) if realized_row else 0.0
    open_orders = _store.list_orders(user_id, status="open")

    # 费用合计
    fills = _store.list_fills(user_id, limit=10000)
    total_fees = round(sum(float(f["fee"]) if f["fee"] is not None else 0.0 for f in fills), 2)

    # 胜率：按已平仓标的的累计已实现盈亏判定
    closed = _store.db.query(
        "SELECT realized_pnl FROM trading_positions WHERE user_id=? AND qty=0 AND realized_pnl!=0",
        (user_id,),
    )
    wins = sum(1 for r in closed if float(r["realized_pnl"]) > 0)
    losses = sum(1 for r in closed if float(r["realized_pnl"]) < 0)
    win_rate = round(wins / (wins + losses), 4) if (wins + losses) > 0 else 0.0

    exposure = round(market_value / equity, 4) if equity else 0.0

    # 权益曲线 + 日盈亏
    snaps = _store.list_equity_snapshots(user_id)
    equity_curve = [{"ts": float(s["ts"]), "equity": round(float(s["equity"]), 2)} for s in snaps]
    daily = {}
    for s in snaps:
        day = time.strftime("%Y-%m-%d", time.localtime(float(s["ts"])))
        daily[day] = round(float(s["equity"]), 2)
    daily_pnl = []
    prev = _INITIAL_CASH
    for d in sorted(daily.keys()):
        eq = daily[d]
        daily_pnl.append({"date": d, "pnl": round(eq - prev, 2)})
        prev = eq

    return {
        "cash": round(cash, 2),
        "market_value": round(market_value, 2),
        "equity": round(equity, 2),
        "realized_pnl": round(realized, 2),
        "total_fees": total_fees,
        "win_rate": win_rate,
        "exposure": exposure,
        "position_count": len(positions),
        "open_orders": len(open_orders),
        "equity_curve": equity_curve,
        "daily_pnl": daily_pnl,
        "initial_cash": _INITIAL_CASH,
    }
