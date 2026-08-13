"""Workflow persistence boundary with an in-memory M1 implementation."""

from __future__ import annotations

import threading
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Dict, List


class WorkflowNotFoundError(KeyError):
    pass


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class VersionNotFoundError(KeyError):
    pass


class InMemoryWorkflowRepository:
    """Thread-safe repository that can later be replaced by MongoDB."""

    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}
        self._snapshots: Dict[str, List[Dict[str, Any]]] = {}
        self._snapshot_seq: Dict[str, int] = {}
        self._lock = threading.RLock()

    def list(self, project_id: str | None = None, owner_id: str | None = None) -> List[dict]:
        with self._lock:
            items = [
                deepcopy(item)
                for item in self._items.values()
                if (project_id is None or item.get("project_id") == project_id)
                and (owner_id is None or item.get("owner_id") == owner_id)
            ]
            items.sort(key=lambda item: item["updated_at"], reverse=True)
            return items

    def get(self, workflow_id: str) -> dict:
        with self._lock:
            try:
                return deepcopy(self._items[workflow_id])
            except KeyError:
                raise WorkflowNotFoundError(workflow_id) from None

    def create(self, payload: dict, owner_id: str | None = None) -> dict:
        now = _utc_now()
        item = {
            "id": f"wf_{uuid.uuid4().hex[:12]}",
            "name": payload["name"],
            "description": payload.get("description", ""),
            "nodes": deepcopy(payload["nodes"]),
            "edges": deepcopy(payload.get("edges", [])),
            "project_id": payload.get("project_id"),
            "owner_id": owner_id,
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._items[item["id"]] = item
        return deepcopy(item)

    def update(self, workflow_id: str, payload: dict, owner_id: str | None = None) -> dict:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            current = self._items[workflow_id]
            current.update(
                name=payload["name"],
                description=payload.get("description", ""),
                nodes=deepcopy(payload["nodes"]),
                edges=deepcopy(payload.get("edges", [])),
                project_id=payload.get("project_id", current.get("project_id")),
                owner_id=owner_id if owner_id is not None else current.get("owner_id"),
                version=current["version"] + 1,
                updated_at=_utc_now(),
            )
            return deepcopy(current)

    # ---- 版本快照（V1.5 工作流版本管理）----
    def snapshot(self, workflow_id: str, label: str | None = None) -> dict:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            current = self._items[workflow_id]
            seq = self._snapshot_seq.get(workflow_id, 0) + 1
            self._snapshot_seq[workflow_id] = seq
            snap = {
                "id": f"snap_{uuid.uuid4().hex[:10]}",
                "version": seq,
                "label": label or f"v{seq}",
                "saved_at": _utc_now(),
                "workflow_id": workflow_id,
                "workflow_version": current["version"],
                "name": current["name"],
                "description": current.get("description", ""),
                "nodes": deepcopy(current["nodes"]),
                "edges": deepcopy(current.get("edges", [])),
            }
            self._snapshots.setdefault(workflow_id, []).append(snap)
            return {
                "id": snap["id"],
                "version": snap["version"],
                "label": snap["label"],
                "saved_at": snap["saved_at"],
                "workflow_version": snap["workflow_version"],
                "name": snap["name"],
                "description": snap["description"],
                "node_count": len(snap["nodes"]),
                "edge_count": len(snap["edges"]),
            }

    def list_versions(self, workflow_id: str) -> List[dict]:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            snaps = self._snapshots.get(workflow_id, [])
            out = [
                {
                    "id": s["id"],
                    "version": s["version"],
                    "label": s["label"],
                    "saved_at": s["saved_at"],
                    "workflow_version": s["workflow_version"],
                    "name": s["name"],
                    "node_count": len(s["nodes"]),
                    "edge_count": len(s["edges"]),
                }
                for s in snaps
            ]
            out.sort(key=lambda x: x["version"], reverse=True)
            return out

    def restore(self, workflow_id: str, version: int) -> dict:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            match = next(
                (s for s in self._snapshots.get(workflow_id, []) if s["version"] == version),
                None,
            )
            if match is None:
                raise VersionNotFoundError(str(version)) from None
            current = self._items[workflow_id]
            current.update(
                name=match["name"],
                description=match["description"],
                nodes=deepcopy(match["nodes"]),
                edges=deepcopy(match["edges"]),
                version=current["version"] + 1,
                updated_at=_utc_now(),
            )
            return deepcopy(current)

    def delete(self, workflow_id: str) -> None:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            del self._items[workflow_id]
            self._snapshots.pop(workflow_id, None)
            self._snapshot_seq.pop(workflow_id, None)

    def clear(self) -> None:
        with self._lock:
            self._items.clear()
            self._snapshots.clear()
            self._snapshot_seq.clear()


WORKFLOW_REPOSITORY = InMemoryWorkflowRepository()
