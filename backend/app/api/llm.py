"""LLM 策略助手 API（V1.1 N1 + V1.4 配置页）。

POST /api/llm/assist      —— 文本对话式策略建议（需鉴权）
GET  /api/llm/status      —— 当前 provider / 是否已配置真实 key
GET  /api/llm/config      —— 当前 LLM 配置（API Key 脱敏）
PUT  /api/llm/config      —— 保存 LLM 配置（持久化 + 重置 provider 单例）
POST /api/llm/config/test —— 测试配置连通性（不落库，可选部分覆盖）
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..config import settings
from ..core.auth import get_current_user
from ..core.llm import (
    LLMMessage,
    get_provider,
    load_llm_config,
    mask_api_key,
    provider_from_config,
    reset_provider,
    save_llm_config,
)

router = APIRouter()

# 未显式传入 system 时使用的默认量化领域系统提示（让用户开箱即用获得专业建议）
DEFAULT_LLM_SYSTEM = (
    "你是一名资深的量化投资策略研究员，熟悉 A 股与期货市场的回测、因子、"
    "均线/动量等技术指标。请用简洁、结构化的中文回答用户的策略问题，"
    "必要时给出可落地的节点组合建议（数据 → 指标/因子 → 回测）。"
)


class ChatMessage(BaseModel):
    role: str = "user"
    content: str


class AssistRequest(BaseModel):
    prompt: str = Field(..., description="用户提示词")
    system: Optional[str] = Field(None, description="系统提示（覆盖默认）")
    history: List[ChatMessage] = Field(default_factory=list, description="多轮上下文（可选）")


class AssistResponse(BaseModel):
    text: str
    provider: str
    model: str
    configured: bool


class LLMConfigUpdate(BaseModel):
    """配置更新：未传字段保持不变；api_key 传空串表示保留现有 key。"""

    provider: Optional[str] = None
    base_url: Optional[str] = None
    api_key: Optional[str] = None
    model: Optional[str] = None
    system_prompt: Optional[str] = None
    temperature: Optional[float] = None
    max_tokens: Optional[int] = None
    timeout: Optional[float] = None
    enabled: Optional[bool] = None


class LLMConfigOut(BaseModel):
    provider: str
    base_url: str
    model: str
    system_prompt: str
    temperature: float
    max_tokens: int
    timeout: float
    enabled: bool
    has_api_key: bool
    api_key_masked: str


def _config_out(cfg: dict) -> LLMConfigOut:
    return LLMConfigOut(
        provider=cfg.get("provider", "mock"),
        base_url=cfg.get("base_url", ""),
        model=cfg.get("model", ""),
        system_prompt=cfg.get("system_prompt", ""),
        temperature=float(cfg.get("temperature", 0.2)),
        max_tokens=int(cfg.get("max_tokens", 1024)),
        timeout=float(cfg.get("timeout", 90.0)),
        enabled=bool(cfg.get("enabled", True)),
        has_api_key=bool(cfg.get("api_key")),
        api_key_masked=mask_api_key(cfg.get("api_key", "")),
    )


def _merge_patch(cur: dict, patch: dict) -> dict:
    """应用 Partial 更新；api_key 空串保留原值（避免误清空）。"""
    if "api_key" in patch:
        if not patch["api_key"]:
            patch["api_key"] = cur.get("api_key", "")
    cur.update(patch)
    cur["provider"] = (cur.get("provider") or "mock").lower()
    return cur


@router.post("/llm/assist", response_model=AssistResponse, summary="LLM 策略建议")
def assist(
    req: AssistRequest,
    _user=Depends(get_current_user),
) -> AssistResponse:
    provider = get_provider()
    messages: List[LLMMessage] = []
    if req.system:
        messages.append(LLMMessage(role="system", content=req.system))
    else:
        # 配置里自定义的 system prompt 优先于内置默认
        cfg = load_llm_config()
        messages.append(
            LLMMessage(
                role="system",
                content=cfg.get("system_prompt") or DEFAULT_LLM_SYSTEM,
            )
        )
    for m in req.history:
        messages.append(LLMMessage(role=m.role, content=m.content))
    messages.append(LLMMessage(role="user", content=req.prompt))
    text = provider.chat(messages)
    return AssistResponse(
        text=text,
        provider=provider.name,
        model=provider.model,
        configured=provider.is_configured(),
    )


@router.get("/llm/status", summary="LLM provider 状态")
def status(_user=Depends(get_current_user)) -> dict:
    provider = get_provider()
    return {
        "provider": provider.name,
        "model": provider.model,
        "configured": provider.is_configured(),
        "env_provider": settings.LLM_PROVIDER,
    }


@router.get("/llm/config", response_model=LLMConfigOut, summary="读取 LLM 配置")
def get_config(_user=Depends(get_current_user)) -> LLMConfigOut:
    return _config_out(load_llm_config())


@router.put("/llm/config", response_model=LLMConfigOut, summary="保存 LLM 配置")
def put_config(req: LLMConfigUpdate, _user=Depends(get_current_user)) -> LLMConfigOut:
    cur = load_llm_config()
    patch = req.model_dump(exclude_unset=True)
    merged = _merge_patch(cur, patch)
    saved = save_llm_config(merged)
    reset_provider()  # 让下一次调用使用新配置
    return _config_out(saved)


@router.post("/llm/config/test", summary="测试 LLM 配置连通性")
def test_config(
    req: Optional[LLMConfigUpdate] = None,
    _user=Depends(get_current_user),
) -> dict:
    """用当前（或传入的部分覆盖）配置做一次最小调用验证连通性。

    不落库。Mock 模式直接返回成功；OpenAI 兼容模式实际发起一次请求。
    """
    if req is None:
        cfg = load_llm_config()
    else:
        cur = load_llm_config()
        cfg = _merge_patch(cur, req.model_dump(exclude_unset=True))
    try:
        provider = provider_from_config(cfg)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    try:
        sample = provider.chat(
            [LLMMessage(role="user", content="ping")],
            max_tokens=16,
            temperature=0,
        )
        return {
            "ok": True,
            "provider": provider.name,
            "model": provider.model,
            "sample": (sample or "")[:200],
        }
    except Exception as exc:  # 网络/鉴权/超时等错误
        return {
            "ok": False,
            "provider": provider.name,
            "model": provider.model,
            "error": str(exc)[:300],
        }


# 兼容旧导入：default_llm_config 已迁至 core.llm.config
__all__ = [
    "AssistRequest",
    "AssistResponse",
    "LLMConfigUpdate",
    "LLMConfigOut",
]
