"""运行实例持久化与查询（M2 执行引擎 RunService）。

对标开发计划 §4.2「运行实例持久化与查询（Mongo）」：

- :class:`RunRepository`：运行实例存储（V1.0 线程安全内存实现，接口对齐
  Mongo 迁移后的查询语义：按 run_id 查询 / 按工作流过滤 / 最新优先）
- :class:`RunService`：提交运行 -> 后台线程执行 -> 全流程事件发布 ->
  持久化终态（状态、节点状态、输出预览引用）

执行器经 :class:`~app.core.events.EventBus` 发布节点级事件，
RunService 订阅并实时落库，前端 WebSocket 亦订阅同一总线。
"""

from __future__ import annotations

import logging
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .dag import WorkflowGraph, validate_workflow
from .databridge import DataBridge
from .eventlog import RUN_EVENT_LOG, RunEventLog
from .events import (
    EVENT_BUS,
    NODE_FAILED,
    NODE_RUNNING,
    NODE_SUCCEEDED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_SUCCEEDED,
    RunEvent,
)
from .executor import WorkflowExecutor
from .jobs import JOB_QUEUE, JobQueue
from .runstore import RUN_REPOSITORY, RunNotFoundError


class RunStatus:
    QUEUED = "queued"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"


class RunExecutionError(RuntimeError):
    """同步执行时出现的意外错误（非节点失败）。"""


