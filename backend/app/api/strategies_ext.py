"""策略库扩展 API（V52–V56）。

端点：
- POST /strategy/pairs-coint       协整检验（Engle-Granger + ADF）
- POST /strategy/pairs-backtest    配对交易回测（z-score 信号）
- POST /strategy/option-price      期权 BS 价格
- POST /strategy/option-greeks     期权 Greeks
- POST /strategy/option-implied-vol 隐含波动率
- POST /strategy/grid-backtest     网格交易回测
- POST /strategy/dca-backtest       定投(DCA)回测
- POST /strategy/multi-trend        多资产趋势跟随回测

均鉴权。
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..backtest import strategy_ext as sx

router = APIRouter()


# ---- V52 配对协整 ----
class PairsCointRequest(BaseModel):
    y: List[float]
    x: List[float]


@router.post("/strategy/pairs-coint", summary="协整检验（V52）")
def pairs_coint_endpoint(req: PairsCointRequest, user=Depends(get_current_user)):
    try:
        return sx.pairs_cointegration(req.y, req.x)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


class PairsBacktestRequest(BaseModel):
    y: List[float]
    x: List[float]
    entry_z: float = 2.0
    exit_z: float = 0.5
    window: int = 60


@router.post("/strategy/pairs-backtest", summary="配对交易回测（V52）")
def pairs_backtest_endpoint(req: PairsBacktestRequest, user=Depends(get_current_user)):
    try:
        return sx.pairs_backtest(req.y, req.x, req.entry_z, req.exit_z, req.window)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V53 期权 ----
class OptionPriceRequest(BaseModel):
    S: float = Field(gt=0)
    K: float = Field(gt=0)
    T: float = Field(gt=0)
    r: float = 0.02
    sigma: float = Field(gt=0)
    option: str = "call"


@router.post("/strategy/option-price", summary="期权 BS 价格（V53）")
def option_price_endpoint(req: OptionPriceRequest, user=Depends(get_current_user)):
    return {"price": round(sx.bs_price(req.S, req.K, req.T, req.r, req.sigma, req.option), 4)}


@router.post("/strategy/option-greeks", summary="期权 Greeks（V53）")
def option_greeks_endpoint(req: OptionPriceRequest, user=Depends(get_current_user)):
    return sx.bs_greeks(req.S, req.K, req.T, req.r, req.sigma, req.option)


class ImpliedVolRequest(BaseModel):
    price: float = Field(gt=0)
    S: float = Field(gt=0)
    K: float = Field(gt=0)
    T: float = Field(gt=0)
    r: float = 0.02
    option: str = "call"


@router.post("/strategy/option-implied-vol", summary="隐含波动率（V53）")
def option_iv_endpoint(req: ImpliedVolRequest, user=Depends(get_current_user)):
    return {"implied_vol": sx.implied_vol(req.price, req.S, req.K, req.T, req.r, req.option)}


# ---- V54 网格 ----
class GridBacktestRequest(BaseModel):
    prices: List[float]
    lower: float
    upper: float
    n_grid: int = 10
    lot: float = 1.0
    initial_cash: float = 1_000_000.0


@router.post("/strategy/grid-backtest", summary="网格交易回测（V54）")
def grid_backtest_endpoint(req: GridBacktestRequest, user=Depends(get_current_user)):
    try:
        return sx.grid_backtest(req.prices, req.lower, req.upper, req.n_grid, req.lot, req.initial_cash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V55 DCA ----
class DcaBacktestRequest(BaseModel):
    prices: List[float]
    dates: Optional[List[str]] = None
    periodic_investment: float = 10_000.0
    freq: str = "M"
    initial_cash: float = 0.0


@router.post("/strategy/dca-backtest", summary="定投(DCA)回测（V55）")
def dca_backtest_endpoint(req: DcaBacktestRequest, user=Depends(get_current_user)):
    try:
        return sx.dca_backtest(req.prices, req.dates, req.periodic_investment, req.freq, req.initial_cash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


# ---- V56 多资产趋势跟随 ----
class MultiTrendRequest(BaseModel):
    returns: List[List[float]]
    assets: List[str]
    prices: Optional[List[List[float]]] = None
    fast: int = 20
    slow: int = 60
    rebalance: str = "M"
    initial_cash: float = 1_000_000.0


@router.post("/strategy/multi-trend", summary="多资产趋势跟随（V56）")
def multi_trend_endpoint(req: MultiTrendRequest, user=Depends(get_current_user)):
    try:
        return sx.multi_trend_backtest(req.returns, req.assets, req.prices, req.fast, req.slow, req.rebalance, req.initial_cash)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
