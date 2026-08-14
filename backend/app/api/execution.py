"""实盘前哨 API（V1.3 工程化收尾第二阶段）。

暴露执行网关的「模式 / 下单 / 账户」接口，便于前端与监控展示模拟盘状态，
并为后续接入真实券商预留统一入口。

- ``GET  /api/execution/mode``   当前网关模式（paper/live）与 live 是否就绪
- ``POST /api/execution/order``  提交一笔市价/限价单（paper 即时成交）
- ``GET  /api/execution/account`` 账户快照（现金 / 持仓市值 / 净值 / 成交明细）
"""

from __future__ import annotations

import os

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from typing import Dict, Optional

from ..core.auth import get_current_user
from ..execution import (
    GatewayNotConfigured,
    Order,
    OrderSide,
    get_execution_gateway,
)
from ..market import market_service

router = APIRouter(
    prefix="/execution",
    tags=["execution"],
    dependencies=[Depends(get_current_user)],
)


def _resolve_last_price(symbol: str) -> Optional[float]:
    """尽力从行情源取最新收盘价；失败返回 None。"""
    try:
        bars = market_service.bars(symbol, "2000-01-01", "2100-01-01")
        if bars:
            return float(bars[-1].close)
    except Exception:  # pragma: no cover - 行情缺失不影响下单接口可用性
        return None
    return None


class OrderRequest(BaseModel):
    symbol: str
    side: str  # buy / sell
    quantity: float
    market: str = "stock"  # stock / future
    price: Optional[float] = None  # 限价；None 尝试用行情最新价成交


@router.get("/mode", summary="执行网关模式")
def execution_mode():
    gateway = get_execution_gateway()
    live_configured = bool(os.getenv("QF_BROKER_API_KEY", ""))
    payload = {
        "mode": gateway.mode,
        "live_configured": live_configured,
        "broker": os.getenv("QF_BROKER", "") if live_configured else "",
    }
    if gateway.mode == "paper":
        payload["paper_cash"] = gateway._initial_cash  # noqa: SLF001 - 只读展示
    return payload


@router.post("/order", summary="提交订单（模拟盘即时成交）")
def submit_order(req: OrderRequest):
    try:
        side = OrderSide(req.side.lower())
    except ValueError:
        raise HTTPException(status_code=400, detail=f"未知 side：{req.side}")
    if req.quantity <= 0:
        raise HTTPException(status_code=400, detail="quantity 必须为正数")
    price = req.price
    if price is None:
        price = _resolve_last_price(req.symbol)
    order = Order(
        symbol=req.symbol,
        side=side,
        quantity=req.quantity,
        market=req.market,
        price=price,
    )
    gateway = get_execution_gateway()
    try:
        fill = gateway.submit_order(order)
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return {"fill": fill.to_dict(), "account": gateway.get_account()}


@router.get("/account", summary="账户快照（模拟盘）")
def account_snapshot(prices: Optional[str] = None):
    """prices 可选，格式 ``SYM1:px1,SYM2:px2``，用于覆盖持仓估值价。"""
    override: Dict[str, float] = {}
    if prices:
        for piece in prices.split(","):
            if ":" not in piece:
                continue
            sym, px = piece.split(":", 1)
            try:
                override[sym.strip()] = float(px)
            except ValueError:
                continue
    gateway = get_execution_gateway()
    try:
        return gateway.get_account(prices=override or None)
    except GatewayNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
