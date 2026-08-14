"""运行实例 API（M2 执行引擎）：异步提交 / 查询 / WebSocket 状态推送。"""

from __future__ import annotations

import asyncio
import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query, WebSocket, WebSocketDisconnect

from ..core import runs as run_module
from ..core.auth import get_current_user
from ..core.eventlog import RUN_EVENT_LOG
from ..core.events import RUN_FAILED, RUN_SUCCEEDED
from ..core.runs import RunCapacityError, RunNotFoundError, RunStatus
from ..core.security import decode_token
from ..core.users import USER_REPOSITORY
from ..core.ws import RUN_CONNECTIONS

router = APIRouter()


@router.post("/runs", summary="提交工作流运行（异步，立即返回 run_id）")
def submit_run(payload: dict, _user: dict = Depends(get_current_user)) -> dict:
    nodes = payload.get("nodes") or []
    edges = payload.get("edges") or []
    if not nodes:
        raise HTTPException(status_code=422, detail="nodes 不能为空")
    try:
        return run_module.RUN_SERVICE.submit(
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
    _user: dict = Depends(get_current_user),
) -> dict:
    return {"items": run_module.RUN_SERVICE.list(workflow_id=workflow_id, limit=limit)}


@router.get("/runs/{run_id}", summary="运行实例详情")
def get_run(run_id: str, _user: dict = Depends(get_current_user)) -> dict:
    try:
        return run_module.RUN_SERVICE.get(run_id)
    except RunNotFoundError:
        raise HTTPException(status_code=404, detail="运行实例不存在") from None


def _ws_user_from_token(raw: Optional[str]) -> Optional[dict]:
    """按裸令牌字符串解析用户（支持 JWT 与 API Token 两种通道）。"""
    if not raw:
        return None
    if raw.startswith("qf."):
        from ..core.api_tokens import API_TOKEN_REPOSITORY

        uid = API_TOKEN_REPOSITORY.verify(raw)
        return USER_REPOSITORY.get(uid) if uid else None
    payload = decode_token(raw)
    if payload is None:
        return None
    return USER_REPOSITORY.get(payload["uid"])


@router.websocket("/ws/runs/{run_id}")
async def ws_run_stream(websocket: WebSocket, run_id: str) -> None:
    """订阅指定运行实例的实时状态事件（跨进程，读取共享事件日志）。

    连接后先推送当前快照（若运行已结束则直接推送终态），随后轮询共享事件日志
    ``run_events`` 按 seq 顺序推送新增事件，直至终态事件（RUN_SUCCEEDED/RUN_FAILED）
    已下发。无论运行由本进程（local 后端）还是独立 worker 进程执行均适用。
    """
    # 鉴权：令牌经 ?token= 查询参数或 Authorization 头传入；无效则拒绝连接。
    token_param = websocket.query_params.get("token")
    header = websocket.headers.get("authorization") or ""
    raw = token_param or (header[7:] if header.lower().startswith("bearer ") else None)
    if _ws_user_from_token(raw) is None:
        await websocket.close(code=1008, reason="未认证")
        return
    await RUN_CONNECTIONS.connect(run_id, websocket)
    poll_interval = float(os.getenv("QF_WS_POLL_INTERVAL", "0.3"))
    last_seq = 0
    terminal_kinds = {RUN_SUCCEEDED, RUN_FAILED}
    try:
        # 先推当前快照（晚到的订阅者也能拿到最新状态）
        try:
            record = run_module.RUN_SERVICE.get(run_id)
        except RunNotFoundError:
            await websocket.send_json({"kind": "error", "payload": {"message": "运行实例不存在"}})
            return
        await websocket.send_json(
            {
                "run_id": run_id,
                "kind": "snapshot",
                "node_id": None,
                "payload": record,
                "timestamp": None,
            }
        )
        while True:
            events = RUN_EVENT_LOG.read_since(run_id, last_seq)
            for ev in events:
                await websocket.send_json(ev)
                last_seq = ev["seq"]
                if ev["kind"] in terminal_kinds:
                    return  # 终态已下发，结束推送
            # 快照状态已是终态且无新事件（如订阅晚于执行完成）亦结束
            try:
                rec = run_module.RUN_SERVICE.get(run_id)
                if rec["status"] not in (RunStatus.RUNNING, RunStatus.QUEUED) and not events:
                    return
            except RunNotFoundError:
                return
            await asyncio.sleep(poll_interval)
    except WebSocketDisconnect:
        pass
    finally:
        await RUN_CONNECTIONS.disconnect(run_id, websocket)
