"""V1.8 模拟交易 API（paper trading）。

所有接口需登录；数据按用户隔离。市价单即时成交，限价单挂单可撤，并由
``POST /api/trading/simulate`` 按行情推进撮合。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..trading import engine
from ..trading import store

router = APIRouter(tags=["trading"])


class OrderIn(BaseModel):
    symbol: str
    side: str          # buy | sell
    type: str          # market | limit
    qty: float
    price: Optional[float] = None


class SimulateIn(BaseModel):
    price_overrides: Dict[str, float] = {}


@router.get("/trading/summary")
def get_summary(user: Dict[str, Any] = Depends(get_current_user)):
    return engine.summary(user["id"])


@router.get("/trading/positions")
def get_positions(user: Dict[str, Any] = Depends(get_current_user)):
    return store.list_positions(user["id"])


@router.get("/trading/orders")
def get_orders(user: Dict[str, Any] = Depends(get_current_user), status: Optional[str] = None):
    return store.list_orders(user["id"], status=status)


@router.post("/trading/orders")
def place_order(payload: OrderIn, user: Dict[str, Any] = Depends(get_current_user)):
    order = engine.submit_order(
        user["id"], payload.symbol, payload.side, payload.type, payload.qty, payload.price
    )
    return _serialize(order)


@router.post("/trading/orders/{order_id}/cancel")
def cancel(order_id: str, user: Dict[str, Any] = Depends(get_current_user)):
    order = engine.cancel_order(user["id"], order_id)
    return _serialize(order)


@router.post("/trading/simulate")
def simulate(payload: SimulateIn, user: Dict[str, Any] = Depends(get_current_user)):
    filled = engine.simulate_tick(user["id"], payload.price_overrides or {})
    return {"filled": filled, "summary": engine.summary(user["id"])}


@router.delete("/trading/reset")
def reset(user: Dict[str, Any] = Depends(get_current_user)):
    engine._store.reset(user["id"])
    return {"ok": True}


def _serialize(order: Optional[dict]) -> Optional[dict]:
    if not order:
        return None
    return {
        "id": order["id"],
        "symbol": order["symbol"],
        "side": order["side"],
        "type": order["type"],
        "qty": order["qty"],
        "price": order["price"],
        "status": order["status"],
        "filled_qty": order["filled_qty"],
        "avg_fill_price": order["avg_fill_price"],
        "created_at": order["created_at"],
    }
