"""V1.8 模拟交易 API（paper trading）。

所有接口需登录；数据按用户隔离。市价单即时成交，限价单挂单可撤，并由
``POST /api/trading/simulate`` 按行情推进撮合。
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..execution.gateway import GatewayNotConfigured
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


class ResetIn(BaseModel):
    initial_cash: Optional[float] = None


@router.get("/trading/mode")
def get_mode(user: Dict[str, Any] = Depends(get_current_user)):
    return {
        "paper": True,
        "live_capable": engine.live_capable(),
        "broker": engine.live_broker(),
    }


@router.get("/trading/live/status")
def get_live_status(user: Dict[str, Any] = Depends(get_current_user)):
    return engine.live_status()


@router.get("/trading/live/positions")
def get_live_positions(user: Dict[str, Any] = Depends(get_current_user)):
    """V31 实盘持仓：经 QMT/CTP 连接器查询真实柜台；未配置返回 409。"""
    try:
        return engine.live_positions()
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="实盘持仓查询待券商 SDK 就绪后启用")


@router.get("/trading/live/fills")
def get_live_fills(user: Dict[str, Any] = Depends(get_current_user)):
    """V31 实盘成交：经 QMT/CTP 连接器查询真实柜台；未配置返回 409。"""
    try:
        return engine.live_fills()
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=409, detail=str(exc))
    except NotImplementedError:
        raise HTTPException(status_code=501, detail="实盘成交查询待券商 SDK 就绪后启用")


@router.get("/trading/live/account")
def get_live_account(user: Dict[str, Any] = Depends(get_current_user)):
    """V107 实盘账户快照（权益/现金/持仓市值/盈亏）；虚拟券商返回本地账本。"""
    return engine.live_account()


@router.post("/trading/live/orders")
def place_live(payload: OrderIn, user: Dict[str, Any] = Depends(get_current_user)):
    fill = engine.place_live_order(
        user["id"], payload.symbol, payload.side, payload.type, payload.qty, payload.price
    )
    return fill


@router.get("/trading/summary")
def get_summary(user: Dict[str, Any] = Depends(get_current_user)):
    return engine.summary(user["id"])


@router.get("/trading/account")
def get_account(user: Dict[str, Any] = Depends(get_current_user)):
    """V6.0 账户概览：初始资金（可配置）、当前现金/权益与持仓/挂单数。"""
    s = engine.summary(user["id"])
    return {
        "initial_cash": s["initial_cash"],
        "cash": s["cash"],
        "market_value": s["market_value"],
        "equity": s["equity"],
        "realized_pnl": s["realized_pnl"],
        "position_count": s["position_count"],
        "open_orders": s["open_orders"],
        "total_fees": s["total_fees"],
    }


@router.get("/trading/analytics")
def get_analytics(user: Dict[str, Any] = Depends(get_current_user)):
    return engine.analytics(user["id"])


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
def reset(payload: ResetIn = None, user: Dict[str, Any] = Depends(get_current_user)):
    """重置模拟账户；``initial_cash`` 可指定新的账户初始资金并持久化（V6.0）。"""
    initial = payload.initial_cash if payload else None
    if initial is not None and initial <= 0:
        raise HTTPException(status_code=400, detail="initial_cash 必须为正数")
    effective = engine._store.reset(user["id"], initial)
    return {"ok": True, "initial_cash": effective}


class VerifyIn(BaseModel):
    symbol: str
    side: str          # buy | sell
    type: str          # market | limit
    qty: float
    price: Optional[float] = None
    today_qty: Optional[float] = None  # SHFE/INE 平今拆单所需的当日持仓


@router.post("/trading/verify")
def verify(payload: VerifyIn, user: Dict[str, Any] = Depends(get_current_user)):
    """交易合规预检（V104，移植自 panda exchange/*_verify）。

    对一笔拟下委托做：交易时段、账户/持仓充足、涨跌停限价、平今/平昨拆单
    四项检查，返回 {ok, violations, suggestions}。不落库、不改变账户状态。
    """
    from ..trading.compliance import verify_order

    return verify_order(
        user["id"], payload.symbol, payload.side.lower(), payload.type.lower(),
        float(payload.qty), payload.price, None, payload.today_qty,
    )


class HedgeIn(BaseModel):
    kind: str                                   # beta | reverse | group
    # beta 对冲
    portfolio: Optional[list] = None            # [{symbol, market_value, beta}]
    future_price: Optional[float] = None
    multiplier: Optional[float] = None
    target_beta: float = 0.0
    future_beta: float = 1.0
    round_lot: float = 1.0
    # reverse 反向
    current_qty: float = 0.0
    mode: str = "close"                         # close | flip
    # group 篮子
    long_dict: Optional[dict] = None
    short_dict: Optional[dict] = None
    prices: Optional[dict] = None


@router.post("/trading/hedge")
def hedge(payload: HedgeIn, user: Dict[str, Any] = Depends(get_current_user)):
    """对冲 / 反向交易计算器（V105，移植自 panda reverse_operation 的计算内核）。

    按 ``kind`` 分发：
    - beta：用股指合约对股票组合做 Beta 中性对冲，返回应对冲手数/方向。
    - reverse：给定当前持仓，返回反向平仓/反手的下单量与方向。
    - group：给定多/空篮子，返回组单结构（对应 panda insert_*_group_order）。
    纯计算，不落库、不改变账户状态。
    """
    from ..trading.hedge import compute_hedge

    try:
        return compute_hedge(payload.model_dump())
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


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
