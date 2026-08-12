"""LLM 策略助手抽象层（V1.1 N1）。

- LLMProvider: 统一 chat 接口
- MockProvider: 无网络、确定性响应（默认，无需 key）
- OpenAIProvider: OpenAI 兼容 /chat/completions（需 QF_LLM_API_KEY）
- get_provider(): 按 settings 单例工厂
"""

from __future__ import annotations

from .providers import (
    LLMMessage,
    LLMProvider,
    MockProvider,
    OpenAIProvider,
    get_provider,
    reset_provider,
)

__all__ = [
    "LLMMessage",
    "LLMProvider",
    "MockProvider",
    "OpenAIProvider",
    "get_provider",
    "reset_provider",
]
