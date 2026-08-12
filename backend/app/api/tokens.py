"""API Token 管理端点（V1.1 N2）。

- ``POST   /api/tokens``        创建令牌（明文 token 仅在此返回一次）
- ``GET    /api/tokens``        列出当前用户的有效/已吊销令牌
- ``DELETE /api/tokens/{prefix}`` 吊销令牌
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field

from ..core.api_tokens import API_TOKEN_REPOSITORY
from ..core.auth import get_current_user

router = APIRouter(prefix="/tokens", tags=["tokens"])


class TokenCreateIn(BaseModel):
    name: str = Field(..., min_length=1, max_length=80, description="令牌用途标识")
    scopes: List[str] = Field(
        default_factory=lambda: ["*"], description="权限范围，[*] 表示全权限"
    )


class TokenOut(BaseModel):
    id: str
    name: str
    prefix: str
    scopes: List[str]
    created_at: str
    last_used_at: Optional[str] = None
    revoked: bool = False


class TokenCreateOut(TokenOut):
    token: str  # 一次性明文，仅创建时返回


@router.post(
    "",
    response_model=TokenCreateOut,
    status_code=status.HTTP_201_CREATED,
    summary="创建 API Token",
)
def create_token(payload: TokenCreateIn, user: dict = Depends(get_current_user)) -> dict:
    return API_TOKEN_REPOSITORY.generate(user["id"], payload.name, payload.scopes)


@router.get("", response_model=List[TokenOut], summary="列出我的 API Token")
def list_tokens(user: dict = Depends(get_current_user)) -> List[dict]:
    return API_TOKEN_REPOSITORY.list(user["id"])


@router.delete("/{prefix}", status_code=status.HTTP_204_NO_CONTENT, summary="吊销 API Token")
def revoke_token(prefix: str, user: dict = Depends(get_current_user)) -> Response:
    if not API_TOKEN_REPOSITORY.revoke(user["id"], prefix):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="令牌不存在或已吊销")
    return Response(status_code=status.HTTP_204_NO_CONTENT)
