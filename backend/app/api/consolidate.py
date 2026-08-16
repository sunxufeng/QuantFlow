"""V97 综合报告聚合 API：/reports/consolidate。"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..reports.consolidate import consolidate_report

router = APIRouter()


class ConsolidateReq(BaseModel):
    returns: List[float]
    weights: Optional[Dict[str, float]] = None
    benchmark: Optional[List[float]] = None
    periods_per_year: int = 252
    confidence: float = 0.95


@router.post("/reports/consolidate")
def api_consolidate(req: ConsolidateReq, _: str = Depends(get_current_user)):
    """综合报告：聚合绩效 / 风险 / 看板为一份多章节报告（复用 analytics 纯函数）。"""
    try:
        return consolidate_report(
            req.returns, req.weights, req.benchmark, req.periods_per_year, req.confidence
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
