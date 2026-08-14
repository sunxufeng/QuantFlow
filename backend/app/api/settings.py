"""通用设置 API（V1.7）：券商凭证配置等。"""

from __future__ import annotations

from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user, require_roles
from ..core.broker.config import (
    SUPPORTED_BROKERS,
    load_broker_config,
    mask_secret,
    save_broker_config,
)
from ..core.broker.connectivity import test_broker_config

router = APIRouter(prefix="/settings", tags=["settings"])


class BrokerConfigIn(BaseModel):
    broker: str = Field(default="none")
    api_key: str = ""
    api_secret: str = ""
    base_url: str = ""
    account_id: str = ""
    extra: Dict[str, Any] = Field(default_factory=dict)


def _public(cfg: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "broker": cfg.get("broker", "none"),
        "api_key": mask_secret(cfg.get("api_key", "")),
        "api_secret": mask_secret(cfg.get("api_secret", "")),
        "base_url": cfg.get("base_url", ""),
        "account_id": mask_secret(cfg.get("account_id", "")),
        "extra": cfg.get("extra", {}) or {},
        "configured": bool(cfg.get("api_key")),
    }


@router.get("/broker", summary="读取券商凭证配置")
def get_broker(user: dict = Depends(get_current_user)) -> dict:
    return _public(load_broker_config())


@router.put("/broker", summary="保存券商凭证配置")
def put_broker(
    req: BrokerConfigIn,
    _user: dict = Depends(require_roles("admin")),
) -> dict:
    if req.broker not in SUPPORTED_BROKERS:
        raise HTTPException(status_code=400, detail=f"不支持的券商类型：{req.broker}")
    saved = save_broker_config(req.model_dump())
    return _public(saved)


@router.post("/broker/test", summary="测试券商凭证连通性")
def test_broker(
    req: Optional[BrokerConfigIn] = None,
    _user: dict = Depends(get_current_user),
) -> dict:
    """用当前（或传入的部分覆盖）配置做一次连通性验证，不落库。"""
    cfg = load_broker_config()
    if req is not None:
        for key in ("broker", "api_key", "base_url", "account_id", "extra"):
            val = getattr(req, key)
            if val not in (None, ""):
                cfg[key] = val
        if req.api_secret:
            cfg["api_secret"] = req.api_secret
    return test_broker_config(cfg)
