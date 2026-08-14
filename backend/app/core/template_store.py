"""个人工作流模板持久化（V3.1 模板市场）。

在 SQLite 业务库上承载用户保存的可复用工作流模板，跨服务重启保留。
内置模板（BUILTIN_TEMPLATES）仍由 ``app.templates`` 提供，本存储只管用户模板。
"""

from __future__ import annotations

import json
import threading
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .db import db


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class TemplateNotFoundError(KeyError):
    pass


class TemplatePermissionError(PermissionError):
    pass


class TemplateStore:
    """用户工作流模板的 CRUD，基于共享 SQLite（db 单例已加锁）。"""

    _ensured = False
    _lock = threading.Lock()

    def _ensure(self) -> None:
        """幂等补齐 is_public 列（兼容旧库，V8.0 新增）。"""
        if TemplateStore._ensured:
            return
        with TemplateStore._lock:
            if TemplateStore._ensured:
                return
            cols = [r["name"] for r in db.query("PRAGMA table_info(workflow_templates)")]
            if "is_public" not in cols:
                db.execute(
                    "ALTER TABLE workflow_templates ADD COLUMN is_public INTEGER NOT NULL DEFAULT 0"
                )
            db.execute(
                "CREATE INDEX IF NOT EXISTS idx_workflow_templates_public "
                "ON workflow_templates(is_public)"
            )
            TemplateStore._ensured = True

    def save(
        self,
        name: str,
        description: str,
        nodes: List[dict],
        edges: List[dict],
        tags: List[str],
        owner_id: Optional[str],
    ) -> dict:
        self._ensure()
        tid = f"tpl_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        db.execute(
            "INSERT INTO workflow_templates "
            "(id, name, description, nodes, edges, tags, builtin, is_public, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, 0, ?, ?, ?)",
            (
                tid,
                name,
                description or "",
                json.dumps(nodes, ensure_ascii=False),
                json.dumps(edges, ensure_ascii=False),
                json.dumps(tags or [], ensure_ascii=False),
                owner_id,
                now,
                now,
            ),
        )
        return self.get(tid)

    def list_user(self, owner_id: str) -> List[dict]:
        self._ensure()
        rows = db.query(
            "SELECT * FROM workflow_templates WHERE builtin = 0 AND owner_id = ? "
            "ORDER BY updated_at DESC",
            (owner_id,),
        )
        return [self._row_to_dict(r) for r in rows]

    def set_public(self, template_id: str, owner_id: str, public: bool) -> dict:
        """切换模板公开状态（V8.0 模板市场）。仅 owner 可操作。"""
        self._ensure()
        row = db.query_one(
            "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
        )
        if not row:
            raise TemplateNotFoundError(template_id)
        if row["builtin"]:
            raise TemplatePermissionError("内置模板不可发布")
        if row["owner_id"] != owner_id:
            raise TemplatePermissionError("无权操作该模板")
        db.execute(
            "UPDATE workflow_templates SET is_public = ?, updated_at = ? WHERE id = ?",
            (1 if public else 0, _utc_now(), template_id),
        )
        return self.get(template_id)

    def list_public(self, exclude_owner_id: Optional[str] = None) -> List[dict]:
        """公共模板市场：内置 + 用户公开模板（V8.0）。"""
        self._ensure()
        if exclude_owner_id:
            rows = db.query(
                "SELECT * FROM workflow_templates "
                "WHERE is_public = 1 AND builtin = 0 AND owner_id != ? "
                "ORDER BY updated_at DESC",
                (exclude_owner_id,),
            )
        else:
            rows = db.query(
                "SELECT * FROM workflow_templates WHERE is_public = 1 AND builtin = 0 "
                "ORDER BY updated_at DESC"
            )
        return [self._row_to_dict(r) for r in rows]

    def get(self, template_id: str) -> Optional[dict]:
        self._ensure()
        row = db.query_one(
            "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
        )
        return self._row_to_dict(row) if row else None

    def delete(self, template_id: str, owner_id: str) -> None:
        self._ensure()
        row = db.query_one(
            "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
        )
        if not row:
            raise TemplateNotFoundError(template_id)
        if row["builtin"]:
            raise TemplatePermissionError("内置模板不可删除")
        if row["owner_id"] != owner_id:
            raise TemplatePermissionError("无权删除该模板")
        db.execute("DELETE FROM workflow_templates WHERE id = ?", (template_id,))

    @staticmethod
    def _row_to_dict(row: Dict[str, Any]) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "description": row.get("description", ""),
            "nodes": json.loads(row["nodes"]) if row["nodes"] else [],
            "edges": json.loads(row["edges"]) if row["edges"] else [],
            "tags": json.loads(row["tags"]) if row["tags"] else [],
            "builtin": bool(row["builtin"]),
            "is_public": bool(row.get("is_public", 0)),
            "owner_id": row["owner_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


TEMPLATE_STORE = TemplateStore()
