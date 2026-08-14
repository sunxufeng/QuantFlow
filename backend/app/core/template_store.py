"""个人工作流模板持久化（V3.1 模板市场）。

在 SQLite 业务库上承载用户保存的可复用工作流模板，跨服务重启保留。
内置模板（BUILTIN_TEMPLATES）仍由 ``app.templates`` 提供，本存储只管用户模板。
"""

from __future__ import annotations

import json
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

    def save(
        self,
        name: str,
        description: str,
        nodes: List[dict],
        edges: List[dict],
        tags: List[str],
        owner_id: Optional[str],
    ) -> dict:
        tid = f"tpl_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        db.execute(
            "INSERT INTO workflow_templates "
            "(id, name, description, nodes, edges, tags, builtin, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)",
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
        rows = db.query(
            "SELECT * FROM workflow_templates WHERE builtin = 0 AND owner_id = ? "
            "ORDER BY updated_at DESC",
            (owner_id,),
        )
        return [self._row_to_dict(r) for r in rows]

    def get(self, template_id: str) -> Optional[dict]:
        row = db.query_one(
            "SELECT * FROM workflow_templates WHERE id = ?", (template_id,)
        )
        return self._row_to_dict(row) if row else None

    def delete(self, template_id: str, owner_id: str) -> None:
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
            "owner_id": row["owner_id"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


TEMPLATE_STORE = TemplateStore()
