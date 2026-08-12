"""分布式 Worker 进程（V1.1 N6）。

消费者侧：循环从共享任务队列 :class:`~app.core.jobs.JobQueue` 认领任务，
用既有的 :class:`~app.core.executor.WorkflowExecutor` 执行，并把节点状态 / 运行终态 /
事件实时写入共享存储（:class:`~app.core.runstore.DatabaseRunRepository` +
:class:`~app.core.eventlog.RunEventLog`），最后触发运行完成通知（N5）。

运行方式::

    python -m app.core.worker            # 前台常驻，按 QF_WORKER_* 环境变量配置
    python -m app.core.worker --once     # 只处理一条（若有），用于测试/一次性任务

与 API 进程通过同一个 SQLite 文件（QF_DB_PATH）共享状态；可单机起多个 worker 进程
横向扩展，无需 Redis 等额外基础设施。
"""

from __future__ import annotations

import logging
import os
import signal
import socket
import sys
import time
from typing import Optional

from .dag import validate_workflow
from .databridge import DataBridge
from .eventlog import RUN_EVENT_LOG, RunEventLog
from .events import (
    NODE_BLOCKED,
    NODE_FAILED,
    NODE_RUNNING,
    NODE_SUCCEEDED,
    RUN_FAILED,
    RUN_STARTED,
    RUN_SUCCEEDED,
    RunEvent,
)
from .executor import WorkflowExecutor
from .jobs import JOB_QUEUE, DatabaseJobQueue, JobQueue
from .runstore import RUN_REPOSITORY, DatabaseRunRepository, RunNotFoundError
from .runs import RunStatus

logger = logging.getLogger("quantflow.worker")

_NODE_KINDS = {NODE_RUNNING, NODE_SUCCEEDED, NODE_FAILED, NODE_BLOCKED}


