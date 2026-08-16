"""V98 报告存档：保存 / 列出 / 读取用户生成的分析报告快照。

表 ``report_archive``（见 core/db.py schema）。按 owner_id 隔离；content 为报告 JSON 字符串。
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..core.db import db

router = APIRouter()


class ArchiveReq(BaseModel):
    name: str = Field(..., min_length=1, max_length=200)
    type: str = Field(default="consolidate", max_length=50)
    content: Any


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/reports/archive")
def archive_save(req: ArchiveReq, user: dict = Depends(get_current_user)):
    """保存一份报告快照，返回生成的 id。"""
    rid = str(uuid.uuid4())
    db.execute(
        "INSERT INTO report_archive (id, name, type, content, owner_id, created_at) VALUES (?,?,?,?,?,?)",
        (rid, req.name, req.type, json.dumps(req.content, ensure_ascii=False), user["id"], _now()),
    )
    return {"id": rid, "name": req.name, "type": req.type}


@router.get("/reports/archive")
def archive_list(user: dict = Depends(get_current_user)):
    """列出当前用户的报告存档（不含 content，便于列表展示）。"""
    rows = db.query(
        "SELECT id, name, type, owner_id, created_at FROM report_archive WHERE owner_id=? ORDER BY created_at DESC",
        (user["id"],),
    )
    return {"items": [dict(r) for r in rows]}


@router.get("/reports/archive/{rid}")
def archive_get(rid: str, user: dict = Depends(get_current_user)):
    """读取某份报告存档（含 content）；非本人或无记录返回 404。"""
    row = db.query_one(
        "SELECT id, name, type, content, owner_id, created_at FROM report_archive WHERE id=? AND owner_id=?",
        (rid, user["id"]),
    )
    if not row:
        raise HTTPException(status_code=404, detail="报告不存在或无权限")
    item = dict(row)
    try:
        item["content"] = json.loads(item["content"]) if item["content"] else None
    except (json.JSONDecodeError, TypeError):
        pass
    return item


@router.delete("/reports/archive/{rid}")
def archive_delete(rid: str, user: dict = Depends(get_current_user)):
    """删除某份报告存档（仅本人）。"""
    cur = db.execute("DELETE FROM report_archive WHERE id=? AND owner_id=?", (rid, user["id"]))
    if cur.rowcount == 0:
        raise HTTPException(status_code=404, detail="报告不存在或无权限")
    return {"deleted": rid}
