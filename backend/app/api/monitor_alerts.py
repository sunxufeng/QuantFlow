"""组合监控与预警 API 端点（/api/monalert/*，避免与 /api/monitor 系统监控冲突）。"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..monitoring import alerts as ma

router = APIRouter()


class DriftReq(BaseModel):
    weights: List[float]
    target: List[float]
    asset_names: Optional[List[str]] = None
    threshold: float = 0.05


class ReturnQualityReq(BaseModel):
    returns: List[float]
    hit_rate_limit: float = 0.45
    payoff_ratio_limit: float = 0.8


class TeReq(BaseModel):
    returns_port: List[float]
    returns_bench: List[float]
    window: int = 20
    limit: float = 0.05


class SectorReq(BaseModel):
    group_weights: Dict[str, float]
    limit: float = 0.6


class BudgetReq(BaseModel):
    weights: List[float]
    cov: List[List[float]]
    target_budget: Optional[List[float]] = None
    asset_names: Optional[List[str]] = None


@router.post("/monalert/drift")
def api_drift(req: DriftReq, _: str = Depends(get_current_user)):
    try:
        return ma.drift_monitor(req.weights, req.target, req.asset_names, req.threshold)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/return-quality")
def api_return_quality(req: ReturnQualityReq, _: str = Depends(get_current_user)):
    try:
        return ma.return_quality_monitor(req.returns, req.hit_rate_limit, req.payoff_ratio_limit)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/tracking-error")
def api_te(req: TeReq, _: str = Depends(get_current_user)):
    try:
        return ma.tracking_error_monitor(req.returns_port, req.returns_bench, req.window, req.limit)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/sector-exposure")
def api_sector(req: SectorReq, _: str = Depends(get_current_user)):
    try:
        return ma.sector_exposure_monitor(req.group_weights, req.limit)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/risk-budget")
def api_budget(req: BudgetReq, _: str = Depends(get_current_user)):
    try:
        return ma.risk_budget_monitor(req.weights, req.cov, req.target_budget, req.asset_names)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
