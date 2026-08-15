"""工作流定时调度 API（V1.2）。

GET    /api/schedules             列表
POST   /api/schedules             创建（name / trigger_type / trigger_cfg / payload / enabled）
DELETE /api/schedules/{id}        删除
POST   /api/schedules/{id}/run     立即触发一次
POST   /api/schedules/{id}/toggle  启用/停用
均需鉴权。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..core.scheduler import ScheduleValidationError, workflow_scheduler
from ..market.scheduler import data_sync_service
from ..alerts import scheduler as alert_scheduler

router = APIRouter()


class ScheduleCreate(BaseModel):
    name: str = Field(..., description="计划名称")
    trigger_type: str = Field(..., description="cron | interval")
    trigger_cfg: str = Field(..., description="cron 表达式 或 interval 的 JSON {\"minutes\": N}")
    payload: Dict[str, Any] = Field(..., description="工作流 {nodes, edges, workflow_name}")
    enabled: bool = True


class ToggleIn(BaseModel):
    enabled: bool


@router.get("/schedules", summary="定时计划列表")
def list_schedules(_user=Depends(get_current_user)) -> list[dict]:
    return workflow_scheduler.list_schedules()


@router.post("/schedules", status_code=201, summary="创建定时计划")
def create_schedule(req: ScheduleCreate, _user=Depends(get_current_user)) -> dict:
    try:
        return workflow_scheduler.create_schedule(
            name=req.name,
            trigger_type=req.trigger_type,
            trigger_cfg=req.trigger_cfg,
            payload=req.payload,
            enabled=req.enabled,
        )
    except ScheduleValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from None


@router.delete("/schedules/{schedule_id}", status_code=204, summary="删除计划")
def delete_schedule(schedule_id: str, _user=Depends(get_current_user)) -> None:
    if workflow_scheduler.get_schedule(schedule_id) is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    workflow_scheduler.remove_schedule(schedule_id)


@router.post("/schedules/{schedule_id}/run", summary="立即触发一次")
def run_now(schedule_id: str, _user=Depends(get_current_user)) -> dict:
    try:
        return workflow_scheduler.run_now(schedule_id)
    except ScheduleValidationError:
        raise HTTPException(status_code=404, detail="计划不存在") from None


@router.post("/schedules/{schedule_id}/toggle", summary="启用/停用")
def toggle(schedule_id: str, body: ToggleIn, _user=Depends(get_current_user)) -> dict:
    rec = workflow_scheduler.set_enabled(schedule_id, body.enabled)
    if rec is None:
        raise HTTPException(status_code=404, detail="计划不存在")
    return rec


@router.get("/schedules/center", summary="调度中心总览（V5.2）")
def center(_user=Depends(get_current_user)) -> dict:
    """聚合三类调度：工作流定时计划 + 行情自动同步 + 预警自动巡检。"""
    return {
        "workflow_schedules": workflow_scheduler.list_schedules(),
        "data_sync": data_sync_service.status(),
        "alert_eval": alert_scheduler.status(),
    }
