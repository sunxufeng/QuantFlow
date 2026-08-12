"""WebSocket 连接管理（M2 执行引擎状态推送）。

对标开发计划 §4.2「运行状态 WebSocket 推送」：

- :class:`RunConnectionManager` 维护 run_id -> 活跃连接集合
- 运行事件经 :class:`~app.core.events.EventBus`（进程内同步回调）投递，
  在 WebSocket 端点内桥接到 asyncio 队列异步下发，避免阻塞执行线程
"""

from __future__ import annotations

import asyncio
from typing import Dict, List

from fastapi import WebSocket


class RunConnectionManager:
    """run_id -> WebSocket 连接集合（进程内，单机部署足够）。"""

    def __init__(self) -> None:
        self._conns: Dict[str, List[WebSocket]] = {}
        self._lock = asyncio.Lock()

    async def connect(self, run_id: str, websocket: WebSocket) -> None:
        await websocket.accept()
        async with self._lock:
            self._conns.setdefault(run_id, []).append(websocket)

    async def disconnect(self, run_id: str, websocket: WebSocket) -> None:
        async with self._lock:
            conns = self._conns.get(run_id, [])
            if websocket in conns:
                conns.remove(websocket)
            if not conns:
                self._conns.pop(run_id, None)

    async def broadcast(self, run_id: str, message: dict) -> None:
        async with self._lock:
            conns = list(self._conns.get(run_id, []))
        for ws in conns:
            try:
                await ws.send_json(message)
            except Exception:  # noqa: BLE001 - 单连接失败不影响其他连接
                await self.disconnect(run_id, ws)


RUN_CONNECTIONS = RunConnectionManager()
