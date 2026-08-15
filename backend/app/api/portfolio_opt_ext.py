"""组合优化增强 API（V32–V36）。

端点：
- POST /portfolio/risk-parity        风险平价 ERC（可指定风险预算）
- POST /portfolio/max-diversification 最大分散化
- POST /portfolio/hrp                 层次风险平价
- POST /portfolio/rebalance           组合再平衡引擎（漂移阈值→交易单）
- POST /portfolio/style-exposure      风格因子暴露归因
均鉴权；优化类端点接受显式收益矩阵或合成行情两种输入。
"""

from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..portfolio import optimize_ext as opt

router = APIRouter()


class _OptBase(BaseModel):
    assets: Optional[List[str]] = None
    returns: Optional[List[List[float]]] = None
    universe: Optional[List[str]] = None
    start: str = "2023-01-01"
    end: str = "2023-12-31"
    source: str = "synthetic"
    seed: int = 12345
    shrinkage: float = Field(default=0.0, ge=0.0, le=0.5, description="协方差收缩系数")


class RiskParityRequest(_OptBase):
    budgets: Optional[List[float]] = Field(None, description="风险预算（默认均等=ERC）")


class RebalanceRequest(BaseModel):
    current_weights: Dict[str, float]
    target_weights: Dict[str, float]
    threshold: float = Field(default=0.0, ge=0.0, le=1.0, description="单边漂移阈值（不交易带）")
    base_value: float = Field(default=1_000_000.0, gt=0.0)


class StyleExposureRequest(BaseModel):
    weights: Dict[str, float]
    factor_betas: Dict[str, Dict[str, float]]
    factors: Optional[List[str]] = None


def _weights_response(assets, w, cov=None):
    out = [{"asset": a, "weight": round(float(x), 6)} for a, x in zip(assets, w)]
    resp = {"assets": assets, "weights": out}
    if cov is not None:
        rc = opt.risk_contributions(np.asarray(w, dtype=float), np.asarray(cov, dtype=float))
        resp["risk_contributions"] = [round(float(x), 6) for x in rc]
        resp["diversification_ratio"] = round(opt.diversification_ratio(np.asarray(w, dtype=float), np.asarray(cov, dtype=float)), 6)
    return resp


@router.post("/portfolio/risk-parity", summary="风险平价组合 ERC（V32）")
def risk_parity(req: RiskParityRequest, user=Depends(get_current_user)):
    try:
        assets, R = opt.resolve_returns(req.assets, req.returns, req.universe, req.start, req.end, req.source, req.seed)
        cov = opt._cov_from_returns(R, shrinkage=req.shrinkage)
        w = opt.risk_parity_weights(cov, budgets=req.budgets)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _weights_response(assets, w, cov)


@router.post("/portfolio/max-diversification", summary="最大分散化组合（V33）")
def max_diversification(req: RiskParityRequest, user=Depends(get_current_user)):
    try:
        assets, R = opt.resolve_returns(req.assets, req.returns, req.universe, req.start, req.end, req.source, req.seed)
        cov = opt._cov_from_returns(R, shrinkage=req.shrinkage)
        w = opt.max_diversification_weights(cov)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _weights_response(assets, w, cov)


@router.post("/portfolio/hrp", summary="层次风险平价 HRP（V34）")
def hrp(req: RiskParityRequest, user=Depends(get_current_user)):
    try:
        assets, R = opt.resolve_returns(req.assets, req.returns, req.universe, req.start, req.end, req.source, req.seed)
        cov = opt._cov_from_returns(R, shrinkage=req.shrinkage)
        w = opt.hierarchical_risk_parity(cov)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return _weights_response(assets, w, cov)


@router.post("/portfolio/rebalance", summary="组合再平衡引擎（V35）")
def rebalance(req: RebalanceRequest, user=Depends(get_current_user)):
    try:
        plan = opt.rebalance_plan(req.current_weights, req.target_weights, req.threshold, req.base_value)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return plan


@router.post("/portfolio/style-exposure", summary="风格因子暴露归因（V36）")
def style_exposure(req: StyleExposureRequest, user=Depends(get_current_user)):
    try:
        res = opt.style_exposure(req.weights, req.factor_betas, req.factors)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return res