class Worker:
    """从共享队列认领并执行工作流运行的消费者。"""

    def __init__(
        self,
        job_queue: Optional[JobQueue] = None,
        repository: Optional[DatabaseRunRepository] = None,
        event_log: Optional[RunEventLog] = None,
        worker_id: Optional[str] = None,
        executor_workers: int = 4,
        stale_timeout: float = 300.0,
    ) -> None:
        self.job_queue = job_queue or JOB_QUEUE
        self.repository = repository or RUN_REPOSITORY
        self.event_log = event_log or RUN_EVENT_LOG
        self.worker_id = worker_id or f"{socket.gethostname()}-{os.getpid()}"
        self.executor_workers = executor_workers
        self.stale_timeout = stale_timeout

    # ------------------------------------------------------------------ #
    def run_once(self) -> bool:
        """认领并执行一条任务；无可认领任务返回 ``False``。"""
        job = self.job_queue.claim(self.worker_id)
        if job is None:
            return False
        self.execute_job(job)
        return True

    def run_forever(
        self, poll_interval: float = 1.0, max_jobs: Optional[int] = None
    ) -> None:
        processed = 0
        logger.info(
            "worker %s 启动 (poll=%.1fs, stale=%.0fs)", self.worker_id, poll_interval, self.stale_timeout
        )
        stop = False

        def _handle_term(signum, frame):  # noqa: ARG001
            nonlocal stop
            logger.info("worker %s 收到停止信号，退出循环", self.worker_id)
            stop = True

        signal.signal(signal.SIGTERM, _handle_term)
        signal.signal(signal.SIGINT, _handle_term)

        while not stop:
            try:
                reclaimed = self.job_queue.reclaim_stale(self.stale_timeout)
                if reclaimed:
                    logger.warning("回收 %d 条超时任务", reclaimed)
            except Exception:  # noqa: BLE001
                logger.exception("reclaim_stale 失败")
            try:
                if self.run_once():
                    processed += 1
                    if max_jobs and processed >= max_jobs:
                        logger.info("已达 max_jobs=%d，退出", max_jobs)
                        break
            except Exception:  # noqa: BLE001 - 单任务异常不应终止 worker
                logger.exception("run_once 意外失败（已跳过，继续下一轮）")
            if not stop:
                time.sleep(poll_interval)
        logger.info("worker %s 停止（共处理 %d 条）", self.worker_id, processed)

    # ------------------------------------------------------------------ #
    def execute_job(self, job: dict) -> None:
        job_id = job["job_id"]
        payload = job["payload"] or {}
        nodes = payload.get("nodes") or []
        edges = payload.get("edges") or []
        workflow_id = job.get("workflow_id")
        workflow_name = job.get("workflow_name", "")
        logger.info("worker %s 认领任务 %s (%d 节点)", self.worker_id, job_id, len(nodes))

        # 执行开始：确保运行记录在共享存储中存在（生产者通常已建，这里兜底自洽）
        try:
            self.repository.get(job_id)
        except RunNotFoundError:
            self.repository.create({
                "run_id": job_id,
                "workflow_id": workflow_id,
                "workflow_name": workflow_name,
                "nodes": {},
                "status": RunStatus.QUEUED,
                "created_at": "",
                "started_at": time.time(),
                "finished_at": None,
                "result": None,
            })
        # 更新运行态 + 发布 RUN_STARTED（单一来源，避免与 API 重复）
        self.job_queue.mark_running(job_id, self.worker_id)
        self.repository.update(job_id, status=RunStatus.RUNNING)
        self.event_log.append(job_id, RUN_STARTED, None, {"workflow_name": workflow_name, "node_ids": [n.get("id") for n in nodes]})

        bus = _LocalBus()
        executor = WorkflowExecutor(
            max_workers=self.executor_workers, event_bus=bus, bridge=DataBridge()
        )

        def _on_event(event: RunEvent) -> None:
            if event.kind in _NODE_KINDS and event.node_id:
                state = {
                    "node_id": event.node_id,
                    "status": event.payload.get("status", event.kind),
                    "error": event.payload.get("error"),
                    "duration_ms": event.payload.get("duration_ms", 0.0),
                    "outputs": event.payload.get("outputs", {}),
                }
                try:
                    self.repository.patch_node(job_id, event.node_id, state)
                except Exception:  # noqa: BLE001
                    logger.warning("patch_node 失败 run=%s node=%s", job_id, event.node_id)
                self.event_log.append(job_id, event.kind, event.node_id, event.payload)

        bus.subscribe(_on_event)

        try:
            graph = validate_workflow(nodes, edges)
            result = executor.run(graph, run_id=job_id)
            succeeded = result.status == "succeeded"
            status = RunStatus.SUCCEEDED if succeeded else RunStatus.FAILED
            error = None if succeeded else _first_error(result)
            self.repository.update(
                job_id,
                status=status,
                finished_at=time.time(),
                result=result.to_dict(include_outputs=False),
            )
            self.event_log.append(
                job_id, RUN_SUCCEEDED if succeeded else RUN_FAILED
            )
            if succeeded:
                self.job_queue.mark_done(job_id)
            else:
                self.job_queue.mark_failed(job_id, error or "节点执行失败")
            self._notify(job_id, workflow_name, status, error)
        except Exception as exc:  # noqa: BLE001 - 兜底：异常视为运行失败
            logger.exception("任务 %s 执行异常", job_id)
            self.repository.update(
                job_id,
                status=RunStatus.FAILED,
                finished_at=time.time(),
                result={"status": "failed", "error": f"{type(exc).__name__}: {exc}"},
            )
            self.event_log.append(job_id, RUN_FAILED, None, {"error": str(exc)})
            self.job_queue.mark_failed(job_id, f"{type(exc).__name__}: {exc}")
            self._notify(job_id, workflow_name, RunStatus.FAILED, str(exc))

    def _notify(self, run_id: str, workflow_name: str, status: str, error: Optional[str]) -> None:
        try:
            from ..notifications.service import notification_service

            notification_service.notify_run_finished(
                run_id=run_id, workflow_name=workflow_name, status=status, error=error
            )
        except Exception:  # noqa: BLE001 - 通知故障不影响运行终态
            logger.warning("运行完成通知发送失败（不影响结果）", exc_info=True)


def _first_error(result) -> Optional[str]:
    for st in result.node_states.values():
        if st.status == "failed" and st.error:
            return st.error
    return "节点执行失败"


class _LocalBus:
    """极简进程内总线，仅用于把执行器事件桥接到 worker 的落库逻辑。"""

    def __init__(self) -> None:
        self._subs = []

    def subscribe(self, cb) -> object:
        self._subs.append(cb)
        return lambda: self._subs.remove(cb) if cb in self._subs else None

    def publish(self, event: RunEvent) -> None:
        for cb in list(self._subs):
            try:
                cb(event)
            except Exception:  # noqa: BLE001
                continue


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def main(argv: Optional[list] = None) -> int:
    logging.basicConfig(
        level=os.getenv("QF_LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    poll = float(os.getenv("QF_WORKER_POLL_INTERVAL", "1.0"))
    stale = float(os.getenv("QF_WORKER_STALE_TIMEOUT", "300"))
    exec_workers = _env_int("QF_WORKER_EXECUTOR_WORKERS", 4)
    worker_id = os.getenv("QF_WORKER_ID")
    once = "--once" in (argv or sys.argv[1:])

    worker = Worker(
        job_queue=DatabaseJobQueue(),
        repository=DatabaseRunRepository(),
        worker_id=worker_id,
        executor_workers=exec_workers,
        stale_timeout=stale,
    )
    if once:
        return 0 if worker.run_once() else 0
    worker.run_forever(poll_interval=poll)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
