"""组合监控与预警 API 端点（/api/monalert/*，避免与 /api/monitor 系统监控冲突）。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..monitoring import alerts as ma
from ..monitoring import monalert_service as msa
from ..monitoring.monalert_scheduler import start as monalert_scheduler_start
from ..monitoring.monalert_scheduler import status as monalert_scheduler_status
from ..monitoring.monalert_scheduler import trigger_now as monalert_trigger_now

router = APIRouter()


class DriftReq(BaseModel):
    weights: List[float]
    target: List[float]
    asset_names: Optional[List[str]] = None
    threshold: float = 0.05


class ReturnQualityReq(BaseModel):
    returns: List[float]
    hit_rate_limit: float = 0.45
    payoff_ratio_limit: float = 0.8


class TeReq(BaseModel):
    returns_port: List[float]
    returns_bench: List[float]
    window: int = 20
    limit: float = 0.05


class SectorReq(BaseModel):
    group_weights: Dict[str, float]
    limit: float = 0.6


class BudgetReq(BaseModel):
    weights: List[float]
    cov: List[List[float]]
    target_budget: Optional[List[float]] = None
    asset_names: Optional[List[str]] = None


@router.post("/monalert/drift")
def api_drift(req: DriftReq, _: str = Depends(get_current_user)):
    try:
        return ma.drift_monitor(req.weights, req.target, req.asset_names, req.threshold)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/return-quality")
def api_return_quality(req: ReturnQualityReq, _: str = Depends(get_current_user)):
    try:
        return ma.return_quality_monitor(req.returns, req.hit_rate_limit, req.payoff_ratio_limit)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/tracking-error")
def api_te(req: TeReq, _: str = Depends(get_current_user)):
    try:
        return ma.tracking_error_monitor(req.returns_port, req.returns_bench, req.window, req.limit)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/sector-exposure")
def api_sector(req: SectorReq, _: str = Depends(get_current_user)):
    try:
        return ma.sector_exposure_monitor(req.group_weights, req.limit)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/monalert/risk-budget")
def api_budget(req: BudgetReq, _: str = Depends(get_current_user)):
    try:
        return ma.risk_budget_monitor(req.weights, req.cov, req.target_budget, req.asset_names)
    except ValueError as e:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail=str(e))


# --------------------------------------------------------------------------- #
# V101 监控告警规则 + 自动评估调度
# --------------------------------------------------------------------------- #
class MonitorRuleCreate(BaseModel):
    name: str
    monitor_type: str
    params: Dict[str, Any]
    cooldown_minutes: int = 60
    enabled: bool = True


class MonitorRuleToggle(BaseModel):
    enabled: bool


@router.get("/monalert/rules", summary="监控告警规则列表")
def list_monitor_rules(_: str = Depends(get_current_user)) -> List[dict]:
    return msa.monitor_alert_service.list_rules()


@router.post("/monalert/rules", status_code=201, summary="新增监控告警规则")
def create_monitor_rule(req: MonitorRuleCreate, _: str = Depends(get_current_user)) -> dict:
    try:
        return msa.monitor_alert_service.create_rule(
            name=req.name,
            monitor_type=req.monitor_type,
            params=req.params,
            cooldown_minutes=req.cooldown_minutes,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/monalert/rules/{rule_id}", status_code=204, summary="删除规则")
def delete_monitor_rule(rule_id: str, _: str = Depends(get_current_user)) -> None:
    if not msa.monitor_alert_service.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")


@router.post("/monalert/rules/{rule_id}/toggle", summary="启用/停用")
def toggle_monitor_rule(rule_id: str, body: MonitorRuleToggle, _: str = Depends(get_current_user)) -> dict:
    if not msa.monitor_alert_service.set_enabled(rule_id, body.enabled):
        raise HTTPException(status_code=404, detail="规则不存在")
    return msa.monitor_alert_service.get_rule(rule_id)


@router.post("/monalert/evaluate", summary="立即评估全部监控告警规则")
def evaluate_monitor_rules(_: str = Depends(get_current_user)) -> dict:
    return monalert_trigger_now()


@router.get("/monalert/scheduler", summary="监控告警自动评估调度状态")
def monitor_alert_scheduler_status(_: str = Depends(get_current_user)) -> dict:
    return monalert_scheduler_status()


@router.post("/monalert/scheduler/start", summary="启动监控告警自动评估调度")
def start_monitor_alert_scheduler(_: str = Depends(get_current_user)) -> dict:
    monalert_scheduler_start()
    return monalert_scheduler_status()