class RunCapacityError(RuntimeError):
    """运行队列已满，拒绝新的异步执行请求。"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class RunRepository:
    """运行实例存储（线程安全内存实现，后续可换 Mongo）。"""

    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def create(self, record: dict) -> dict:
        with self._lock:
            self._items[record["run_id"]] = record
        return deepcopy(record)

    def get(self, run_id: str) -> dict:
        with self._lock:
            try:
                return deepcopy(self._items[run_id])
            except KeyError:
                raise RunNotFoundError(run_id) from None

    def update(self, run_id: str, **fields: Any) -> dict:
        with self._lock:
            if run_id not in self._items:
                raise RunNotFoundError(run_id)
            self._items[run_id].update(fields)
            return deepcopy(self._items[run_id])

    def patch_node(self, run_id: str, node_id: str, state: dict) -> dict:
        with self._lock:
            if run_id not in self._items:
                raise RunNotFoundError(run_id)
            record = self._items[run_id]
            record.setdefault("nodes", {})[node_id] = state
            return deepcopy(record)

    def list(self, workflow_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        with self._lock:
            items = sorted(
                self._items.values(),
                key=lambda r: r["started_at"],
                reverse=True,
            )
            if workflow_id:
                items = [r for r in items if r.get("workflow_id") == workflow_id]
            return [self._summary(r) for r in items[:limit]]

    def delete(self, run_id: str) -> None:
        with self._lock:
            if run_id not in self._items:
                raise RunNotFoundError(run_id)
            del self._items[run_id]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()

    def stats(self) -> dict:
        """运行状态统计（M4 监控用）。"""
        with self._lock:
            counts = {"total": len(self._items)}
            for record in self._items.values():
                status = record.get("status", "unknown")
                counts[status] = counts.get(status, 0) + 1
            return counts

    @staticmethod
    def _summary(record: dict) -> dict:
        return {
            "run_id": record["run_id"],
            "workflow_id": record.get("workflow_id"),
            "workflow_name": record.get("workflow_name", ""),
            "status": record["status"],
            "created_at": record["created_at"],
            "started_at": record["started_at"],
            "finished_at": record.get("finished_at"),
        }


class RunService:
    """运行生命周期编排：提交 -> 后台执行 -> 事件 -> 持久化。"""

    def __init__(
        self,
        executor: Optional[WorkflowExecutor] = None,
        repository: Optional[RunRepository] = None,
        bridge: Optional[DataBridge] = None,
        bus=None,
        run_workers: int = 20,
        queue_size: int = 100,
        backend: str = "local",
        job_queue: Optional[JobQueue] = None,
        event_log: Optional[RunEventLog] = None,
    ) -> None:
        if run_workers < 1:
            raise ValueError("run_workers must be at least 1")
        if queue_size < 0:
            raise ValueError("queue_size cannot be negative")
        if backend not in ("local", "worker"):
            raise ValueError(f"unknown backend: {backend}")
        self.backend = backend
        self.job_queue = job_queue or JOB_QUEUE
        self.event_log = event_log or RUN_EVENT_LOG
        if repository is not None:
            self.repository = repository
        elif backend == "worker":
            # 共享存储：API 与 worker 进程看到同一份运行态
            self.repository = RUN_REPOSITORY
        else:
            self.repository = RunRepository()
        self.bridge = bridge or DataBridge()
        self.bus = bus if bus is not None else EVENT_BUS
        self.executor = executor or WorkflowExecutor(
            max_workers=4, event_bus=self.bus, bridge=self.bridge
        )
        self.run_workers = run_workers
        self.queue_size = queue_size
        self._run_pool = ThreadPoolExecutor(
            max_workers=run_workers,
            thread_name_prefix="quantflow-run",
        )
        self._capacity = threading.BoundedSemaphore(run_workers + queue_size)
        # 实时订阅：节点事件即时写入运行记录（local 进程内执行 / 同步执行均生效）
        self.bus.subscribe(self._on_event)

    # ------------------------------------------------------------------ #
    # 对外 API
    # ------------------------------------------------------------------ #
    def submit(
        self,
        nodes: List[dict],
        edges: List[dict],
        *,
        workflow_id: Optional[str] = None,
        workflow_name: str = "",
    ) -> dict:
        """校验并异步执行工作流，立即返回 ``{run_id, status}``。

        - ``backend="local"``：进程内线程池执行（历史默认行为）。
        - ``backend="worker"``：仅入队共享任务队列，由 ``quantflow-worker`` 进程消费执行；
          运行态写入共享存储，状态先为 ``queued``，worker 认领后转 ``running``。
        """
        graph = validate_workflow(nodes, edges)
        if not self._capacity.acquire(blocking=False):
            raise RunCapacityError(
                f"run capacity reached ({self.run_workers} active, {self.queue_size} queued)"
            )
        run_id = uuid.uuid4().hex[:12]
        now = _utc_now()
        is_worker = self.backend == "worker"
        record = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "nodes": {},   # node_id -> NodeRunState.to_dict()
            "status": RunStatus.QUEUED if is_worker else RunStatus.RUNNING,
            "created_at": now,
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
        }
        try:
            self.repository.create(record)
            if is_worker:
                # 仅入队；RUN_STARTED 由 worker 认领时写入（单一来源）
                self.job_queue.enqueue(
                    {"nodes": nodes, "edges": edges},
                    job_id=run_id,
                    workflow_id=workflow_id,
                    workflow_name=workflow_name,
                )
                self._capacity.release()  # 入队即视为接纳，受 queue_size 约束
            else:
                self.bus.publish(
                    RunEvent(
                        run_id=run_id,
                        kind=RUN_STARTED,
                        payload={"workflow_name": workflow_name, "node_ids": graph.nodes},
                    )
                )
                self.event_log.append(
                    run_id,
                    RUN_STARTED,
                    None,
                    {"workflow_name": workflow_name, "node_ids": list(graph.nodes)},
                )
                self._run_pool.submit(self._execute_async, run_id, graph)
        except Exception:
            self._capacity.release()
            raise
        return {"run_id": run_id, "status": record["status"]}

    def execute_sync(
        self,
        nodes: List[dict],
        edges: List[dict],
        *,
        workflow_id: Optional[str] = None,
        workflow_name: str = "",
    ):
        """同步执行（API 同步端点用）：返回含完整输出的 RunResult，同时持久化。"""
        graph = validate_workflow(nodes, edges)
        run_id = uuid.uuid4().hex[:12]
        record = {
            "run_id": run_id,
            "workflow_id": workflow_id,
            "workflow_name": workflow_name,
            "nodes": {},
            "status": RunStatus.RUNNING,
            "created_at": _utc_now(),
            "started_at": time.time(),
            "finished_at": None,
            "result": None,
        }
        self.repository.create(record)
        self.bus.publish(
            RunEvent(run_id=run_id, kind=RUN_STARTED, payload={"node_ids": graph.nodes})
        )
        result = self._execute(run_id, graph)
        if result is None:
            record = self.repository.get(run_id)
            error = (record.get("result") or {}).get("error", "执行失败")
            raise RunExecutionError(error)
        return result

    def get(self, run_id: str) -> dict:
        return self.repository.get(run_id)

    def list(self, workflow_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        return self.repository.list(workflow_id=workflow_id, limit=limit)

    def wait(self, run_id: str, timeout: Optional[float] = None) -> dict:
        """阻塞直到运行结束（测试/同步调用用）。"""
        deadline = time.time() + timeout if timeout else None
        while True:
            record = self.repository.get(run_id)
            if record["status"] not in (RunStatus.RUNNING, RunStatus.QUEUED):
                return record
            if deadline is not None and time.time() > deadline:
                return record
            time.sleep(0.02)

    # ------------------------------------------------------------------ #
    # 执行与事件消费
    # ------------------------------------------------------------------ #
    def _execute_async(self, run_id: str, graph: WorkflowGraph) -> None:
        try:
            self._execute(run_id, graph)
        finally:
            self._capacity.release()

    def _execute(self, run_id: str, graph: WorkflowGraph):
        """执行并持久化；成功返回 RunResult，意外异常时更新记录并返回 None。"""
        try:
            result = self.executor.run(graph, run_id=run_id)
            status = RunStatus.SUCCEEDED if result.status == "succeeded" else RunStatus.FAILED
            final = {
                "status": status,
                "finished_at": time.time(),
                "result": result.to_dict(include_outputs=False),
            }
            self.repository.update(run_id, **final)
            kind = RUN_SUCCEEDED if status == RunStatus.SUCCEEDED else RUN_FAILED
            self.bus.publish(RunEvent(run_id=run_id, kind=kind))
            self.event_log.append(run_id, kind, None, final.get("result") or {})
            self._notify_finished(run_id, status)
            return result
        except Exception as exc:  # noqa: BLE001 - 兜底：异常视为运行失败
            final = {
                "status": RunStatus.FAILED,
                "finished_at": time.time(),
                "result": {"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
            }
            self.repository.update(run_id, **final)
            self.bus.publish(RunEvent(run_id=run_id, kind=RUN_FAILED, payload={"error": str(exc)}))
            self.event_log.append(run_id, RUN_FAILED, None, {"error": str(exc)})
            self._notify_finished(run_id, RunStatus.FAILED, error=str(exc))
            return None

    def _notify_finished(self, run_id: str, status: str, error: Optional[str] = None) -> None:
        """运行完成/失败后推送外部通知（N5）；失败不影响运行结果。"""
        try:
            from ..notifications.service import notification_service

            rec = self.repository.get(run_id)
            wf_name = rec.get("workflow_name", "") if rec else ""
            notification_service.notify_run_finished(
                run_id=run_id, workflow_name=wf_name, status=status, error=error
            )
        except Exception:  # 通知故障不应影响运行终态
            logging.getLogger("quantflow.runs").warning(
                "运行完成通知发送失败（不影响结果）", exc_info=True
            )

    def _on_event(self, event: RunEvent) -> None:
        """订阅总线：节点状态事件实时写入运行记录 + 持久化到跨进程事件日志。"""
        if event.kind not in (NODE_RUNNING, NODE_SUCCEEDED, NODE_FAILED):
            return
        if not event.node_id:
            return
        payload = event.payload or {}
        state = {
            "node_id": event.node_id,
            "status": payload.get("status", event.kind),
            "error": payload.get("error"),
            "duration_ms": payload.get("duration_ms", 0.0),
            "outputs": payload.get("outputs", {}),  # 预览（大数据已落盘）
        }
        try:
            self.repository.patch_node(event.run_id, event.node_id, state)
            self.event_log.append(event.run_id, event.kind, event.node_id, payload)
        except RunNotFoundError:
            pass  # 运行记录不存在（如直接被删除）时忽略


# 全局单例
RUN_SERVICE = RunService()
