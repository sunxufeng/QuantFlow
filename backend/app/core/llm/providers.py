"""LLM provider 实现（V1.1 N1）。

设计要点：
- 统一 chat(messages) -> str 接口，便于节点 / API / 测试复用。
- MockProvider 不依赖网络与 key，输出结构化、确定性的「策略助手」建议，
  保证无 key 环境下功能闭环（可测、可演示）。
- OpenAIProvider 走 OpenAI 兼容协议（DeepSeek / 通义 / 自建网关均兼容），
  缺 key 时显式报错，避免静默失效。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import List, Optional

import httpx

from ...config import settings


@dataclass
class LLMMessage:
    role: str  # system | user | assistant
    content: str


class LLMProvider:
    """统一聊天接口。"""

    name: str = "base"
    model: str = ""

    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        raise NotImplementedError

    def is_configured(self) -> bool:
        """provider 是否已具备真实调用条件（mock 永远 True）。"""
        return True


class MockProvider(LLMProvider):
    """确定性 mock：把最近一条 user 消息转成结构化的策略助手建议。

    不联网、不需要 key，用于默认环境 / 单元测试 / 演示。
    """

    name = "mock"

    def __init__(self, model: str = "mock-1") -> None:
        self.model = model

    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        last_user = next(
            (m.content for m in reversed(messages) if m.role == "user"), ""
        )
        return self._render(last_user)

    @staticmethod
    def _render(prompt: str) -> str:
        p = (prompt or "").strip()
        return (
            "【QuantFlow 策略助手 · 演示模式 (mock)】\n"
            "当前未配置 LLM API Key，以下为基于本地规则的结构化建议：\n\n"
            f"1. 你的诉求：{p or '（空）'}\n"
            "2. 建议节点组合：data.常量/数列 → 指标(动量/均线) → 因子(IC 分析) → 回测(收益/最大回撤)\n"
            "3. 下一步：在节点画布拖入上述节点并连线，运行后查看因子 IC 与分层收益。\n"
            "提示：配置 QF_LLM_API_KEY 后切换 QF_LLM_PROVIDER=openai 即可启用真实大模型。"
        )


class OpenAIProvider(LLMProvider):
    """OpenAI 兼容 chat/completions（DeepSeek / 通义 / 自建网关）。"""

    name = "openai"

    def __init__(
        self,
        *,
        api_key: str,
        base_url: str,
        model: str,
        timeout: float = 90.0,
    ) -> None:
        if not api_key:
            raise ValueError("OpenAIProvider 需要 QF_LLM_API_KEY")
        self._api_key = api_key
        self._base_url = base_url.rstrip("/")
        self.model = model
        self._timeout = timeout

    def is_configured(self) -> bool:
        return bool(self._api_key)

    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        payload = {
            "model": self.model,
            "messages": [{"role": m.role, "content": m.content} for m in messages],
            "temperature": (
                temperature if temperature is not None else settings.LLM_TEMPERATURE
            ),
            "max_tokens": (
                max_tokens if max_tokens is not None else settings.LLM_MAX_TOKENS
            ),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        try:
            resp = httpx.post(
                f"{self._base_url}/chat/completions",
                json=payload,
                headers=headers,
                timeout=self._timeout,
            )
            resp.raise_for_status()
            data = resp.json()
            return data["choices"][0]["message"]["content"]
        except httpx.HTTPStatusError as exc:  # 4xx/5xx
            body = exc.response.text[:300]
            raise RuntimeError(f"LLM 调用失败 {exc.response.status_code}: {body}") from exc
        except (httpx.HTTPError, KeyError, IndexError, json.JSONDecodeError) as exc:
            raise RuntimeError(f"LLM 调用异常: {exc}") from exc


_PROVIDER: Optional[LLMProvider] = None


def get_provider() -> LLMProvider:
    """按 settings 返回单例 provider。

    provider=mock 或无 key 时回退 mock；openai 且配置了 key 时返回真实 provider。
    """
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER

    provider = settings.LLM_PROVIDER.lower()
    if provider == "openai" and settings.LLM_API_KEY:
        _PROVIDER = OpenAIProvider(
            api_key=settings.LLM_API_KEY,
            base_url=settings.LLM_BASE_URL,
            model=settings.LLM_MODEL,
        )
    else:
        _PROVIDER = MockProvider(model=settings.LLM_MODEL)
    return _PROVIDER


def reset_provider() -> None:
    """测试 / 配置变更后重置单例。"""
    global _PROVIDER
    _PROVIDER = None
