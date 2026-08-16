"""衍生品策略与对冲 API 端点（/api/deriv/*）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..derivatives import hedging as dh

router = APIRouter()


class LegItem(BaseModel):
    type: str
    side: str = "long"
    strike: float
    premium: float = 0.0
    qty: int = 1


class PayoffReq(BaseModel):
    legs: List[LegItem]
    spot_min: Optional[float] = None
    spot_max: Optional[float] = None
    n_points: int = 101


class HedgeReq(BaseModel):
    path: List[float]
    strike: float
    r: float = 0.0
    sigma: float = 0.2
    rebalance_every: int = 1
    option_type: str = "call"
    premium: Optional[float] = None
    T: float = 1.0


class InsuranceReq(BaseModel):
    risky_path: List[float]
    method: str = "put"
    floor: float = 0.8
    put_strike: Optional[float] = None
    put_premium: Optional[float] = None
    collar_cap: Optional[float] = None
    cppi_multiplier: float = 3.0
    r: float = 0.0


class PositionItem(BaseModel):
    type: str
    strike: float
    t: float
    sigma: float
    qty: float = 1.0
    side: str = "long"


class GreeksReq(BaseModel):
    positions: List[PositionItem]
    spot: float
    r: float = 0.0


class SurfaceReq(BaseModel):
    strikes: List[float]
    maturities: List[float]
    iv: List[List[float]]
    spot: Optional[float] = None


@router.post("/deriv/payoff")
def api_payoff(req: PayoffReq, _: str = Depends(get_current_user)):
    try:
        return dh.option_payoff([l.model_dump() for l in req.legs], req.spot_min, req.spot_max, req.n_points)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deriv/delta-hedge")
def api_hedge(req: HedgeReq, _: str = Depends(get_current_user)):
    try:
        return dh.delta_hedge(req.path, req.strike, req.r, req.sigma, req.rebalance_every,
                              req.option_type, req.premium, req.T)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deriv/insurance")
def api_insurance(req: InsuranceReq, _: str = Depends(get_current_user)):
    try:
        return dh.portfolio_insurance(req.risky_path, req.method, req.floor, req.put_strike,
                                      req.put_premium, req.collar_cap, req.cppi_multiplier, req.r)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deriv/portfolio-greeks")
def api_greeks(req: GreeksReq, _: str = Depends(get_current_user)):
    try:
        return dh.portfolio_greeks([p.model_dump() for p in req.positions], req.spot, req.r)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/deriv/vol-surface")
def api_surface(req: SurfaceReq, _: str = Depends(get_current_user)):
    try:
        return dh.implied_vol_surface(req.strikes, req.maturities, req.iv, req.spot)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
