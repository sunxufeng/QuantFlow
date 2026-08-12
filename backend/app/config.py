"""应用配置（环境变量驱动，默认本地开发）。"""

from __future__ import annotations

import os


class Settings:
    APP_NAME: str = os.getenv("QF_APP_NAME", "quantflow")
    DEBUG: bool = os.getenv("QF_DEBUG", "1") == "1"
    CORS_ORIGINS: list[str] = os.getenv(
        "QF_CORS_ORIGINS", "http://localhost:5173,http://127.0.0.1:5173"
    ).split(",")
    # V2.0：MongoDB/Redis 连接串（M1 原型暂用内存态）
    MONGO_URI: str = os.getenv("QF_MONGO_URI", "mongodb://localhost:27017")
    REDIS_URI: str = os.getenv("QF_REDIS_URI", "redis://localhost:6379")


settings = Settings()
