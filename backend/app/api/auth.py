"""认证 API：注册 / 登录 / 当前用户（M4-1）。

- 注册：用户名唯一、密码 ≥ 6 位，首个注册用户为 admin；
- 登录：校验成功后签发 JWT（HS256，24h 默认）；
- /me：返回当前令牌对应的用户。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status

from ..config import settings
from ..core.auth import get_current_user
from ..core.security import create_token
from ..core.users import USER_REPOSITORY, UserAlreadyExistsError
from ..models.schemas import AuthTokenOut, LoginIn, RegisterIn, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


@router.post(
    "/register",
    response_model=AuthTokenOut,
    status_code=status.HTTP_201_CREATED,
    summary="注册",
)
def register(payload: RegisterIn) -> AuthTokenOut:
    try:
        user = USER_REPOSITORY.create(payload.username, payload.password)
    except UserAlreadyExistsError:
        raise HTTPException(status_code=409, detail="用户名已存在") from None
    return _token_response(user)


@router.post("/login", response_model=AuthTokenOut, summary="登录")
def login(payload: LoginIn) -> AuthTokenOut:
    user = USER_REPOSITORY.authenticate(payload.username, payload.password)
    if user is None:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    return _token_response(user)


@router.get("/me", response_model=UserOut, summary="当前用户")
def me(user: dict = Depends(get_current_user)) -> dict:
    return user


def _token_response(user: dict) -> AuthTokenOut:
    return AuthTokenOut(
        token=create_token(user),
        expires_in=settings.TOKEN_EXPIRE_MINUTES * 60,
        user=UserOut(**user),
    )
