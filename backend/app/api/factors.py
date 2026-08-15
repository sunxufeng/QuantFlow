"""因子分析 API（V1.1 N3）。

POST /api/factors/analyze —— 对任意「因子 + 下期收益」宽表做系统分析（IC/ICIR/衰减/分层收益/自相关）。
支持三种输入：
  1. table: {"columns": [...], "rows": [...]}（DataTable 契约）
  2. rows + columns 平铺
  3. symbols + start + end（+ 可选 expression）：直接拉取行情构建动量因子与下期收益
需鉴权（与 N2 API Token / JWT 双通道一致）。
"""

from __future__ import annotations

from typing import Optional

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..factors.analyzer import FactorAnalyzer
from ..factors import backtest as factor_backtest
from ..factors import library as factor_library
from ..factors.registry import FactorNotFoundError
from ..market.service import market_service

router = APIRouter()


# ----------------------------- 因子库 CRUD（V1.1 N3） -----------------------------


class FactorCreateRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="因子名称")
    expression: str = Field(..., min_length=1, description="pandas 表达式，如 close.pct_change(20)")
    category: str = Field(default="自定义", max_length=40, description="类别")
    description: str = Field(default="", max_length=500, description="说明")
    params: dict = Field(default_factory=dict, description="附加参数（JSON）")


class FactorUpdateRequest(BaseModel):
    name: Optional[str] = Field(None, min_length=1, max_length=80)
    expression: Optional[str] = Field(None, min_length=1)
    category: Optional[str] = Field(None, max_length=40)
    description: Optional[str] = Field(None, max_length=500)
    params: Optional[dict] = None


@router.get("/factors/library", summary="因子库列表（V1.1 N3）")
def list_factor_library(
    category: Optional[str] = None,
    user=Depends(get_current_user),
) -> dict:
    items = factor_library.list_factors(owner_id=user["id"], category=category)
    return {"items": items, "total": len(items)}


@router.post("/factors/library", summary="新建因子定义（V1.1 N3）", status_code=201)
def create_factor_definition(
    req: FactorCreateRequest,
    user=Depends(get_current_user),
) -> dict:
    factor = factor_library.create_factor(
        name=req.name,
        expression=req.expression,
        category=req.category,
        description=req.description,
        params=req.params,
        owner_id=user["id"],
    )
    return factor


@router.get("/factors/library/{factor_id}", summary="因子定义详情（V1.1 N3）")
def get_factor_definition(factor_id: str, user=Depends(get_current_user)) -> dict:
    factor = factor_library.get_factor(factor_id)
    if factor is None:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return factor


@router.put("/factors/library/{factor_id}", summary="更新因子定义（V1.1 N3）")
def update_factor_definition(
    factor_id: str,
    req: FactorUpdateRequest,
    user=Depends(get_current_user),
) -> dict:
    factor = factor_library.update_factor(
        factor_id,
        name=req.name,
        expression=req.expression,
        category=req.category,
        description=req.description,
        params=req.params,
    )
    if factor is None:
        raise HTTPException(status_code=404, detail="因子定义不存在")
    return factor


@router.delete("/factors/library/{factor_id}", summary="删除因子定义（V1.1 N3）", status_code=204)
def delete_factor_definition(factor_id: str, user=Depends(get_current_user)) -> None:
    if not factor_library.delete_factor(factor_id):
        raise HTTPException(status_code=404, detail="因子定义不存在")


class FactorAnalyzeRequest(BaseModel):
    # 直接表格输入
    table: dict | None = Field(None, description="DataTable 契约 {columns, rows}")
    columns: list[str] | None = None
    rows: list[dict] | None = None
    # 行情构建输入
    symbols: list[str] | None = None
    start: str | None = None
    end: str | None = None
    expression: str | None = Field(None, description="因子表达式，默认动量 close.pct_change()")
    # 分析参数
    factor: str = "factor"
    forward_return: str = "fwd_return"
    date: str | None = "date"
    n_quantiles: int = 5
    max_lag: int = 5


class FactorAnalyzeResponse(BaseModel):
    report: dict


def _build_from_market(req: FactorAnalyzeRequest) -> pd.DataFrame:
    """按 symbols 拉取日线，构建动量因子（或自定义表达式）与下期收益。"""
    frames = []
    for sym in req.symbols or []:
        # use_cache=False：因子分析需取最新行情，且避免污染共享行情缓存影响其他用例
        bars = market_service.bars(sym, req.start, req.end, use_cache=False)
        if not bars:
            continue
        d = pd.DataFrame([b.to_dict() for b in bars])
        d["symbol"] = sym
        d = d.sort_values("date")
        d["fwd_return"] = d["close"].pct_change().shift(-1)
        if req.expression:
            d["factor"] = d.eval(req.expression)
        else:
            d["factor"] = d["close"].pct_change()
        frames.append(d[["date", "symbol", "factor", "fwd_return"]].dropna())
    if not frames:
        raise HTTPException(status_code=400, detail="未取到任何行情数据，请检查 symbols/start/end")
    return pd.concat(frames, ignore_index=True)


def _resolve_df(req: FactorAnalyzeRequest) -> pd.DataFrame:
    if req.table:
        return pd.DataFrame(req.table["rows"], columns=req.table["columns"])
    if req.rows is not None and req.columns is not None:
        return pd.DataFrame(req.rows, columns=req.columns)
    if req.symbols:
        return _build_from_market(req)
    raise HTTPException(
        status_code=400,
        detail="需提供 table({columns,rows}) / rows+columns / symbols 之一",
    )


@router.post("/factors/analyze", summary="因子分析", response_model=FactorAnalyzeResponse)
def analyze_factor(
    req: FactorAnalyzeRequest,
    user=Depends(get_current_user),
) -> dict:
    df = _resolve_df(req)
    analyzer = FactorAnalyzer()
    try:
        report = analyzer.analyze(
            df,
            factor_col=req.factor,
            ret_col=req.forward_return,
            date_col=req.date,
            n_quantiles=req.n_quantiles,
            max_lag=req.max_lag,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"report": report}


# ----------------------------- V30：因子回测（多空组合） -----------------------------

class FactorBacktestRequest(BaseModel):
    factor: str = Field(..., description="因子名（内置 momentum/volatility/rsi…）或表达式（如 close.pct_change(20)）")
    universe: list[str] = Field(..., min_length=2, description="股票池")
    start: str = Field(default="2023-01-01", description="开始日 YYYY-MM-DD")
    end: str = Field(default="2023-12-31", description="结束日 YYYY-MM-DD")
    quantiles: int = Field(default=5, ge=2, le=10, description="分组数")
    neutralized: bool = Field(default=False, description="是否横截面中性化（缩尾+zscore）")
    source: str = Field(default="synthetic", description="行情来源：synthetic(离线) / live")
    seed: int = Field(default=12345, description="合成行情随机种子")


@router.get("/factors/backtest/catalog", summary="因子回测可用因子清单（V30）")
def factor_backtest_catalog(user=Depends(get_current_user)) -> dict:
    return {"factors": factor_backtest.factor_catalog()}


@router.post("/factors/backtest", summary="因子多空组合回测（累计收益/IC 时序/指标，V30）")
def factor_backtest_run(
    req: FactorBacktestRequest,
    user=Depends(get_current_user),
) -> dict:
    try:
        result = factor_backtest.factor_long_short(
            factor=req.factor,
            universe=req.universe,
            start=req.start,
            end=req.end,
            quantiles=req.quantiles,
            neutralized=req.neutralized,
            source=req.source,
            seed=req.seed,
        )
    except (ValueError, FactorNotFoundError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return result
