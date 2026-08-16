"""V106 适配器目录 API：汇总市场数据源与券商连接器的接口缝状态。

GET /api/adapters —— 返回已注册的全部适配器（市场源 + 券商）及其就绪情况。
仅供已登录用户；只读，不建立真实连接。
"""

from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, Depends

from ..core.auth import get_current_user
from ..adapters import list_adapters

router = APIRouter(tags=["adapters"])


@router.get("/adapters")
def get_adapters(user: Dict[str, Any] = Depends(get_current_user)) -> Dict[str, Any]:
    """适配器目录：市场数据源 + 券商连接器（含 panda 多源接口缝）。"""
    return list_adapters()
