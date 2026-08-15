"""V6.2 批量导出中心。

统一导出端点，支持将平台内可复用/可回看的数据批量导出为 CSV 或 JSON：
- ``factors``：因子库（factor_library）
- ``templates``：工作流模板库（workflow_templates）
- ``backtests``：回测/工作流运行记录（runs，含 result）

所有接口需登录；数据按当前用户可见范围返回（因子/模板按 owner 隔离，运行记录返回全部）。
"""

from __future__ import annotations

import csv
import io
import json
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..core.db import db

router = APIRouter(prefix="/export", tags=["export"])

# 各资源的列顺序与 JSON 字段（用于 CSV 内联 / JSON 解析）
_RESOURCES: Dict[str, Dict[str, Any]] = {
    "factors": {
        "table": "factor_library",
        "order_by": "created_at ASC",
        "columns": ["id", "name", "category", "expression", "description", "params", "owner_id", "created_at", "updated_at"],
        "json_fields": {"params"},
    },
    "templates": {
        "table": "workflow_templates",
        "order_by": "created_at ASC",
        "columns": ["id", "name", "description", "tags", "builtin", "owner_id", "created_at", "updated_at"],
        "json_fields": {"tags"},
    },
    "backtests": {
        "table": "runs",
        "order_by": "started_at DESC",
        "columns": ["run_id", "workflow_id", "workflow_name", "status", "created_at", "started_at", "finished_at", "result"],
        "json_fields": {"result"},
    },
}


def _query(resource: str, user: dict) -> List[Dict[str, Any]]:
    meta = _RESOURCES[resource]
    table = meta["table"]
    # 因子/模板按 owner 隔离；运行记录返回全部（回测结果属于平台资产）
    if resource in ("factors", "templates"):
        rows = db.query(
            f"SELECT * FROM {table} WHERE owner_id=? ORDER BY {meta['order_by']}", (user["id"],)
        )
    else:
        rows = db.query(f"SELECT * FROM {table} ORDER BY {meta['order_by']}")
    json_fields = meta["json_fields"]
    out = []
    for r in rows:
        item = dict(r)
        for f in json_fields:
            if f in item and isinstance(item[f], str):
                try:
                    item[f] = json.loads(item[f]) if item[f] else None
                except (json.JSONDecodeError, TypeError):
                    pass
        out.append(item)
    return out


def _to_csv(rows: List[Dict[str, Any]], resource: str) -> str:
    meta = _RESOURCES[resource]
    cols = meta["columns"]
    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=cols, extrasaction="ignore")
    writer.writeheader()
    for r in rows:
        row = {}
        for c in cols:
            v = r.get(c)
            if isinstance(v, (dict, list)):
                row[c] = json.dumps(v, ensure_ascii=False)
            else:
                row[c] = "" if v is None else v
        writer.writerow(row)
    return buf.getvalue()


@router.get("")
def export_get(
    resource: str,
    format: str = "json",
    user: dict = Depends(get_current_user),
):
    """批量导出（GET 版本，便于直接下载）。resource=factors|templates|backtests；format=csv|json。"""
    return _do_export(resource, format, user)


class ExportRequest(BaseModel):
    resource: str
    format: str = "json"


@router.post("")
def export_post(payload: ExportRequest, user: dict = Depends(get_current_user)):
    """批量导出（POST 版本，便于前端带体调用）。"""
    return _do_export(payload.resource, payload.format, user)


def _do_export(resource: str, format: str, user: dict):
    if resource not in _RESOURCES:
        raise HTTPException(status_code=400, detail=f"不支持的导出资源：{resource}（可选：{', '.join(_RESOURCES)}）")
    if format not in ("csv", "json"):
        raise HTTPException(status_code=400, detail=f"不支持的导出格式：{format}（可选：csv, json）")
    rows = _query(resource, user)
    if format == "json":
        body = json.dumps({"resource": resource, "count": len(rows), "items": rows}, ensure_ascii=False)
        return Response(
            content=body,
            media_type="application/json",
            headers={"Content-Disposition": f'attachment; filename="quantflow_{resource}.json"'},
        )
    csv_text = _to_csv(rows, resource)
    return Response(
        content="\ufeff" + csv_text,  # BOM 便于 Excel 打开中文
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="quantflow_{resource}.csv"'},
    )
