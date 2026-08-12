"""监控 API（M4-4）：系统概览 + Prometheus 指标。"""

from __future__ import annotations

import os
import time

from fastapi import APIRouter, Depends, Response

from ..config import settings
from ..core.auth import get_current_user, require_roles
from ..core.projects import PROJECT_REPOSITORY
from ..core.registry import REGISTRY
from ..core import runs as run_module
from ..core.users import USER_REPOSITORY
from ..core.ws import RUN_CONNECTIONS

router = APIRouter(prefix="/monitoring", tags=["monitoring"])

_START_TIME = time.time()


def _uptime_seconds() -> float:
    return round(time.time() - _START_TIME, 1)


@router.get("/overview", summary="系统概览（运行队列/节点/连接/用户/项目）")
def overview(user: dict = Depends(get_current_user)) -> dict:
    run_stats = run_module.RUN_SERVICE.repository.stats()
    base = {
        "server": {
            "app": settings.APP_NAME,
            "version": settings.APP_VERSION,
            "uptime_seconds": _uptime_seconds(),
            "pid": os.getpid(),
        },
        "runs": {
            "total": run_stats.get("total", 0),
            "running": run_stats.get("running", 0),
            "succeeded": run_stats.get("succeeded", 0),
            "failed": run_stats.get("failed", 0),
            "capacity": run_module.RUN_SERVICE.run_workers + run_module.RUN_SERVICE.queue_size,
            "queued": max(0, run_stats.get("total", 0) - run_stats.get("running", 0)),
        },
        "nodes": {"registered": len(REGISTRY.all())},
        "ws_connections": RUN_CONNECTIONS.connection_count(),
        "requested_by": user["username"],
    }
    if user["role"] == "admin":
        base["users"] = {"total": USER_REPOSITORY.count()}
        base["projects"] = {"total": PROJECT_REPOSITORY.count()}
    return base


@router.get("/metrics", summary="Prometheus 指标（admin）")
def metrics(user: dict = Depends(require_roles("admin"))) -> Response:
    run_stats = run_module.RUN_SERVICE.repository.stats()

    def counter(name: str, value: int) -> str:
        return f"quantflow_{name} {value}"

    lines = [
        "# HELP quantflow_uptime_seconds 服务运行时长",
        "# TYPE quantflow_uptime_seconds gauge",
        f"quantflow_uptime_seconds {_uptime_seconds()}",
        "# HELP quantflow_runs_total 累计运行数",
        "# TYPE quantflow_runs_total counter",
        counter("runs_total", run_stats.get("total", 0)),
        "# HELP quantflow_runs_running 运行中",
        "# TYPE quantflow_runs_running gauge",
        counter("runs_running", run_stats.get("running", 0)),
        counter("runs_succeeded", run_stats.get("succeeded", 0)),
        counter("runs_failed", run_stats.get("failed", 0)),
        counter("runs_queued", max(0, run_stats.get("total", 0) - run_stats.get("running", 0))),
        counter("nodes_registered", len(REGISTRY.all())),
        counter("ws_connections", RUN_CONNECTIONS.connection_count()),
        counter("users_total", USER_REPOSITORY.count()),
        counter("projects_total", PROJECT_REPOSITORY.count()),
    ]
    return Response(
        content="\n".join(lines) + "\n", media_type="text/plain; version=0.0.4"
    )
