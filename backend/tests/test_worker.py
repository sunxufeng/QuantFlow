"""N6 分布式 Worker 测试：共享任务队列 / 运行态 / 事件日志 / Worker 执行 / RunService worker 后端 / 跨进程 WS。

全部使用独立临时 SQLite，避免污染业务库；验证生产者(API) 入队、消费者(worker) 出队执行、
跨进程运行态与事件可见性。
"""

from __future__ import annotations

import os
import tempfile

import pytest

from app.core.db import Database
from app.core.eventlog import RunEventLog
from app.core.jobs import DatabaseJobQueue
from app.core.runstore import DatabaseRunRepository, RunNotFoundError
from app.core.runs import RunService, RunStatus
from app.core.worker import Worker


@pytest.fixture
def tdb():
    d = tempfile.mkdtemp()
    db = Database(path=os.path.join(d, "n6.db"))
    yield db
    try:
        os.remove(db.path)
    except OSError:
        pass


@pytest.fixture
def components(tdb):
    return (
        DatabaseJobQueue(tdb),
        DatabaseRunRepository(tdb),
        RunEventLog(tdb),
    )


# --------------------------------------------------------------------------- #
# JobQueue
# --------------------------------------------------------------------------- #
def test_job_queue_lifecycle(components):
    q, _repo, _log = components
    job_id = q.enqueue({"nodes": [], "edges": []}, workflow_name="w")
    assert q.pending_count() == 1
    job = q.claim("worker-1")
    assert job is not None and job["job_id"] == job_id
    # 认领后不可再次认领同一条
    assert q.claim("worker-2") is None
    q.mark_done(job_id)
    assert q.pending_count() == 0
    assert q.claim("worker-3") is None


def test_job_queue_atomic_distinct(components):
    q, _repo, _log = components
    q.enqueue({"nodes": []}, job_id="j1")
    q.enqueue({"nodes": []}, job_id="j2")
    a = q.claim("w1")
    b = q.claim("w2")
    ids = {a["job_id"], b["job_id"]}
    assert ids == {"j1", "j2"}


def test_job_queue_reclaim_stale(components):
    q, _repo, _log = components
    q.enqueue({"nodes": []}, job_id="stale")
    q.claim("w1")  # -> running, claimed_at = now
    # 把认领时间改到很久以前以模拟 worker 崩溃
    q._db.execute("UPDATE run_jobs SET claimed_at = claimed_at - 1000 WHERE id = 'stale'")
    assert q.reclaim_stale(timeout=1) == 1
    reclaimed = q.claim("w2")
    assert reclaimed is not None and reclaimed["job_id"] == "stale"


# --------------------------------------------------------------------------- #
# DatabaseRunRepository
# --------------------------------------------------------------------------- #
def test_run_repository_crud(components):
    _q, repo, _log = components
    repo.create({
        "run_id": "r1", "workflow_id": "wf", "workflow_name": "n",
        "nodes": {}, "status": RunStatus.QUEUED, "created_at": "t",
        "started_at": 1.0, "finished_at": None, "result": None,
    })
    rec = repo.get("r1")
    assert rec["status"] == RunStatus.QUEUED
    repo.patch_node("r1", "c", {"node_id": "c", "status": "succeeded", "outputs": {"v": 1}})
    assert repo.get("r1")["nodes"]["c"]["status"] == "succeeded"
    repo.update("r1", status=RunStatus.SUCCEEDED, finished_at=2.0)
    assert repo.get("r1")["status"] == RunStatus.SUCCEEDED
    assert repo.stats()["succeeded"] == 1
    repo.delete("r1")
    with pytest.raises(RunNotFoundError):
        repo.get("r1")


# --------------------------------------------------------------------------- #
# RunEventLog
# --------------------------------------------------------------------------- #
def test_event_log_order(components):
    _q, _repo, log = components
    log.append("r1", "run_started")
    log.append("r1", "node_succeeded", "c", {"status": "succeeded"})
    log.append("r1", "run_succeeded")
    evs = log.read_since("r1", 0)
    assert [e["kind"] for e in evs] == ["run_started", "node_succeeded", "run_succeeded"]
    assert [e["seq"] for e in evs] == [1, 2, 3]
    assert log.read_since("r1", 2)[0]["kind"] == "run_succeeded"


