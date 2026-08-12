"""LLM 策略助手 API（V1.1 N1）。

POST /api/llm/assist —— 文本对话式策略建议（需鉴权）
GET  /api/llm/status —— 当前 provider / 是否已配置真实 key
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from ..config import settings
from ..core.auth import get_current_user
from ..core.llm import LLMMessage, get_provider

router = APIRouter()


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


@router.post("/llm/assist", response_model=AssistResponse, summary="LLM 策略建议")
def assist(
    req: AssistRequest,
    _user=Depends(get_current_user),
) -> AssistResponse:
    provider = get_provider()
    messages: List[LLMMessage] = []
    if req.system:
        messages.append(LLMMessage(role="system", content=req.system))
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
