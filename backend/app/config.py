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
    # M4：JWT 密钥与有效期（生产环境务必通过环境变量覆盖）
    SECRET_KEY: str = os.getenv(
        "QF_SECRET_KEY",
        "qf-dev-secret-change-me-8f3b2a1c9d4e5f6a",
    )
    TOKEN_EXPIRE_MINUTES: int = int(os.getenv("QF_TOKEN_EXPIRE_MINUTES", "1440"))


settings = Settings()
