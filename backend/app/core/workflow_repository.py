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


class InMemoryWorkflowRepository:
    """Thread-safe repository that can later be replaced by MongoDB."""

    def __init__(self) -> None:
        self._items: Dict[str, Dict[str, Any]] = {}
        self._lock = threading.RLock()

    def list(self) -> List[dict]:
        with self._lock:
            items = sorted(self._items.values(), key=lambda item: item["updated_at"], reverse=True)
            return [deepcopy(item) for item in items]

    def get(self, workflow_id: str) -> dict:
        with self._lock:
            try:
                return deepcopy(self._items[workflow_id])
            except KeyError:
                raise WorkflowNotFoundError(workflow_id) from None

    def create(self, payload: dict) -> dict:
        now = _utc_now()
        item = {
            "id": f"wf_{uuid.uuid4().hex[:12]}",
            "name": payload["name"],
            "description": payload.get("description", ""),
            "nodes": deepcopy(payload["nodes"]),
            "edges": deepcopy(payload.get("edges", [])),
            "version": 1,
            "created_at": now,
            "updated_at": now,
        }
        with self._lock:
            self._items[item["id"]] = item
        return deepcopy(item)

    def update(self, workflow_id: str, payload: dict) -> dict:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            current = self._items[workflow_id]
            current.update(
                name=payload["name"],
                description=payload.get("description", ""),
                nodes=deepcopy(payload["nodes"]),
                edges=deepcopy(payload.get("edges", [])),
                version=current["version"] + 1,
                updated_at=_utc_now(),
            )
            return deepcopy(current)

    def delete(self, workflow_id: str) -> None:
        with self._lock:
            if workflow_id not in self._items:
                raise WorkflowNotFoundError(workflow_id)
            del self._items[workflow_id]

    def clear(self) -> None:
        with self._lock:
            self._items.clear()


WORKFLOW_REPOSITORY = InMemoryWorkflowRepository()
