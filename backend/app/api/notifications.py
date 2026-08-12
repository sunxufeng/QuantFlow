"""通知配置 API（V1.1 N5）。

GET    /api/notifications              列出已配置渠道
POST   /api/notifications              新增渠道（type/name/config）
DELETE /api/notifications/{id}         删除渠道
POST   /api/notifications/{id}/test    向该渠道发送测试通知
均需鉴权。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..notifications.service import notification_service

router = APIRouter()


class ChannelCreate(BaseModel):
    type: str = Field(..., description="webhook | feishu")
    name: str
    config: Dict[str, Any] = Field(default_factory=dict)


class ChannelOut(BaseModel):
    id: str
    type: str
    name: str
    config: Dict[str, Any]
    enabled: bool
    created_at: str


@router.get("/notifications", response_model=list[ChannelOut])
def list_channels(user=Depends(get_current_user)) -> list:
    return notification_service.list()


@router.post("/notifications", response_model=ChannelOut, status_code=201)
def create_channel(req: ChannelCreate, user=Depends(get_current_user)) -> dict:
    try:
        return notification_service.configure(req.type, req.name, req.config)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.delete("/notifications/{channel_id}", status_code=204)
def delete_channel(channel_id: str, user=Depends(get_current_user)) -> None:
    if not notification_service.remove(channel_id):
        raise HTTPException(status_code=404, detail="渠道不存在")


@router.post("/notifications/{channel_id}/test", status_code=202)
def test_channel(channel_id: str, user=Depends(get_current_user)) -> dict:
    try:
        notification_service.test_send(channel_id)
    except KeyError:
        raise HTTPException(status_code=404, detail="渠道不存在")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc))
    return {"status": "sent"}
