"""通用设置 API（V1.7）：券商凭证配置、系统信息与用户偏好（V6.1）。"""

from __future__ import annotations

import json
import time

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
from ..core.db import db
from ..config import settings as app_settings

router = APIRouter(prefix="/settings", tags=["settings"])

# V6.1 允许用户设置的偏好字段与默认值
DEFAULT_PREFERENCES: Dict[str, Any] = {
    "default_view": "home",   # 登录后默认进入的视图（对应 Sidebar 的 home=概览）
    "theme": "light",              # light | dark
    "preferred_data_source": "fixture",  # fixture | tushare
}
_VALID_VIEWS = {
    "home", "editor", "chart", "data", "monitor", "factor", "factorScore",
    "notify", "llm", "prefs", "templates", "reports", "compare",
    "alerts", "board", "watch", "sched", "trade", "broker",
}
_VALID_THEMES = {"light", "dark"}
_VALID_SOURCES = {"fixture", "tushare"}


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


# --------------------------------------------------------------------------- #
# V6.1 系统信息 + 用户偏好
# --------------------------------------------------------------------------- #

def _load_prefs(user_id: str) -> Dict[str, Any]:
    row = db.query_one("SELECT prefs FROM user_preferences WHERE user_id=?", (user_id,))
    if not row or not row["prefs"]:
        return dict(DEFAULT_PREFERENCES)
    try:
        stored = json.loads(row["prefs"]) or {}
    except (json.JSONDecodeError, TypeError):
        stored = {}
    merged = dict(DEFAULT_PREFERENCES)
    merged.update({k: v for k, v in stored.items() if k in DEFAULT_PREFERENCES})
    return merged


def _save_prefs(user_id: str, prefs: Dict[str, Any]) -> Dict[str, Any]:
    db.execute(
        "INSERT INTO user_preferences(user_id, prefs, updated_at) VALUES(?, ?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET prefs=excluded.prefs, updated_at=excluded.updated_at",
        (user_id, json.dumps(prefs), _now()),
    )
    return prefs


def _now() -> str:
    return time.strftime("%Y-%m-%d %H:%M:%S", time.localtime())


def _system_info() -> Dict[str, Any]:
    """只读系统信息：版本、行情数据源模式、缓存后端、券商概况。"""
    try:
        from ..market.service import market_service
        cache = market_service.cache_summary()
        market = {
            "provider_mode": cache.get("provider_mode"),
            "provider": cache.get("provider"),
            "cache_backend": cache.get("cache_backend"),
        }
    except Exception:
        market = {"provider_mode": None, "provider": None, "cache_backend": None}
    broker = load_broker_config()
    return {
        "app": app_settings.APP_NAME,
        "version": app_settings.APP_VERSION,
        "market": market,
        "broker": {
            "broker": broker.get("broker", "none"),
            "configured": bool(broker.get("api_key")),
        },
    }


@router.get("", summary="读取系统信息与当前用户偏好（V6.1）")
def get_settings(user: dict = Depends(get_current_user)) -> dict:
    return {"system": _system_info(), "preferences": _load_prefs(user["id"])}


class PreferencesIn(BaseModel):
    default_view: Optional[str] = None
    theme: Optional[str] = None
    preferred_data_source: Optional[str] = None


@router.put("", summary="更新当前用户偏好（V6.1，部分字段合并）")
def put_settings(req: PreferencesIn, user: dict = Depends(get_current_user)) -> dict:
    updates = {k: v for k, v in req.model_dump(exclude_unset=True).items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="未提供任何偏好字段")
    if "default_view" in updates and updates["default_view"] not in _VALID_VIEWS:
        raise HTTPException(status_code=400, detail=f"无效 default_view：{updates['default_view']}")
    if "theme" in updates and updates["theme"] not in _VALID_THEMES:
        raise HTTPException(status_code=400, detail=f"无效 theme：{updates['theme']}")
    if "preferred_data_source" in updates and updates["preferred_data_source"] not in _VALID_SOURCES:
        raise HTTPException(status_code=400, detail=f"无效 preferred_data_source：{updates['preferred_data_source']}")
    merged = _load_prefs(user["id"])
    merged.update(updates)
    return {"preferences": _save_prefs(user["id"], merged)}
