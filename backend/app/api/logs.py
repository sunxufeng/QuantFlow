"""结构化日志查询 API（M4-3）。"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Query

from ..core.auth import get_current_user
from ..core.logging_store import LOG_STORE

router = APIRouter(prefix="/logs", tags=["logs"])


@router.get("", summary="日志查询（admin 全量，普通用户仅自身+系统日志）")
def query_logs(
    level: Optional[str] = Query(default=None, description="按级别过滤：DEBUG/INFO/WARNING/ERROR"),
    logger: Optional[str] = Query(default=None, description="按 logger 名模糊过滤"),
    keyword: Optional[str] = Query(default=None, description="按消息/路径关键字过滤"),
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    user: dict = Depends(get_current_user),
) -> dict:
    return LOG_STORE.query(
        level=level,
        logger=logger,
        keyword=keyword,
        limit=limit,
        offset=offset,
        viewer=user,
    )
