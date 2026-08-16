"""定时报告自动投递（V102）。

把绩效 / 风险 / 周期 / 综合报告按 cron/interval 定时生成，并推送至已配置的
通知渠道（飞书 / 邮件 / Webhook）。复用现有报告纯函数与 notification_service。

- ``deliver_report(report_type, params)``：一次性生成并推送一份报告；
- ``DeliveryService``：管理投递任务（report_delivery_jobs 表），按 interval
  自动生成并推送；
- 与 workflow 调度器相互独立（后者只跑工作流 DAG）。
"""

from __future__ import annotations

import datetime as dt
import json
import logging
import uuid
from typing import Any, Callable, Dict, List, Optional, Tuple

from ..core.db import db
from ..notifications.base import NotificationMessage
from ..notifications.service import notification_service
from .analytics import build_performance_report, periodic_report, risk_dashboard

logger = logging.getLogger("quantflow.reports.delivery")

VALID_TYPES = ("performance", "risk", "periodic", "consolidate")

_TYPE_LABEL = {
    "performance": "综合绩效",
    "risk": "风险看板",
    "periodic": "周期报告",
    "consolidate": "综合报告",
}

# report_type -> 报告生成函数（consolidate 延迟导入，避免循环依赖）
_BUILDERS: Dict[str, Callable] = {
    "performance": build_performance_report,
    "risk": risk_dashboard,
    "periodic": periodic_report,
}


def _builder(report_type: str) -> Callable:
    if report_type == "consolidate":
        from .consolidate import consolidate_report

        return consolidate_report
    fn = _BUILDERS.get(report_type)
    if fn is None:
        raise ValueError(f"不支持的报告类型 {report_type!r}，可选: {VALID_TYPES}")
    return fn


def _flatten(obj: Any, prefix: str = "", max_depth: int = 2) -> Dict[str, Any]:
    """展平报告结果为标量键值（最多两层嵌套），便于通知文本展示。"""
    out: Dict[str, Any] = {}
    if isinstance(obj, dict) and max_depth > 0:
        for k, v in obj.items():
            nk = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, dict):
                out.update(_flatten(v, nk, max_depth - 1))
            elif isinstance(v, (int, float, str, bool)) and not isinstance(v, bool):
                out[nk] = v
            elif isinstance(v, (list, tuple)) and v and all(isinstance(x, (int, float)) for x in v[:3]):
                out[nk] = f"[{len(v)} 项]"
    return out


def _format_metric(k: str, v: Any) -> str:
    if isinstance(v, float):
        if abs(v) < 1:
            return f"{k}: {v:.4f}"
        return f"{k}: {v:,.4f}"
    return f"{k}: {v}"


def deliver_report(report_type: str, params: Dict[str, Any]) -> Dict[str, Any]:
    """生成一份报告并经通知渠道推送，返回投递结果。

    params 即对应报告生成函数的入参（如 returns / weights / benchmark 等）。
    """
    if report_type not in VALID_TYPES:
        raise ValueError(f"不支持的报告类型 {report_type!r}，可选: {VALID_TYPES}")
    if not isinstance(params, dict):
        raise ValueError("params 必须为对象")
    builder = _builder(report_type)
    result = builder(**params)

    flat = _flatten(result)
    lines = [_format_metric(k, v) for k, v in list(flat.items())[:24]]
    label = _TYPE_LABEL.get(report_type, report_type)
    title = f"量化报告投递：{label}"
    content = f"已生成「{label}」报告，核心指标如下：\n" + "\n".join(lines)
    message = NotificationMessage(
        title=title,
        content=content,
        level="info",
        fields={"report_type": report_type, "metric_count": len(flat)},
    )
    sent = notification_service.notify(message)
    return {
        "report_type": report_type,
        "sent": sent,
        "title": title,
        "metric_count": len(flat),
        "metrics": dict(list(flat.items())[:12]),
    }


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class DeliveryService:
    """投递任务 CRUD + 定时执行。"""

    def list_jobs(self) -> List[dict]:
        rows = db.query(
            "SELECT * FROM report_delivery_jobs ORDER BY created_at DESC, id"
        )
        return [self._row_to_dict(r) for r in rows]

    def get_job(self, job_id: str) -> Optional[dict]:
        r = db.query_one("SELECT * FROM report_delivery_jobs WHERE id = ?", (job_id,))
        return self._row_to_dict(r) if r else None

    def create_job(
        self,
        name: str,
        report_type: str,
        params: Dict[str, Any],
        interval_minutes: int = 60,
        enabled: bool = True,
    ) -> dict:
        if report_type not in VALID_TYPES:
            raise ValueError(f"不支持的报告类型 {report_type!r}，可选: {VALID_TYPES}")
        if not isinstance(params, dict):
            raise ValueError("params 必须为对象")
        job_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        db.execute(
            "INSERT INTO report_delivery_jobs "
            "(id, name, report_type, params, interval_minutes, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                job_id,
                name,
                report_type,
                json.dumps(params, ensure_ascii=False),
                int(interval_minutes),
                1 if enabled else 0,
                now,
            ),
        )
        return self.get_job(job_id)

    def delete_job(self, job_id: str) -> bool:
        cur = db.execute("DELETE FROM report_delivery_jobs WHERE id = ?", (job_id,))
        return (cur.rowcount or 0) > 0

    def set_enabled(self, job_id: str, enabled: bool) -> bool:
        cur = db.execute(
            "UPDATE report_delivery_jobs SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, job_id),
        )
        return (cur.rowcount or 0) > 0

    def run_job(self, job_id: str) -> Dict[str, Any]:
        job = self.get_job(job_id)
        if job is None:
            raise ValueError("投递任务不存在")
        status = "failed"
        detail: Dict[str, Any] = {}
        try:
            detail = deliver_report(job["report_type"], job["params"])
            status = "delivered" if detail.get("sent", 0) > 0 else "no_channel"
        except Exception as exc:  # 生成/推送失败记录，不抛出
            logger.warning("投递任务 %s 执行失败: %s", job_id, exc)
            detail = {"error": str(exc)}
        now = _now_iso()
        db.execute(
            "UPDATE report_delivery_jobs SET last_run_at = ?, last_run_status = ? WHERE id = ?",
            (now, status, job_id),
        )
        return {"job_id": job_id, "status": status, **detail}

    def run_all(self) -> List[Dict[str, Any]]:
        results = []
        for job in self.list_jobs():
            if not job["enabled"]:
                continue
            results.append(self.run_job(job["id"]))
        return results

    @staticmethod
    def _row_to_dict(row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "report_type": row["report_type"],
            "params": json.loads(row["params"]),
            "interval_minutes": row["interval_minutes"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "last_run_at": row.get("last_run_at"),
            "last_run_status": row.get("last_run_status"),
        }


delivery_service = DeliveryService()
