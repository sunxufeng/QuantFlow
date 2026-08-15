"""市场状态与择时 API（V47–V51）。

端点：
- POST /market/regime            市场状态检测（趋势+波动率区制，含滚动序列）
- POST /market/vol-forecast       波动率预测（EWMA / GARCH(1,1) 多步向前）
- POST /market/sector-rotation    板块轮动信号（相对强度/动量排序 + 超配低配）
- POST /market/correlation-network 相关性聚类网络（层次聚类 + 板块内外相关）
- POST /market/etf-rotation       ETF 动量轮动回测（Top-N 动量轮动 vs 等权基准）

均鉴权。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..market import regime as mr

router = APIRouter()


# ---- V47 市场状态检测 ----
class RegimeRequest(BaseModel):
    returns: List[float]
    dates: Optional[List[str]] = None
    short_ma: int = 20
    long_ma: int = 60
    vol_window: int = 20
    sideways_band: float = 0.02


@router.post("/market/regime", summary="市场状态检测（V47）")
def regime_endpoint(req: RegimeRequest, user=Depends(get_current_user)):
    try:
        return mr.detect_regime(req.returns, req.dates, req.short_ma, req.long_ma, req.vol_window, req.sideways_band)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V48 波动率预测 ----
class VolForecastRequest(BaseModel):
    returns: List[float]
    method: str = "ewma"
    lam: float = 0.94
    horizon: int = Field(default=21, ge=1, le=252)
    garch_omega: float = 1e-5
    garch_alpha: float = 0.08
    garch_beta: float = 0.90


@router.post("/market/vol-forecast", summary="波动率预测（V48）")
def vol_forecast_endpoint(req: VolForecastRequest, user=Depends(get_current_user)):
    try:
        return mr.forecast_volatility(req.returns, req.method, req.lam, req.horizon, req.garch_omega, req.garch_alpha, req.garch_beta)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V49 板块轮动 ----
class SectorRotationRequest(BaseModel):
    sector_returns: Dict[str, List[float]]
    window: int = 60
    method: str = "relative_strength"


@router.post("/market/sector-rotation", summary="板块轮动信号（V49）")
def sector_rotation_endpoint(req: SectorRotationRequest, user=Depends(get_current_user)):
    try:
        return mr.sector_rotation(req.sector_returns, req.window, req.method)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V50 相关性聚类网络 ----
class CorrelationNetworkRequest(BaseModel):
    returns: List[List[float]]
    assets: List[str]
    method: str = "average"
    n_clusters: Optional[int] = None


@router.post("/market/correlation-network", summary="相关性聚类网络（V50）")
def correlation_network_endpoint(req: CorrelationNetworkRequest, user=Depends(get_current_user)):
    try:
        return mr.correlation_network(req.returns, req.assets, req.method, req.n_clusters)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V51 ETF 动量轮动回测 ----
class EtfRotationRequest(BaseModel):
    returns: List[List[float]]
    assets: List[str]
    dates: Optional[List[str]] = None
    lookback: int = 20
    hold_top: int = 1
    rebalance: str = "M"
    initial_cash: float = 1_000_000.0


@router.post("/market/etf-rotation", summary="ETF 动量轮动回测（V51）")
def etf_rotation_endpoint(req: EtfRotationRequest, user=Depends(get_current_user)):
    try:
        return mr.etf_momentum_rotation(req.returns, req.assets, req.dates, req.lookback, req.hold_top, req.rebalance, req.initial_cash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
