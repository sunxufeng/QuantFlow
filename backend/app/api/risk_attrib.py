"""风险归因与因子风险模型 API 端点（/api/riskattr/*）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..risk import risk_attrib as ra

router = APIRouter()


class FactorRiskReq(BaseModel):
    weights: List[float]
    factor_exposures: List[List[float]]
    factor_cov: List[List[float]]
    specific_var: Optional[List[float]] = None
    factor_names: Optional[List[str]] = None


class FactorRetAttrReq(BaseModel):
    weights: List[float]
    factor_exposures: List[List[float]]
    factor_returns: List[List[float]]
    specific_returns: Optional[List[float]] = None
    factor_names: Optional[List[str]] = None


class CompVarReq(BaseModel):
    returns: List[List[float]]
    weights: Optional[List[float]] = None
    alpha: float = 0.05


class RiskTreeReq(BaseModel):
    weights: List[float]
    cov: List[List[float]]
    groups: List[str]
    asset_names: Optional[List[str]] = None


class TailReq(BaseModel):
    returns: List[float]
    risk_free: float = 0.0
    periods_per_year: int = 252


@router.post("/riskattr/factor-risk")
def api_factor_risk(req: FactorRiskReq, _: str = Depends(get_current_user)):
    try:
        return ra.factor_risk_decomposition(
            req.weights, req.factor_exposures, req.factor_cov, req.specific_var, req.factor_names
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/riskattr/factor-return")
def api_factor_return(req: FactorRetAttrReq, _: str = Depends(get_current_user)):
    try:
        return ra.factor_return_attribution(
            req.weights, req.factor_exposures, req.factor_returns, req.specific_returns, req.factor_names
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/riskattr/component-var")
def api_component_var(req: CompVarReq, _: str = Depends(get_current_user)):
    try:
        return ra.component_var(req.returns, req.weights, req.alpha)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/riskattr/risk-tree")
def api_risk_tree(req: RiskTreeReq, _: str = Depends(get_current_user)):
    try:
        return ra.risk_decomposition_tree(req.weights, req.cov, req.groups, req.asset_names)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/riskattr/tail")
def api_tail(req: TailReq, _: str = Depends(get_current_user)):
    try:
        return ra.tail_risk_metrics(req.returns, req.risk_free, req.periods_per_year)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
