"""组合层面增强 API 端点（/api/portfolioi/*）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..portfolio import portfolio_i as pi

router = APIRouter()


class ViewItem(BaseModel):
    assets: List[int]
    coefs: Optional[List[float]] = None
    q: float
    confidence: float = 0.5


class BLReq(BaseModel):
    cov: List[List[float]]
    prior_weights: Optional[List[float]] = None
    views: Optional[List[ViewItem]] = None
    risk_aversion: float = 2.5
    tau: float = 0.05
    asset_names: Optional[List[str]] = None


class FactorReq(BaseModel):
    factor_exposures: List[List[float]]
    target_bets: Optional[List[float]] = None
    base_weights: Optional[List[float]] = None
    asset_names: Optional[List[str]] = None
    method: str = "tilt"
    max_active: float = 0.5
    long_only: bool = True
    cov: Optional[List[List[float]]] = None


class StressReq(BaseModel):
    weights: List[float]
    asset_names: Optional[List[str]] = None
    shocks: Optional[Dict[str, float]] = None
    scenario: Optional[str] = None
    factor_exposures: Optional[List[List[float]]] = None
    factor_shocks: Optional[Dict[str, float]] = None


class RebalReq(BaseModel):
    current_weights: List[float]
    target_weights: List[float]
    turnover_limit: Optional[float] = None
    min_trade: float = 0.0
    max_weight: Optional[float] = None
    long_only: bool = True
    no_trade_band: float = 0.0


class PositionItem(BaseModel):
    asset: Optional[str] = None
    value: float = 0.0


class AccountItem(BaseModel):
    name: Optional[str] = None
    positions: Any = Field(default_factory=dict)
    cash: float = 0.0


class AggReq(BaseModel):
    accounts: List[AccountItem]
    cash_label: str = "现金"


@router.post("/portfolioi/black-litterman")
def api_bl(req: BLReq, _: str = Depends(get_current_user)):
    try:
        return pi.black_litterman(
            req.cov, req.prior_weights,
            [v.model_dump() for v in req.views] if req.views else None,
            req.risk_aversion, req.tau, req.asset_names,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portfolioi/factor-portfolio")
def api_factor(req: FactorReq, _: str = Depends(get_current_user)):
    try:
        return pi.factor_portfolio(
            req.factor_exposures, req.target_bets, req.base_weights, req.asset_names,
            req.method, req.max_active, req.long_only, req.cov,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portfolioi/stress-test")
def api_stress(req: StressReq, _: str = Depends(get_current_user)):
    try:
        return pi.stress_test(
            req.weights, req.asset_names, req.shocks, req.scenario,
            req.factor_exposures, req.factor_shocks,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portfolioi/rebalance")
def api_rebal(req: RebalReq, _: str = Depends(get_current_user)):
    try:
        return pi.constrained_rebalance(
            req.current_weights, req.target_weights, req.turnover_limit, req.min_trade,
            req.max_weight, req.long_only, req.no_trade_band,
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/portfolioi/aggregate")
def api_agg(req: AggReq, _: str = Depends(get_current_user)):
    try:
        accounts = [a.model_dump() for a in req.accounts]
        return pi.aggregate_accounts(accounts, req.cash_label)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
