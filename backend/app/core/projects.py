"""项目仓库（SQLite，M4-2）。

- 项目由 owner 创建，创建者自动成为 owner 角色成员；
- 成员角色：owner / admin / member / viewer（权限判定见 api/projects.py）；
- 项目删除级联清理成员（SQLite FK ON DELETE CASCADE）。
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import List, Optional

from .db import db


class ProjectNotFoundError(KeyError):
    pass


class ProjectMemberNotFoundError(KeyError):
    pass


class UserAlreadyMemberError(ValueError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ProjectRepository:
    def create(self, owner_id: str, name: str, description: str = "") -> dict:
        now = _utc_now()
        project_id = f"p_{uuid.uuid4().hex[:12]}"
        db.execute(
            "INSERT INTO projects (id, name, description, owner_id, created_at, updated_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (project_id, name, description, owner_id, now, now),
        )
        db.execute(
            "INSERT INTO project_members (project_id, user_id, role, created_at) "
            "VALUES (?, ?, ?, ?)",
            (project_id, owner_id, "owner", now),
        )
        return self.get(project_id)

    def get(self, project_id: str) -> Optional[dict]:
        row = db.query_one(
            "SELECT p.*, (SELECT COUNT(*) FROM project_members m WHERE m.project_id = p.id) AS member_count "
            "FROM projects p WHERE p.id = ?",
            (project_id,),
        )
        return row

    def get_or_404(self, project_id: str) -> dict:
        project = self.get(project_id)
        if project is None:
            raise ProjectNotFoundError(project_id)
        return project

    def list_for_user(self, user_id: str) -> List[dict]:
        """用户拥有或参与的项目。"""
        return db.query(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM project_members m WHERE m.project_id = p.id) AS member_count "
            "FROM projects p "
            "LEFT JOIN project_members pm ON pm.project_id = p.id AND pm.user_id = ? "
            "WHERE p.owner_id = ? OR pm.user_id = ? "
            "ORDER BY p.updated_at DESC",
            (user_id, user_id, user_id),
        )

    def list_all(self) -> List[dict]:
        return db.query(
            "SELECT p.*, "
            "(SELECT COUNT(*) FROM project_members m WHERE m.project_id = p.id) AS member_count "
            "FROM projects p ORDER BY p.created_at"
        )

    def update(self, project_id: str, name: str, description: str) -> dict:
        self.get_or_404(project_id)
        db.execute(
            "UPDATE projects SET name = ?, description = ?, updated_at = ? WHERE id = ?",
            (name, description, _utc_now(), project_id),
        )
        return self.get(project_id)

    def delete(self, project_id: str) -> None:
        self.get_or_404(project_id)
        db.execute("DELETE FROM projects WHERE id = ?", (project_id,))

    def member_role(self, project_id: str, user_id: str) -> Optional[str]:
        row = db.query_one(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        return row["role"] if row else None

    def add_member(self, project_id: str, user_id: str, role: str) -> dict:
        self.get_or_404(project_id)
        if self.member_role(project_id, user_id):
            raise UserAlreadyMemberError(user_id)
        db.execute(
            "INSERT INTO project_members (project_id, user_id, role, created_at) VALUES (?, ?, ?, ?)",
            (project_id, user_id, role, _utc_now()),
        )
        return {
            "project_id": project_id,
            "user_id": user_id,
            "role": role,
            "created_at": _utc_now(),
        }

    def remove_member(self, project_id: str, user_id: str) -> None:
        row = db.query_one(
            "SELECT role FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )
        if row is None:
            raise ProjectMemberNotFoundError(user_id)
        if row["role"] == "owner":
            raise ValueError("不能移除项目 owner")
        db.execute(
            "DELETE FROM project_members WHERE project_id = ? AND user_id = ?",
            (project_id, user_id),
        )

    def list_members(self, project_id: str) -> List[dict]:
        self.get_or_404(project_id)
        return db.query(
            "SELECT pm.project_id, pm.user_id, pm.role, pm.created_at, u.username "
            "FROM project_members pm JOIN users u ON u.id = pm.user_id "
            "WHERE pm.project_id = ? ORDER BY pm.created_at",
            (project_id,),
        )

    def count(self) -> int:
        row = db.query_one("SELECT COUNT(*) AS n FROM projects")
        return int(row["n"]) if row else 0


PROJECT_REPOSITORY = ProjectRepository()
