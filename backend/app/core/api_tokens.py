"""API Token 仓库（V1.1 N2：API 代码式调用）。

令牌格式：``qf.<prefix>.<secret>``（prefix 16 hex，secret 64 hex）。
存储仅保存 prefix（定位键）与 secret 的 SHA-256（不可逆校验）；
完整令牌（含 secret）仅在创建时返回一次，其后不可再读取。

鉴权侧由 :mod:`app.core.auth` 透明支持：Bearer 头中以 ``qf.`` 开头即按
API Token 校验，否则按 JWT 校验，路由层无感知。
"""

from __future__ import annotations

import hashlib
import hmac
import secrets
import uuid
from datetime import datetime, timezone
from typing import List, Optional

from .db import db

_TOKEN_PREFIX = "qf"
_PREFIX_BYTES = 8  # → 16 hex
_SECRET_BYTES = 32  # → 64 hex


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _encode_scopes(scopes: Optional[List[str]]) -> str:
    return ",".join(scopes or ["*"])


def _decode_scopes(raw: Optional[str]) -> List[str]:
    if not raw:
        return ["*"]
    return raw.split(",")


class ApiTokenRepository:
    """用户级 API Token 生命周期管理。"""

    def generate(
        self, user_id: str, name: str, scopes: Optional[List[str]] = None
    ) -> dict:
        """创建令牌；返回结果含一次性明文 ``token``，落库仅存哈希。"""
        prefix = secrets.token_hex(_PREFIX_BYTES)
        secret = secrets.token_hex(_SECRET_BYTES)
        token = f"{_TOKEN_PREFIX}.{prefix}.{secret}"
        secret_hash = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        now = _utc_now()
        token_id = f"tok_{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO api_tokens "
            "(id, user_id, name, prefix, secret_hash, scopes, created_at, last_used_at, revoked_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, NULL, NULL)",
            (
                token_id,
                user_id,
                name,
                prefix,
                secret_hash,
                _encode_scopes(scopes),
                now,
            ),
        )
        return {
            "id": token_id,
            "token": token,
            "prefix": prefix,
            "name": name,
            "scopes": scopes or ["*"],
            "created_at": now,
        }

    def verify(self, token: str) -> Optional[str]:
        """校验令牌；通过返回 user_id，否则返回 None（并记录 last_used）。"""
        parts = token.split(".")
        if len(parts) != 3 or parts[0] != _TOKEN_PREFIX:
            return None
        prefix, secret = parts[1], parts[2]
        row = db.query_one(
            "SELECT user_id, secret_hash, revoked_at FROM api_tokens WHERE prefix = ?",
            (prefix,),
        )
        if row is None or row["revoked_at"] is not None:
            return None
        expected = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        if not hmac.compare_digest(expected, row["secret_hash"]):
            return None
        db.execute(
            "UPDATE api_tokens SET last_used_at = ? WHERE prefix = ?",
            (_utc_now(), prefix),
        )
        return row["user_id"]

    def list(self, user_id: str) -> List[dict]:
        rows = db.query(
            "SELECT id, name, prefix, scopes, created_at, last_used_at, revoked_at "
            "FROM api_tokens WHERE user_id = ? ORDER BY created_at DESC",
            (user_id,),
        )
        return [_public(r) for r in rows]

    def revoke(self, user_id: str, prefix: str) -> bool:
        res = db.execute(
            "UPDATE api_tokens SET revoked_at = ? "
            "WHERE prefix = ? AND user_id = ? AND revoked_at IS NULL",
            (_utc_now(), prefix, user_id),
        )
        return bool(res.rowcount)

    def admin_list(self, limit: int = 200) -> List[dict]:
        rows = db.query(
            "SELECT id, user_id, name, prefix, scopes, created_at, last_used_at, revoked_at "
            "FROM api_tokens ORDER BY created_at DESC LIMIT ?",
            (limit,),
        )
        return [_public(r, include_user=True) for r in rows]


def _public(row: dict, include_user: bool = False) -> dict:
    out = {
        "id": row["id"],
        "name": row["name"],
        "prefix": row["prefix"],
        "scopes": _decode_scopes(row.get("scopes")),
        "created_at": row["created_at"],
        "last_used_at": row.get("last_used_at"),
        "revoked": row.get("revoked_at") is not None,
    }
    if include_user:
        out["user_id"] = row.get("user_id")
    return out


API_TOKEN_REPOSITORY = ApiTokenRepository()
