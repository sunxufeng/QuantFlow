"""运行实例 API（M2 执行引擎）：异步提交 / 查询 / WebSocket 状态推送。"""

from __future__ import annotations

import asyncio
from typing import Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..core.events import EVENT_BUS
from ..core.runs import RUN_SERVICE, RunCapacityError, RunNotFoundError
from ..core.ws import RUN_CONNECTIONS

router = APIRouter()


@router.post("/runs", summary="提交工作流运行（异步，立即返回 run_id）")
def submit_run(payload: dict) -> dict:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    if not nodes:
        raise HTTPException(status_code=422, detail="nodes 不能为空")
    try:
        return RUN_SERVICE.submit(
            nodes,
            edges,
            workflow_id=payload.get("workflow_id"),
            workflow_name=payload.get("workflow_name", ""),
        )
    except RunCapacityError as exc:
        raise HTTPException(status_code=429, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=422, detail=f"工作流校验失败: {exc}") from exc


@router.get("/runs", summary="运行实例列表")
def list_runs(
    workflow_id: Optional[str] = Query(default=None, description="按工作流过滤"),
    limit: int = Query(default=50, ge=1, le=200),
) -> dict:
    return {"items": RUN_SERVICE.list(workflow_id=workflow_id, limit=limit)}


@router.get("/runs/{run_id}", summary="运行实例详情")
def get_run(run_id: str) -> dict:
    try:
        return RUN_SERVICE.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="运行实例不存在") from None


@router.websocket("/ws/runs/{run_id}")
async def ws_run_stream(websocket: WebSocket, run_id: str) -> None:
    """订阅指定运行实例的实时状态事件。

    连接后先推送当前快照（若运行已结束则直接推送终态），
    随后按事件顺序推送节点/运行状态变更。
    """
    await RUN_CONNECTIONS.connect(run_id, websocket)
    queue: asyncio.Queue = asyncio.Queue()

    def _on_event(event) -> None:
        if event.run_id == run_id:
            try:
                queue.put_nowait(event.to_dict())
            except Exception:  # noqa: BLE001 - 队列溢出不影响主流程
                pass

    unsubscribe = EVENT_BUS.subscribe(_on_event)
    try:
        # 先推当前快照（晚到的订阅者也能拿到最新状态）
        try:
            record = RUN_SERVICE.get(run_id)
            snapshot = {
                "run_id": run_id,
                "kind": "snapshot",
                "node_id": None,
                "payload": record,
                "timestamp": None,
            }
            await websocket.send_json(snapshot)
        except RunNotFoundError:
            await websocket.send_json({"kind": "error", "payload": {"message": "运行实例不存在"}})
            return
        while True:
            msg = await queue.get()
            await websocket.send_json(msg)
    except WebSocketDisconnect:
        pass
    finally:
        unsubscribe()
        await RUN_CONNECTIONS.disconnect(run_id, websocket)
