"""报告与运维增强 API 端点（/api/reports/*）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..reports import analytics as rep

router = APIRouter()


class ReportReq(BaseModel):
    returns: List[float]
    equity: Optional[List[float]] = None
    benchmark: Optional[List[float]] = None
    periods_per_year: int = 252
    confidence: float = 0.95


class CompareReq(BaseModel):
    report_a: Dict[str, Any]
    report_b: Dict[str, Any]
    name_a: str = "A"
    name_b: str = "B"


class MultiReq(BaseModel):
    curves: Dict[str, List[float]]
    periods_per_year: int = 252
    confidence: float = 0.95


class PeriodicReq(BaseModel):
    returns: List[float]
    dates: List[str]
    freq: str = "M"
    periods_per_year: int = 252


class DashboardReq(BaseModel):
    returns: List[float]
    weights: Optional[Dict[str, float]] = None
    benchmark: Optional[List[float]] = None
    confidence: float = 0.95
    periods_per_year: int = 252


@router.post("/reports/performance")
def api_report(req: ReportReq, _: str = Depends(get_current_user)):
    try:
        return rep.build_performance_report(
            req.returns, req.equity, req.benchmark, req.periods_per_year, req.confidence
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reports/compare")
def api_compare(req: CompareReq, _: str = Depends(get_current_user)):
    return rep.compare_reports(req.report_a, req.report_b, req.name_a, req.name_b)


@router.post("/reports/multi-compare")
def api_multi(req: MultiReq, _: str = Depends(get_current_user)):
    try:
        return rep.multi_compare(req.curves, req.periods_per_year, req.confidence)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reports/periodic")
def api_periodic(req: PeriodicReq, _: str = Depends(get_current_user)):
    try:
        return rep.periodic_report(req.returns, req.dates, req.freq, req.periods_per_year)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/reports/dashboard")
def api_dashboard(req: DashboardReq, _: str = Depends(get_current_user)):
    try:
        return rep.risk_dashboard(
            req.returns, req.weights, req.benchmark, req.confidence, req.periods_per_year
        )
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))
