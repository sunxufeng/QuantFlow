"""QuantFlow 后端入口。

启动：
    cd backend && uvicorn app.main:app --reload --port 8000
"""

from __future__ import annotations

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .api import market, runs, workflows
from .config import settings
from .nodes import discover

logging.basicConfig(
    level=logging.DEBUG if settings.DEBUG else logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
logger = logging.getLogger("quantflow")

app = FastAPI(
    title="QuantFlow 量化工作流平台",
    description="可视化量化工作流平台（M1 技术预研原型）",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.CORS_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(workflows.router, prefix="/api")
app.include_router(market.router, prefix="/api")
app.include_router(runs.router, prefix="/api")


@app.on_event("startup")
async def startup() -> None:
    discover()
    logger.info("节点库加载完成，共 %d 种节点", _node_count())


def _node_count() -> int:
    from .core.registry import REGISTRY

    return len(REGISTRY.all())


@app.get("/api/health", summary="健康检查")
def health() -> dict:
    return {"status": "ok", "app": settings.APP_NAME, "version": app.version}
