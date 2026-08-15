"""风险分析 API（V42–V46）。

端点：
- POST /risk/var           VaR / CVaR（历史/参数/蒙特卡洛）
- POST /risk/var-backtest  VaR 穿透率回测（Kupiec 覆盖检验）
- POST /risk/drawdown      回撤归因（最大回撤/持续期/最差区间）
- POST /risk/tail          尾部风险与极端相关（尾相依/下跌相关性）
- POST /risk/liquidity     流动性风险（平方根冲击成本/变现天数）
- POST /risk/concentration 持仓集中度（HHI/有效持仓数/Top-N）
均鉴权。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..risk import analytics as ra

router = APIRouter()


class VarRequest(BaseModel):
    returns: List[float]
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0)
    method: str = "historical"
    n_sims: int = 10000
    seed: int = 12345


class VarBacktestRequest(BaseModel):
    returns: List[float]
    confidence: float = Field(default=0.95, gt=0.0, lt=1.0)
    method: str = "historical"


class DrawdownRequest(BaseModel):
    returns: List[float]


class TailRequest(BaseModel):
    returns_a: List[float]
    returns_b: List[float]
    alpha: float = Field(default=0.05, gt=0.0, lt=0.5)


class LiquidityRequest(BaseModel):
    positions: Dict[str, Dict]
    adv: Dict[str, float]
    participation: float = 0.1
    impact_coef: float = 0.1


class ConcentrationRequest(BaseModel):
    weights: Dict[str, float]


@router.post("/risk/var", summary="VaR / CVaR（V42）")
def var_endpoint(req: VarRequest, user=Depends(get_current_user)):
    try:
        return ra.var_cvar(req.returns, req.confidence, req.method, req.n_sims, req.seed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/risk/var-backtest", summary="VaR 穿透率回测（V42）")
def var_backtest_endpoint(req: VarBacktestRequest, user=Depends(get_current_user)):
    try:
        return ra.var_backtest(req.returns, req.confidence, req.method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/risk/drawdown", summary="回撤归因（V43）")
def drawdown_endpoint(req: DrawdownRequest, user=Depends(get_current_user)):
    try:
        return ra.drawdown_analysis(req.returns)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/risk/tail", summary="尾部风险与极端相关（V44）")
def tail_endpoint(req: TailRequest, user=Depends(get_current_user)):
    try:
        return ra.tail_risk(req.returns_a, req.returns_b, req.alpha)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/risk/liquidity", summary="流动性风险（V45）")
def liquidity_endpoint(req: LiquidityRequest, user=Depends(get_current_user)):
    try:
        return ra.liquidity_risk(req.positions, req.adv, req.participation, req.impact_coef)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/risk/concentration", summary="持仓集中度（V46）")
def concentration_endpoint(req: ConcentrationRequest, user=Depends(get_current_user)):
    try:
        return ra.concentration(req.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
