"""策略评估与显著性 API 端点（/api/sig/*）。"""
from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..backtest import significance as sig

router = APIRouter()


class DeflatedReq(BaseModel):
    sharpe: float
    n_obs: int
    skew: float = 0.0
    kurtosis: float = 3.0
    n_trials: int = 1


class PsrReq(BaseModel):
    sharpe: float
    n_obs: int
    skew: float = 0.0
    kurtosis: float = 3.0
    target_sr: float = 0.0


class CapacityReq(BaseModel):
    adv: float
    participation: float = 0.1
    impact_coef: float = 0.1
    annual_turnover: float = 2.0
    trading_days: int = 252


class RegimeReq(BaseModel):
    returns: List[float]
    regime_labels: List[str]
    regimes: Optional[List[str]] = None


class DiversificationReq(BaseModel):
    equity_curves: Dict[str, List[float]]


@router.post("/sig/deflated-sharpe")
def api_deflated(req: DeflatedReq, _: str = Depends(get_current_user)):
    try:
        return sig.deflated_sharpe_ratio(req.sharpe, req.n_obs, req.skew, req.kurtosis, req.n_trials)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sig/probabilistic-sharpe")
def api_psr(req: PsrReq, _: str = Depends(get_current_user)):
    try:
        return sig.probabilistic_sharpe_ratio(req.sharpe, req.n_obs, req.skew, req.kurtosis, req.target_sr)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sig/capacity")
def api_capacity(req: CapacityReq, _: str = Depends(get_current_user)):
    try:
        return sig.strategy_capacity(req.adv, req.participation, req.impact_coef,
                                     req.annual_turnover, req.trading_days)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sig/regime-stats")
def api_regime(req: RegimeReq, _: str = Depends(get_current_user)):
    try:
        return sig.regime_conditional_stats(req.returns, req.regime_labels, req.regimes)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/sig/diversification")
def api_div(req: DiversificationReq, _: str = Depends(get_current_user)):
    try:
        return sig.strategy_diversification(req.equity_curves)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
