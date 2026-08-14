"""预警规则 API（V2.3）。

- ``GET    /api/alerts``               列出预警规则
- ``POST   /api/alerts``               新增规则
- ``DELETE /api/alerts/{id}``          删除规则
- ``POST   /api/alerts/{id}/toggle``  启用/停用
- ``POST   /api/alerts/evaluate``      立即评估全部启用规则（触发通知）
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..alerts import alert_service
from ..core.auth import get_current_user

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(get_current_user)],
)


class AlertCreate(BaseModel):
    name: str = Field(..., description="规则名称")
    symbol: str = Field(..., description="标的代码，如 TEST.STOCK")
    metric: str = Field(default="price", description="price | daily_change_pct")
    operator: str = Field(default=">", description="> < >= <= cross_above cross_below")
    threshold: float = Field(default=0.0, description="阈值")
    cooldown_minutes: int = Field(default=60, gt=0, description="触发后冷却分钟数（去重）")
    enabled: bool = Field(default=True, description="是否启用")


class ToggleRequest(BaseModel):
    enabled: bool


@router.get("", summary="列出预警规则")
def list_alerts() -> Dict[str, Any]:
    return {"items": alert_service.list_rules()}


@router.post("", summary="新增预警规则", status_code=201)
def create_alert(req: AlertCreate) -> Dict[str, Any]:
    try:
        return alert_service.create_rule(
            name=req.name,
            symbol=req.symbol,
            metric=req.metric,
            operator=req.operator,
            threshold=req.threshold,
            cooldown_minutes=req.cooldown_minutes,
            enabled=req.enabled,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.delete("/{rule_id}", summary="删除预警规则", status_code=204)
def delete_alert(rule_id: str) -> None:
    if not alert_service.delete_rule(rule_id):
        raise HTTPException(status_code=404, detail="规则不存在")


@router.post("/{rule_id}/toggle", summary="启用/停用规则")
def toggle_alert(rule_id: str, req: ToggleRequest) -> Dict[str, Any]:
    if not alert_service.set_enabled(rule_id, req.enabled):
        raise HTTPException(status_code=404, detail="规则不存在")
    return alert_service.get_rule(rule_id)


@router.post("/evaluate", summary="立即评估全部启用规则")
def evaluate_alerts() -> Dict[str, Any]:
    results = alert_service.evaluate_all()
    notified = sum(1 for r in results if r.get("notified"))
    return {"evaluated": len(results), "notified": notified, "results": results}
