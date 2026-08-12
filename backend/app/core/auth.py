"""认证依赖（M4）：get_current_user / get_current_user_optional / require_roles。

- 认证始终可用；未认证请求按各路由设计决定是否放行（见路由注释）。
- 角色：``admin`` > ``user`` > ``viewer``。首个注册用户为 admin。
"""

from __future__ import annotations

from typing import Callable, List, Optional

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from .security import decode_token
from .users import USER_REPOSITORY

_bearer = HTTPBearer(auto_error=False)


def _user_from_credentials(
    credentials: Optional[HTTPAuthorizationCredentials],
) -> Optional[dict]:
    if credentials is None or not credentials.credentials:
        return None
    payload = decode_token(credentials.credentials)
    if payload is None:
        return None
    return USER_REPOSITORY.get(payload["uid"])


def get_current_user_optional(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> Optional[dict]:
    """取当前用户；无令牌或令牌无效返回 None（不报错）。"""
    return _user_from_credentials(credentials)


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer),
) -> dict:
    """取当前用户；未认证抛 401。"""
    user = _user_from_credentials(credentials)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未认证或令牌已失效",
            headers={"WWW-Authenticate": "Bearer"},
        )
    return user


def require_roles(*roles: str) -> Callable:
    """按角色限制访问（admin/user/viewer）。"""

    def dependency(user: dict = Depends(get_current_user)) -> dict:
        if user["role"] not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"需要角色 {'/'.join(roles)}，当前为 {user['role']}",
            )
        return user

    return dependency
