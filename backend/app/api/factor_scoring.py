"""因子评分 API（V2.5）。

在 V1.1 因子分析（IC/分层）能力之外，新增「横截面因子评分与排序」：
直接对一组标的的行情计算内置因子，标准化后加权合成综合分并排名。

- GET  /api/factors/scoring/catalog : 内置因子目录
- POST /api/factors/scoring/score   : 对一组标的做因子评分与排序
"""

from __future__ import annotations

from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..factors import research as factor_research
from ..factors.registry import FactorNotFoundError, list_factors
from ..factors.scoring import FactorScoreConfigError, score

router = APIRouter(prefix="/factors", tags=["factor-scoring"], dependencies=[Depends(get_current_user)])


class FactorSpec(BaseModel):
    name: str
    window: Optional[int] = None
    direction: Optional[int] = None
    weight: Optional[float] = None


class ScoreRequest(BaseModel):
    symbols: List[str] = Field(..., min_length=1, description="参与评分的标的列表")
    factors: Optional[List[FactorSpec]] = Field(
        None, description="因子规格；留空则使用全部默认因子等权"
    )
    start: Optional[str] = Field(None, description="行情起始日期 YYYY-MM-DD")
    end: Optional[str] = Field(None, description="行情结束日期 YYYY-MM-DD")
    method: str = Field("rank", description="标准化方法：rank（百分位）或 zscore")


@router.get("/scoring/catalog", summary="内置因子目录（V2.5）")
def scoring_catalog() -> dict:
    return {"items": list_factors()}


@router.post("/scoring/score", summary="因子评分与排序（V2.5）")
def scoring_score(payload: ScoreRequest) -> dict:
    try:
        result = score(
            symbols=payload.symbols,
            factors=[f.model_dump(exclude_none=True) for f in (payload.factors or [])] or None,
            start=payload.start,
            end=payload.end,
            method=payload.method,
        )
    except FactorScoreConfigError as exc:
        raise HTTPException(status_code=422, detail=exc.message) from None
    except FactorNotFoundError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from None
    return result


# --------------------------------------------------------------------------- #
# 因子研究（V2.9）：相关性矩阵 + IC/IR
# --------------------------------------------------------------------------- #
def _parse_symbols(raw) -> Optional[List[str]]:
    if not raw:
        return None
    return [s.strip() for s in raw.split(",") if s.strip()]


@router.get("/research/matrix", summary="因子相关性矩阵（V2.9）")
def research_matrix(
    symbols: Optional[str] = None,
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
) -> dict:
    return factor_research.correlation_matrix(
        symbols=_parse_symbols(symbols), start=start, end=end, window=window
    )


@router.get("/research/ic", summary="因子 IC / IR 分析（V2.9）")
def research_ic(
    symbols: Optional[str] = None,
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
    forward: int = 1,
) -> dict:
    return factor_research.ic_analysis(
        symbols=_parse_symbols(symbols),
        start=start,
        end=end,
        window=window,
        forward=forward,
    )


@router.get("/research/ranking", summary="因子排行榜：按 IC/IR 排序（V3.2）")
def research_ranking(
    symbols: Optional[str] = None,
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
    forward: int = 1,
    metric: str = "mean_ic",
    order: str = "desc",
) -> dict:
    """对所有内置因子按 IC/IR 指标排序，连接 V2.8 排行榜与 V2.9 因子研究。"""
    if order not in ("asc", "desc"):
        order = "desc"
    return factor_research.factor_ranking(
        symbols=_parse_symbols(symbols),
        start=start,
        end=end,
        window=window,
        forward=forward,
        metric=metric,
        order=order,
    )
