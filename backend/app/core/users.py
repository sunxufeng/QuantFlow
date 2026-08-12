"""用户仓库（SQLite，M4）。"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from .db import db
from .security import hash_password, verify_password


class UserAlreadyExistsError(ValueError):
    pass


class UserNotFoundError(KeyError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class UserRepository:
    """用户表访问。首注册用户自动获得 admin 角色。"""

    def create(self, username: str, password: str) -> dict:
        now = _utc_now()
        if self.get_by_username(username):
            raise UserAlreadyExistsError(username)
        digest, salt = hash_password(password)
        role = "admin" if self.count() == 0 else "user"
        user_id = f"u_{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO users (id, username, password_hash, salt, role, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (user_id, username, digest, salt, role, now, now),
        )
        return self.get(user_id)

    def get(self, user_id: str) -> Optional[dict]:
        return db.query_one(
            "SELECT id, username, role, created_at FROM users WHERE id = ?", (user_id,)
        )

    def get_with_credentials(self, username: str) -> Optional[dict]:
        return db.query_one(
            "SELECT id, username, password_hash, salt, role, created_at FROM users WHERE username = ?",
            (username,),
        )

    def get_by_username(self, username: str) -> Optional[dict]:
        return db.query_one(
            "SELECT id, username, role, created_at FROM users WHERE username = ?",
            (username,),
        )

    def authenticate(self, username: str, password: str) -> Optional[dict]:
        row = self.get_with_credentials(username)
        if row is None:
            return None
        if not verify_password(password, row["password_hash"], row["salt"]):
            return None
        return {
            "id": row["id"],
            "username": row["username"],
            "role": row["role"],
            "created_at": row["created_at"],
        }

    def list(self, limit: int = 100, offset: int = 0) -> List[dict]:
        return db.query(
            "SELECT id, username, role, created_at FROM users ORDER BY created_at "
            "LIMIT ? OFFSET ?",
            (limit, offset),
        )

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS n FROM users")
        return int(row["n"]) if row else 0


USER_REPOSITORY = UserRepository()
