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


def provider_from_config(cfg: dict) -> LLMProvider:
    """按配置字典构造 provider（V1.4）。

    - provider=mock 或 enabled=False → MockProvider；
    - provider=openai 且 enabled=True → 需要 api_key，否则抛 ValueError（交由调用方回退 mock）。
    """
    provider = (cfg.get("provider") or "mock").lower()
    enabled = bool(cfg.get("enabled", True))
    if provider == "openai" and enabled:
        api_key = cfg.get("api_key") or ""
        if not api_key:
            raise ValueError("OpenAI 兼容模式需要 API Key")
        return OpenAIProvider(
            api_key=api_key,
            base_url=cfg.get("base_url") or "https://api.openai.com/v1",
            model=cfg.get("model") or "gpt-4o-mini",
            timeout=float(cfg.get("timeout", 90.0)),
        )
    return MockProvider(model=cfg.get("model") or "mock-1")


class RoutingProvider(LLMProvider):
    """多 provider 路由：按序尝试，第一个成功即返回；全部失败抛最后一个错误。

    V3.3 引入，用于「主模型不可用自动切备用」与多模型选择。
    构造时只保留成功构建的 provider；若链为空则回退单个 MockProvider，
    避免配置错误导致 500。
    """

    name = "routing"

    def __init__(self, providers: List[LLMProvider]) -> None:
        if not providers:
            providers = [MockProvider(model="mock-1")]
        self._providers = list(providers)
        self.model = self._providers[0].model

    def is_configured(self) -> bool:
        return any(p.is_configured() for p in self._providers)

    def chat(
        self,
        messages: List[LLMMessage],
        *,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        last_exc: Optional[Exception] = None
        for p in self._providers:
            try:
                return p.chat(messages, temperature=temperature, max_tokens=max_tokens)
            except Exception as exc:  # 任一 provider 失败则尝试下一个
                last_exc = exc
                continue
        if last_exc is not None:
            raise RuntimeError(f"所有 LLM provider 均调用失败: {last_exc}") from last_exc
        raise RuntimeError("未配置任何可用的 LLM provider")

    def chain_info(self) -> List[dict]:
        return [
            {"name": p.name, "model": p.model, "configured": p.is_configured()}
            for p in self._providers
        ]


def build_provider(cfg: dict, *, strict: bool = False) -> LLMProvider:
    """按配置构造 provider：支持 ``providers`` 列表（多模型路由）或单配置。

    - 若 ``cfg["providers"]`` 为非空列表，逐条构造并包装为 RoutingProvider（任意
      一条构建失败仅跳过该条，不影响其余）；
    - 否则走原单配置逻辑。``strict=False`` 时缺 key 安全回退 mock（与历史行为一致，
      用于 /assist、/generate 等运行路径）；``strict=True`` 时缺 key 抛 ValueError
      （用于 /config/test 连通性校验，保留「openai 缺 key → 400」契约）。
    """
    providers = cfg.get("providers")
    if isinstance(providers, list) and providers:
        built: List[LLMProvider] = []
        for sub in providers:
            if not isinstance(sub, dict):
                continue
            try:
                built.append(provider_from_config(sub))
            except Exception:
                continue
        if not built:
            if strict:
                raise ValueError("未配置任何可用的 LLM provider")
            built = [MockProvider(model=cfg.get("model") or "mock-1")]
        return RoutingProvider(built)
    if strict:
        return provider_from_config(cfg)  # 缺 key 直接抛 ValueError
    try:
        return provider_from_config(cfg)
    except ValueError:
        return MockProvider(model=cfg.get("model") or "mock-1")


def get_provider() -> LLMProvider:
    """按配置（settings store 优先，环境变量兜底）返回单例 provider。

    provider=mock 或无 key 时回退 mock；openai 且配置了 key 时返回真实 provider；
    配置了 ``providers`` 列表时返回按序 fallback 的 RoutingProvider（V3.3）。
    """
    global _PROVIDER
    if _PROVIDER is not None:
        return _PROVIDER

    from .config import load_llm_config

    cfg = load_llm_config()
    _PROVIDER = build_provider(cfg)
    return _PROVIDER


def reset_provider() -> None:
    """测试 / 配置变更后重置单例。"""
    global _PROVIDER
    _PROVIDER = None