# --------------------------------------------------------------------------- #
# Worker 执行
# --------------------------------------------------------------------------- #
def test_worker_executes_success(components):
    q, repo, log = components
    payload = {"nodes": [{"id": "c", "node_type": "data.constant", "params": {"value": 7}}], "edges": []}
    job_id = q.enqueue(payload, job_id="run1", workflow_name="demo")
    worker = Worker(job_queue=q, repository=repo, event_log=log, worker_id="w-test")
    assert worker.run_once() is True
    rec = repo.get("run1")
    assert rec["status"] == RunStatus.SUCCEEDED
    assert rec["nodes"]["c"]["status"] == "succeeded"
    assert rec["nodes"]["c"]["outputs"]["value"] == 7
    kinds = [e["kind"] for e in log.read_since("run1", 0)]
    assert "run_started" in kinds and "run_succeeded" in kinds


def test_worker_executes_failure(components):
    q, repo, log = components
    # 不存在的节点类型 -> validate_workflow 抛错 -> 运行标记 FAILED
    payload = {"nodes": [{"id": "x", "node_type": "nope.missing", "params": {}}], "edges": []}
    q.enqueue(payload, job_id="run2", workflow_name="bad")
    worker = Worker(job_queue=q, repository=repo, event_log=log, worker_id="w-test")
    worker.run_once()
    rec = repo.get("run2")
    assert rec["status"] == RunStatus.FAILED
    assert log.read_since("run2", 0)[-1]["kind"] == "run_failed"


# --------------------------------------------------------------------------- #
# RunService worker 后端（生产者/消费者集成）
# --------------------------------------------------------------------------- #
def test_runservice_worker_backend_end_to_end(components):
    q, repo, log = components
    svc = RunService(
        backend="worker", repository=repo, job_queue=q, event_log=log, run_workers=4
    )
    # 生产者：仅入队
    resp = svc.submit(
        [{"id": "c", "node_type": "data.constant", "params": {"value": 42}}],
        [],
        workflow_name="via-worker",
    )
    assert resp["status"] == RunStatus.QUEUED
    assert q.pending_count() == 1
    # 消费者：worker 出队执行
    worker = Worker(job_queue=q, repository=repo, event_log=log, worker_id="w-e2e")
    assert worker.run_once() is True
    rec = repo.get(resp["run_id"])
    assert rec["status"] == RunStatus.SUCCEEDED
    assert rec["nodes"]["c"]["outputs"]["value"] == 42
    # API（生产者侧）读取共享运行态可见
    assert svc.get(resp["run_id"])["status"] == RunStatus.SUCCEEDED


def test_runservice_local_backend_unchanged(components):
    """默认 local 后端行为不变：进程内执行，立即 running。"""
    q, repo, log = components
    svc = RunService(backend="local", repository=repo, job_queue=q, event_log=log)
    resp = svc.submit(
        [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}], [], workflow_name="local"
    )
    assert resp["status"] == RunStatus.RUNNING
    # local 不写任务队列
    assert q.pending_count() == 0
    rec = svc.wait(resp["run_id"], timeout=5)
    assert rec["status"] == RunStatus.SUCCEEDED


def test_run_completion_triggers_notification(monkeypatch):
    """回归：运行结束后必须真正触发 notify_run_finished（曾经因错误的导入路径静默失败）。"""
    import app.notifications.service as svc_mod

    calls = []
    monkeypatch.setattr(
        svc_mod.notification_service,
        "notify_run_finished",
        lambda **kw: calls.append(kw),
    )
    svc = RunService(backend="local")
    r = svc.submit(
        [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}], [], workflow_name="n"
    )
    svc.wait(r["run_id"], timeout=5)
    assert any(
        c.get("run_id") == r["run_id"] and c.get("status") == "succeeded" for c in calls
    )
