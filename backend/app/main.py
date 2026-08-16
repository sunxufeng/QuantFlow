"""QuantFlow 后端入口。

启动：
    cd backend && uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import os
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import (
    alerts,
    auth,
    backtest,
    execution,
    execution_cost,
    export as export_api,
    factor_scoring,
    factors,
    factors_eng,
    logs,
    llm,
    market,
    market_regime,
    ml_analytics,
    monitoring,
    notifications,
    portfolio_opt_ext,
    portfolio_i,
    projects,
    reports_analytics,
    risk_analytics,
    risk_attrib,
    strategies_ext,
    runs,
    schedules,
    settings as settings_api,
    tokens,
    trading,
    workflows,
    workspace as workspace_api,
)
from .config import settings
from .core import runs as run_module
from .core.logging_store import RequestContextMiddleware, install as install_logging
from .nodes import discover

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("quantflow")

app = FastAPI(
    title="QuantFlow 量化工作流平台",
    description="可视化量化工作流平台（股票 / 基金 / 期货 回测 + 工作流编排）",
    version=settings.APP_VERSION,
    # 文档路径统一收口到 /api 前缀，使 Swagger/OpenAPI 能经反向代理（prod/docker）直接访问。
    docs_url="/api/docs",
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(RequestContextMiddleware)

install_logging()

# V1.1 N6：按环境变量选择运行后端。
# - local（默认）：进程内线程池执行，运行态存内存（历史行为，零变化）。
# - worker：API 仅入队共享任务队列，由独立 quantflow-worker 进程消费执行；
#   运行态/事件落共享 SQLite，跨进程可见。
_RUN_BACKEND = os.getenv("QF_RUN_BACKEND", "local")
if _RUN_BACKEND not in ("local", "worker"):
    logger.warning("未知 QF_RUN_BACKEND=%r，回退 local", _RUN_BACKEND)
    _RUN_BACKEND = "local"
if _RUN_BACKEND == "worker":
    from .core.runs import RunService

    run_module.RUN_SERVICE = RunService(backend="worker")
    logger.info("运行后端=worker（API 入队，quantflow-worker 进程消费）")
else:
    logger.info("运行后端=local（进程内线程池执行）")


# 前端顶层错误边界上报入口（无需鉴权，便于在登录前/崩溃时也能收集真实错误）。
from pydantic import BaseModel


class ClientErrorPayload(BaseModel):
    message: str = ""
    stack: str = ""
    phase: str = ""


@app.post("/api/client-error")
async def client_error(payload: ClientErrorPayload):
    logger.error(
        "[CLIENT-ERROR] phase=%s message=%s stack=%s",
        payload.phase,
        payload.message,
        payload.stack[:2000] if payload.stack else "",
    )
    return {"ok": True}

app.include_router(workflows.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(tokens.router, prefix="/api")
app.include_router(factors.router, prefix="/api")
app.include_router(factors_eng.router, prefix="/api")
app.include_router(factor_scoring.router, prefix="/api")
app.include_router(notifications.router, prefix="/api")
app.include_router(llm.router, prefix="/api")
app.include_router(schedules.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(monitoring.router, prefix="/api")
app.include_router(execution.router, prefix="/api")
app.include_router(settings_api.router, prefix="/api")
app.include_router(trading.router, prefix="/api")
app.include_router(portfolio_opt_ext.router, prefix="/api")
app.include_router(portfolio_i.router, prefix="/api")
app.include_router(risk_analytics.router, prefix="/api")
app.include_router(reports_analytics.router, prefix="/api")
app.include_router(risk_attrib.router, prefix="/api")
app.include_router(market_regime.router, prefix="/api")
app.include_router(ml_analytics.router, prefix="/api")
app.include_router(strategies_ext.router, prefix="/api")
app.include_router(alerts.router, prefix="/api")
app.include_router(workspace_api.router, prefix="/api")
app.include_router(export_api.router, prefix="/api")
app.include_router(execution_cost.router, prefix="/api")

_START_TIME = time.time()


@app.on_event("startup")
async def startup() -> None:
    discover()
    logger.info("节点库加载完成，共 %d 种节点", _node_count())
    from .core.scheduler import workflow_scheduler
    from .market.scheduler import data_sync_service
    from .factors import library as factor_library

    data_sync_service.start()
    workflow_scheduler.start()
    try:
        from .alerts.scheduler import start as alerts_scheduler_start

        alerts_scheduler_start()
    except Exception as exc:  # pragma: no cover - 启动容错
        logger.warning("预警自动评估调度启动失败（可忽略）：%s", exc)
    try:
        seeded = factor_library.seed_defaults()
        if seeded:
            logger.info("因子库已写入 %d 个内置因子", seeded)
    except Exception as exc:  # pragma: no cover - 启动容错
        logger.warning("因子库初始化失败（可忽略）：%s", exc)


def _node_count() -> int:
    from .core.registry import REGISTRY

    return len(REGISTRY.all())


@app.on_event("shutdown")
async def shutdown() -> None:
    from .core.scheduler import workflow_scheduler
    from .market.scheduler import data_sync_service

    workflow_scheduler.shutdown()
    data_sync_service.shutdown()
    try:
        from .alerts.scheduler import shutdown as alerts_scheduler_shutdown

        alerts_scheduler_shutdown()
    except Exception:  # pragma: no cover
        pass


@app.get("/api/health", summary="健康检查")
def health() -> dict:
    run_service = run_module.RUN_SERVICE
    run_stats = run_service.repository.stats()
    return {
        "status": "ok",
        "app": settings.APP_NAME,
        "version": app.version,
        "uptime_seconds": round(time.time() - _START_TIME, 1),
        "runs": {
            "total": run_stats.get("total", 0),
            "running": run_stats.get("running", 0),
            "succeeded": run_stats.get("succeeded", 0),
            "failed": run_stats.get("failed", 0),
        },
    }
