"""分布式任务队列（V1.1 N6）。

把「工作流运行」从 API 进程内执行，改为生产者/消费者模型：

- 生产者（API 进程中的 :class:`~app.core.runs.RunService` ``backend="worker"``）
  调用 :meth:`JobQueue.enqueue` 写入一条待执行任务；
- 消费者（独立的 ``quantflow-worker`` 进程）调用 :meth:`JobQueue.claim` 原子认领
  一条 ``queued`` 任务，执行完后 :meth:`JobQueue.mark_done` / :meth:`JobQueue.mark_failed`。

本模块提供 :class:`JobQueue` 抽象基类与基于项目既有 SQLite（:mod:`app.core.db`）
的 :class:`DatabaseJobQueue` 实现。SQLite 文件可被同机多个进程共享（WAL 模式），
因此天然支持「多 worker 进程」的分布式部署，而无需引入 Redis 等额外基础设施。

接口与实现解耦，未来若需跨主机可替换为 Redis/RabbitMQ 后端，调用方不变。
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any, Dict, Optional

from .db import db


class JobQueue:
    """任务队列抽象（生产者/消费者）。"""

    def enqueue(
        self,
        payload: Dict[str, Any],
        *,
        job_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        workflow_name: str = "",
        priority: int = 0,
    ) -> str:
        """入队一条任务，返回 job_id（通常等于 run_id）。"""
        raise NotImplementedError

    def claim(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """原子认领一条待执行任务；无可认领任务时返回 ``None``。"""
        raise NotImplementedError

    def mark_running(self, job_id: str, worker_id: str) -> None:
        raise NotImplementedError

    def mark_done(self, job_id: str) -> None:
        raise NotImplementedError

    def mark_failed(self, job_id: str, error: str) -> None:
        raise NotImplementedError

    def reclaim_stale(self, timeout: float) -> int:
        """回收超时未更新的 ``running`` 任务为 ``queued``，返回回收数量。"""
        raise NotImplementedError

    def pending_count(self) -> int:
        raise NotImplementedError


class DatabaseJobQueue(JobQueue):
    """基于 SQLite 的共享任务队列（同机多进程共享同一 DB 文件）。"""

    def __init__(self, database=None) -> None:
        self._db = database or db

    def enqueue(
        self,
        payload: Dict[str, Any],
        *,
        job_id: Optional[str] = None,
        workflow_id: Optional[str] = None,
        workflow_name: str = "",
        priority: int = 0,
    ) -> str:
        job_id = job_id or uuid.uuid4().hex[:12]
        now = time.time()
        self._db.execute(
            "INSERT INTO run_jobs (id, workflow_id, workflow_name, payload, status, "
            "claimed_by, claimed_at, error, created_at, updated_at, priority) "
            "VALUES (?, ?, ?, ?, 'queued', NULL, NULL, NULL, ?, ?, ?)",
            (
                job_id,
                workflow_id,
                workflow_name,
                json.dumps(payload, ensure_ascii=False),
                now,
                now,
                priority,
            ),
        )
        return job_id

    def claim(self, worker_id: str) -> Optional[Dict[str, Any]]:
        """认领优先级最高、最早创建的 ``queued`` 任务（原子 UPDATE + 回读）。"""
        now = time.time()
        row = self._db.query_one(
            "SELECT id FROM run_jobs WHERE status = 'queued' "
            "ORDER BY priority DESC, created_at ASC LIMIT 1"
        )
        if row is None:
            return None
        cur = self._db.execute(
            "UPDATE run_jobs SET status = 'running', claimed_by = ?, claimed_at = ?, "
            "updated_at = ? WHERE id = ? AND status = 'queued'",
            (worker_id, now, now, row["id"]),
        )
        if cur.rowcount == 0:
            return None  # 竞态：被其它 worker 抢先认领
        job = self._db.query_one(
            "SELECT id, workflow_id, workflow_name, payload, priority "
            "FROM run_jobs WHERE id = ?",
            (row["id"],),
        )
        return {
            "job_id": job["id"],
            "workflow_id": job["workflow_id"],
            "workflow_name": job["workflow_name"],
            "payload": json.loads(job["payload"]),
            "priority": job["priority"],
        }

    def mark_running(self, job_id: str, worker_id: str) -> None:
        self._db.execute(
            "UPDATE run_jobs SET status = 'running', claimed_by = ?, claimed_at = ?, "
            "updated_at = ? WHERE id = ?",
            (worker_id, time.time(), time.time(), job_id),
        )

    def mark_done(self, job_id: str) -> None:
        self._db.execute(
            "UPDATE run_jobs SET status = 'succeeded', updated_at = ? WHERE id = ?",
            (time.time(), job_id),
        )

    def mark_failed(self, job_id: str, error: str) -> None:
        self._db.execute(
            "UPDATE run_jobs SET status = 'failed', error = ?, updated_at = ? WHERE id = ?",
            (error, time.time(), job_id),
        )

    def reclaim_stale(self, timeout: float) -> int:
        """回收 ``running`` 但超过 ``timeout`` 秒未更新的任务（worker 崩溃兜底）。"""
        cutoff = time.time() - timeout
        cur = self._db.execute(
            "UPDATE run_jobs SET status = 'queued', claimed_by = NULL, claimed_at = NULL, "
            "updated_at = ? WHERE status = 'running' AND claimed_at IS NOT NULL "
            "AND claimed_at < ?",
            (time.time(), cutoff),
        )
        return cur.rowcount

    def pending_count(self) -> int:
        row = self._db.query_one(
            "SELECT COUNT(*) AS n FROM run_jobs WHERE status IN ('queued', 'running')"
        )
        return int(row["n"]) if row else 0


# 全局默认队列（与 db 单例共享同一 SQLite 文件，跨进程可见）
JOB_QUEUE = DatabaseJobQueue()
