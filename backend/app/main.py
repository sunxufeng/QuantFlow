"""QuantFlow 后端入口。

启动：
    cd backend && uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging
import time

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import auth, backtest, logs, market, monitoring, projects, runs, workflows
from .config import settings
from .core.logging_store import RequestContextMiddleware, install as install_logging
from .nodes import discover

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("quantflow")

app = FastAPI(
    title="QuantFlow 量化工作流平台",
    description="可视化量化工作流平台（V1.0）",
    version="1.0.0",
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

app.include_router(workflows.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(runs.router, prefix="/api")
app.include_router(backtest.router, prefix="/api")
app.include_router(auth.router, prefix="/api")
app.include_router(projects.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(monitoring.router, prefix="/api")

_START_TIME = time.time()


@app.on_event("startup")
async def startup() -> None:
    discover()
    logger.info("节点库加载完成，共 %d 种节点", _node_count())


def _node_count() -> int:
    from .core.registry import REGISTRY

    return len(REGISTRY.all())


@app.get("/api/health", summary="健康检查")
def health() -> dict:
    from .core.runs import RUN_SERVICE

    run_stats = RUN_SERVICE.repository.stats()
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
