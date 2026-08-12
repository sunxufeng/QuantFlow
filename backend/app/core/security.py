"""密码哈希与 JWT 令牌（M4 用户体系）。

- 密码：PBKDF2-HMAC-SHA256（210_000 次迭代，随机 16B 盐），校验用
  :func:`hmac.compare_digest` 防时序侧信道；
- 令牌：PyJWT HS256，payload 含 uid/username/role/exp；
- 密钥与有效期由环境变量 ``QF_SECRET_KEY`` / ``QF_TOKEN_EXPIRE_MINUTES`` 控制。
"""

from __future__ import annotations

import hashlib
import hmac
import os
import time
from typing import Dict, Optional

import jwt as pyjwt

from ..config import settings

_PBKDF2_ITERATIONS = 210_000
_ALGORITHM = "HS256"


def hash_password(password: str) -> tuple[str, str]:
    """返回 ``(digest_hex, salt_hex)``。"""
    salt = os.urandom(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return digest.hex(), salt.hex()


def verify_password(password: str, digest_hex: str, salt_hex: str) -> bool:
    salt = bytes.fromhex(salt_hex)
    digest = hashlib.pbkdf2_hmac(
        "sha256", password.encode("utf-8"), salt, _PBKDF2_ITERATIONS
    )
    return hmac.compare_digest(digest.hex(), digest_hex)


def create_token(user: Dict[str, str]) -> str:
    now = int(time.time())
    payload = {
        "uid": user["id"],
        "username": user["username"],
        "role": user["role"],
        "iat": now,
        "exp": now + settings.TOKEN_EXPIRE_MINUTES * 60,
    }
    return pyjwt.encode(payload, settings.SECRET_KEY, algorithm=_ALGORITHM)


def decode_token(token: str) -> Optional[dict]:
    """解码令牌；非法/过期返回 None。"""
    try:
        payload = pyjwt.decode(token, settings.SECRET_KEY, algorithms=[_ALGORITHM])
        return payload
    except pyjwt.PyJWTError:
        return None
