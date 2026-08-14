"""应用配置（环境变量驱动，默认本地开发）。"""

from __future__ import annotations

import os


class Settings:
    APP_NAME: str = os.getenv("QF_APP_NAME", "quantflow")
    # 版本号单一来源（health / monitoring / OpenAPI 共用）
    APP_VERSION: str = "3.2.0"
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
    # V1.1 N1：LLM 策略助手
    # provider=mock 时无需 key，使用确定性 mock 响应（可测、可演示）
    # provider=openai 时走 OpenAI 兼容 /chat/completions（如 DeepSeek/通义/自建网关）
    LLM_PROVIDER: str = os.getenv("QF_LLM_PROVIDER", "mock")
    LLM_API_KEY: str = os.getenv("QF_LLM_API_KEY", "")
    LLM_BASE_URL: str = os.getenv(
        "QF_LLM_BASE_URL", "https://api.openai.com/v1"
    )
    LLM_MODEL: str = os.getenv("QF_LLM_MODEL", "gpt-4o-mini")
    LLM_TEMPERATURE: float = float(os.getenv("QF_LLM_TEMPERATURE", "0.2"))
    LLM_MAX_TOKENS: int = int(os.getenv("QF_LLM_MAX_TOKENS", "1024"))


settings = Settings()
