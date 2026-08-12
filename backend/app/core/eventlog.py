"""运行事件日志（V1.1 N6）。

把运行生命周期事件（开始 / 节点状态变更 / 结束）持久化到共享 SQLite，
供 WebSocket 跨进程读取（生产者与 worker 可能不在同一进程）。

与原进程内 :class:`~app.core.events.EventBus` 互补：bus 适合单进程实时回调，
事件日志适合跨进程、可回放的场景。WS 端点改为轮询本日志，
从而天然支持「API 与 worker 分进程」部署。
"""

from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional

from .db import db


class RunEventLog:
    def __init__(self, database=None) -> None:
        self._db = database or db

    def append(
        self,
        run_id: str,
        kind: str,
        node_id: Optional[str] = None,
        payload: Optional[Dict[str, Any]] = None,
        timestamp: Optional[float] = None,
    ) -> int:
        """追加一条事件，返回自增 seq。"""
        cur = self._db.execute(
            "INSERT INTO run_events (run_id, kind, node_id, payload, timestamp) "
            "VALUES (?, ?, ?, ?, ?)",
            (
                run_id,
                kind,
                node_id,
                json.dumps(payload or {}, ensure_ascii=False),
                timestamp if timestamp is not None else time.time(),
            ),
        )
        return cur.lastrowid

    def read_since(self, run_id: str, after_seq: int = 0) -> List[Dict[str, Any]]:
        """读取某运行 ``seq > after_seq`` 的事件，按 seq 升序（保证顺序回放）。"""
        rows = self._db.query(
            "SELECT seq, run_id, kind, node_id, payload, timestamp FROM run_events "
            "WHERE run_id = ? AND seq > ? ORDER BY seq ASC",
            (run_id, after_seq),
        )
        return [
            {
                "seq": r["seq"],
                "run_id": r["run_id"],
                "kind": r["kind"],
                "node_id": r["node_id"],
                "payload": json.loads(r["payload"]),
                "timestamp": r["timestamp"],
            }
            for r in rows
        ]

    def latest_seq(self, run_id: str) -> int:
        row = self._db.query_one(
            "SELECT MAX(seq) AS m FROM run_events WHERE run_id = ?", (run_id,)
        )
        return int(row["m"]) if row and row["m"] is not None else 0

    def purge(self, run_id: str) -> None:
        self._db.execute("DELETE FROM run_events WHERE run_id = ?", (run_id,))


# 全局默认事件日志（跨进程共享）
RUN_EVENT_LOG = RunEventLog()
