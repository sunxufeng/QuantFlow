"""执行成本与最优执行 API 端点（/api/execution/*）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..execution import cost as ec

router = APIRouter()


class TradeItem(BaseModel):
    price: float
    shares: float
    side: str = "buy"


class CostReq(BaseModel):
    trades: List[TradeItem]
    commission_rate: float = 0.0003
    min_commission: float = 5.0
    fixed_per_trade: float = 0.0
    stamp_tax: float = 0.001
    regulator_fee: float = 0.00002


class ImpactReq(BaseModel):
    shares: float
    price: float
    adv: float
    volatility: float
    participation: float = 0.1
    eta: float = 0.5
    gamma: float = 0.3


class TwapReq(BaseModel):
    parent_qty: float
    n_slices: int
    interval_seconds: float = 60.0
    start_seconds: float = 0.0


class VwapReq(BaseModel):
    parent_qty: float
    n_slices: int = 6
    volume_profile: Optional[List[float]] = None
    interval_seconds: float = 60.0
    start_seconds: float = 0.0


class SlippageReq(BaseModel):
    arrival_mid: float
    fill_price: float
    side: str
    shares: float
    fee_bps: float = 0.0
    vwap_benchmark: Optional[float] = None
    impact_bps: float = 0.0


@router.post("/execution/cost")
def api_cost(req: CostReq, _: str = Depends(get_current_user)):
    try:
        return ec.transaction_cost(
            [t.model_dump() for t in req.trades], req.commission_rate, req.min_commission,
            req.fixed_per_trade, req.stamp_tax, req.regulator_fee,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/execution/impact")
def api_impact(req: ImpactReq, _: str = Depends(get_current_user)):
    try:
        return ec.market_impact(
            req.shares, req.price, req.adv, req.volatility, req.participation, req.eta, req.gamma
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/execution/twap")
def api_twap(req: TwapReq, _: str = Depends(get_current_user)):
    try:
        return ec.twap_schedule(req.parent_qty, req.n_slices, req.interval_seconds, req.start_seconds)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/execution/vwap")
def api_vwap(req: VwapReq, _: str = Depends(get_current_user)):
    try:
        return ec.vwap_schedule(
            req.parent_qty, req.volume_profile, req.n_slices, req.interval_seconds, req.start_seconds
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/execution/slippage")
def api_slippage(req: SlippageReq, _: str = Depends(get_current_user)):
    try:
        return ec.slippage_attribution(
            req.arrival_mid, req.fill_price, req.side, req.shares,
            req.fee_bps, req.vwap_benchmark, req.impact_bps,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
