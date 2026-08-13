"""共享运行态存储（V1.1 N6）。

:class:`DatabaseRunRepository` 与 :mod:`app.core.runs` 中原有的内存
:class:`RunRepository` 接口完全一致，但数据落在项目既有 SQLite（同机多进程共享），
因此 API 进程与 ``quantflow-worker`` 进程看到的是同一份运行实例/节点状态。

定位：补齐 V1.0 注释中「运行实例仍为内存态，迁移 SQLite 排入 V1.1」的遗留项，
同时为分布式 Worker 提供跨进程可见的运行态。
"""

from __future__ import annotations

import json
from typing import Any, List, Optional

from .db import db


class RunNotFoundError(KeyError):
    pass


def _to_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False) if value is not None else None  # type: ignore


def _from_json(text: Optional[str]) -> Any:
    return json.loads(text) if text else None


class DatabaseRunRepository:
    """运行实例存储（SQLite 实现，跨进程共享）。"""

    def __init__(self, database=None) -> None:
        self._db = database or db

    def create(self, record: dict) -> dict:
        self._db.execute(
            "INSERT INTO runs (run_id, workflow_id, workflow_name, status, created_at, "
            "started_at, finished_at, result, nodes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record["run_id"],
                record.get("workflow_id"),
                record.get("workflow_name", ""),
                record["status"],
                record.get("created_at", ""),
                record.get("started_at", 0.0),
                record.get("finished_at"),
                _to_json(record.get("result")),
                _to_json(record.get("nodes", {})),
            ),
        )
        return dict(record)

    def get(self, run_id: str) -> dict:
        row = self._db.query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,))
        if row is None:
            raise RunNotFoundError(run_id)
        return self._row_to_record(row)

    def update(self, run_id: str, **fields: Any) -> dict:
        if not fields:
            return self.get(run_id)
        allowed = {"status", "finished_at", "result", "started_at", "workflow_name"}
        set_clauses = []
        params: List[Any] = []
        for key, value in fields.items():
            if key not in allowed:
                continue
            set_clauses.append(f"{key} = ?")
            if key in ("result",):
                params.append(_to_json(value))
            else:
                params.append(value)
        if not set_clauses:
            return self.get(run_id)
        params.append(run_id)
        self._db.execute(
            f"UPDATE runs SET {', '.join(set_clauses)} WHERE run_id = ?", params
        )
        return self.get(run_id)

    def patch_node(self, run_id: str, node_id: str, state: dict) -> dict:
        row = self._db.query_one(
            "SELECT nodes FROM runs WHERE run_id = ?", (run_id,)
        )
        if row is None:
            raise RunNotFoundError(run_id)
        nodes = _from_json(row["nodes"]) or {}
        nodes[node_id] = state
        self._db.execute(
            "UPDATE runs SET nodes = ? WHERE run_id = ?",
            (_to_json(nodes), run_id),
        )
        return self._row_to_record(self._db.query_one("SELECT * FROM runs WHERE run_id = ?", (run_id,)))

    def list(self, workflow_id: Optional[str] = None, limit: int = 50) -> List[dict]:
        rows = self._db.query(
            "SELECT * FROM runs ORDER BY started_at DESC"
        )
        items = [self._summary(self._row_to_record(r)) for r in rows]
        if workflow_id:
            items = [r for r in items if r.get("workflow_id") == workflow_id]
        return items[:limit]

    def delete(self, run_id: str) -> None:
        self._db.execute("DELETE FROM runs WHERE run_id = ?", (run_id,))
        self._db.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))
        self._db.execute("DELETE FROM run_jobs WHERE id = ?", (run_id,))

    def clear(self) -> None:
        self._db.execute("DELETE FROM runs")
        self._db.execute("DELETE FROM run_events")
        self._db.execute("DELETE FROM run_jobs")

    def stats(self) -> dict:
        rows = self._db.query(
            "SELECT status, COUNT(*) AS n FROM runs GROUP BY status"
        )
        counts = {"total": 0}
        for r in rows:
            counts[r["status"]] = int(r["n"])
            counts["total"] += int(r["n"])
        return counts

    # ------------------------------------------------------------------ #
    @staticmethod
    def _row_to_record(row: dict) -> dict:
        return {
            "run_id": row["run_id"],
            "workflow_id": row["workflow_id"],
            "workflow_name": row.get("workflow_name", ""),
            "status": row["status"],
            "created_at": row.get("created_at"),
            "started_at": row.get("started_at", 0.0),
            "finished_at": row.get("finished_at"),
            "result": _from_json(row.get("result")),
            "nodes": _from_json(row.get("nodes")) or {},
        }

    @staticmethod
    def _summary(record: dict) -> dict:
        return {
            "run_id": record["run_id"],
            "workflow_id": record.get("workflow_id"),
            "workflow_name": record.get("workflow_name", ""),
            "status": record["status"],
            "created_at": record.get("created_at"),
            "started_at": record.get("started_at"),
            "finished_at": record.get("finished_at"),
        }


# 全局默认存储（与 db 单例共享同一 SQLite 文件，跨进程可见）
RUN_REPOSITORY = DatabaseRunRepository()
