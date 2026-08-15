"""因子工程深化 API（V37–V41）。

端点：
- POST /factors/orthogonalize     单因子对其余因子正交化（去冗余）
- POST /factors/orthogonalize-all 全体因子 Gram-Schmidt 正交基
- POST /factors/timing            因子波动率择时（对比择时 vs 静态夏普）
- POST /factors/crowding          因子拥挤度（自相关+波动→拥挤指数）
- POST /factors/combine           多因子合成（等权/逆波动/正交/自定义）
- POST /factors/turnover          因子换手率与稳定性（横截面排名）
均鉴权；输入为因子收益序列或因子值矩阵（dict）。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..factors import engineering as eng

router = APIRouter()


class OrthoRequest(BaseModel):
    target: str
    factor_returns: Dict[str, List[float]]


class TimingRequest(BaseModel):
    factor_returns: Dict[str, List[float]]
    method: str = "vol"
    halflife: int = 21


class CrowdingRequest(BaseModel):
    factor_returns: Dict[str, List[float]]
    lags: List[int] = Field(default=[1, 2])


class CombineRequest(BaseModel):
    factor_returns: Dict[str, List[float]]
    method: str = "equal"
    weights: Optional[List[float]] = None


class TurnoverRequest(BaseModel):
    factor_values: Dict[str, List[float]]


@router.post("/factors/orthogonalize", summary="因子正交化（V37）")
def orthogonalize(req: OrthoRequest, user=Depends(get_current_user)):
    try:
        return eng.orthogonalize_factor(req.target, req.factor_returns)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/orthogonalize-all", summary="因子全体正交化（V37）")
def orthogonalize_all(req: OrthoRequest, user=Depends(get_current_user)):
    try:
        return eng.orthogonalize_all(req.factor_returns)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/timing", summary="因子择时（V38）")
def timing(req: TimingRequest, user=Depends(get_current_user)):
    try:
        return eng.factor_timing(req.factor_returns, req.method, req.halflife)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/crowding", summary="因子拥挤度（V39）")
def crowding(req: CrowdingRequest, user=Depends(get_current_user)):
    try:
        return eng.factor_crowding(req.factor_returns, req.lags)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/combine", summary="多因子合成（V40）")
def combine(req: CombineRequest, user=Depends(get_current_user)):
    try:
        return eng.combine_factors(req.factor_returns, req.method, req.weights)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/factors/turnover", summary="因子换手率与稳定性（V41）")
def turnover(req: TurnoverRequest, user=Depends(get_current_user)):
    try:
        return eng.factor_turnover(req.factor_values)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
