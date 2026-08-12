"""因子分析 API（V1.1 N3）。

POST /api/factors/analyze —— 对任意「因子 + 下期收益」宽表做系统分析（IC/ICIR/衰减/分层收益/自相关）。
支持三种输入：
  1. table: {"columns": [...], "rows": [...]}（DataTable 契约）
  2. rows + columns 平铺
  3. symbols + start + end（+ 可选 expression）：直接拉取行情构建动量因子与下期收益
需鉴权（与 N2 API Token / JWT 双通道一致）。
"""

from __future__ import annotations

import pandas as pd
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..factors.analyzer import FactorAnalyzer
from ..market.service import market_service

router = APIRouter()


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
