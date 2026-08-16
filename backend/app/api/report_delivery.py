"""定时报告自动投递 API（V102）。

- ``POST   /api/reports/deliver``            一次性生成并推送一份报告
- ``GET    /api/reports/delivery-jobs``       投递任务列表
- ``POST   /api/reports/delivery-jobs``       新增投递任务
- ``DELETE /api/reports/delivery-jobs/{id}``  删除任务
- ``POST   /api/reports/delivery-jobs/{id}/toggle`` 启用/停用
- ``POST   /api/reports/delivery-jobs/{id}/run``     立即执行一次
- ``GET    /api/reports/delivery/scheduler``  自动调度状态
均需鉴权。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..reports import delivery as dv
from ..reports.delivery_scheduler import (
    start as delivery_scheduler_start,
)
from ..reports.delivery_scheduler import (
    status as delivery_scheduler_status,
)
from ..reports.delivery_scheduler import (
    trigger_now as delivery_trigger_now,
)

router = APIRouter()


class DeliverReq(BaseModel):
    report_type: str = Field(..., description="performance | risk | periodic | consolidate")
    params: Dict[str, Any] = Field(default_factory=dict)


class DeliveryJobCreate(BaseModel):
    name: str
    report_type: str
    params: Dict[str, Any] = Field(default_factory=dict)
    interval_minutes: int = 60
    enabled: bool = True


class DeliveryJobToggle(BaseModel):
    enabled: bool


@router.post("/reports/deliver", summary="一次性生成并推送报告")
def deliver(req: DeliverReq, _: str = Depends(get_current_user)) -> dict:
    try:
        return dv.deliver_report(req.report_type, req.params)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/reports/delivery-jobs", summary="投递任务列表")
def list_jobs(_: str = Depends(get_current_user)) -> list[dict]:
    return dv.delivery_service.list_jobs()


@router.post("/reports/delivery-jobs", status_code=201, summary="新增投递任务")
def create_job(req: DeliveryJobCreate, _: str = Depends(get_current_user)) -> dict:
    try:
        return dv.delivery_service.create_job(
            name=req.name,
            report_type=req.report_type,
            params=req.params,
            interval_minutes=req.interval_minutes,
            enabled=req.enabled,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/reports/delivery-jobs/{job_id}", status_code=204, summary="删除任务")
def delete_job(job_id: str, _: str = Depends(get_current_user)) -> None:
    if not dv.delivery_service.delete_job(job_id):
        raise HTTPException(status_code=404, detail="任务不存在")


@router.post("/reports/delivery-jobs/{job_id}/toggle", summary="启用/停用")
def toggle_job(job_id: str, body: DeliveryJobToggle, _: str = Depends(get_current_user)) -> dict:
    if not dv.delivery_service.set_enabled(job_id, body.enabled):
        raise HTTPException(status_code=404, detail="任务不存在")
    return dv.delivery_service.get_job(job_id)


@router.post("/reports/delivery-jobs/{job_id}/run", summary="立即执行一次")
def run_job(job_id: str, _: str = Depends(get_current_user)) -> dict:
    try:
        return dv.delivery_service.run_job(job_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/reports/delivery/scheduler", summary="报告投递自动调度状态")
def scheduler_status(_: str = Depends(get_current_user)) -> dict:
    return delivery_scheduler_status()


@router.post("/reports/delivery/scheduler/trigger", summary="立即触发一次自动投递")
def scheduler_trigger(_: str = Depends(get_current_user)) -> dict:
    return delivery_trigger_now()


@router.post("/reports/delivery/scheduler/start", summary="启动自动投递调度")
def scheduler_start(_: str = Depends(get_current_user)) -> dict:
    delivery_scheduler_start()
    return delivery_scheduler_status()
