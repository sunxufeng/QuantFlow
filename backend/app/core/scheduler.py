"""工作流定时调度器（V1.2）。

按 cron / interval 周期自动触发工作流执行（复用 N6 Worker 或 local 后端）。
与 N4 行情同步调度器相互独立：本调度器由 QF_DISABLE_WORKFLOW_SCHEDULER 控制，
默认启用；计划存入 SQLite（schedules 表），进程重启后自动恢复。

设计要点：
- 触发即调用 RunService.submit（worker 后端下仅入队，由 worker 进程消费）；
- 每次触发记录 last_run_at / last_run_status / last_run_id / next_run_at；
- cron 表达式用 APScheduler 解析（标准 5 段）；interval 用 minutes。
"""

from __future__ import annotations

import json
import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from . import runs as run_module
from .db import db

logger = logging.getLogger("quantflow.scheduler")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ScheduleValidationError(ValueError):
    pass


class WorkflowScheduler:
    """工作流定时计划管理 + APScheduler 驱动。"""

    def __init__(self) -> None:
        self._scheduler: Optional[BackgroundScheduler] = None

    # ------------------------------------------------------------------ #
    # 持久化
    # ------------------------------------------------------------------ #
    def create_schedule(
        self,
        name: str,
        trigger_type: str,
        trigger_cfg: str,
        payload: Dict,
        enabled: bool = True,
    ) -> Dict:
        trigger_type = trigger_type.lower()
        if trigger_type not in ("cron", "interval"):
            raise ScheduleValidationError(f"trigger_type 必须是 cron/interval，收到 {trigger_type}")
        self._validate_trigger(trigger_type, trigger_cfg)  # 抛错即非法
        if not isinstance(payload, dict) or not payload.get("nodes"):
            raise ScheduleValidationError("payload 必须包含 nodes（工作流节点列表）")

        sid = f"sch_{uuid.uuid4().hex[:12]}"
        now = _utc_now()
        rec = {
            "id": sid,
            "name": name,
            "trigger_type": trigger_type,
            "trigger_cfg": trigger_cfg,
            "payload": json.dumps(payload, ensure_ascii=False),
            "enabled": 1 if enabled else 0,
            "created_at": now,
            "last_run_at": None,
            "last_run_status": None,
            "last_run_id": None,
            "next_run_at": None,
        }
        db.execute(
            "INSERT INTO schedules "
            "(id, name, trigger_type, trigger_cfg, payload, enabled, created_at, "
            "last_run_at, last_run_status, last_run_id, next_run_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rec["id"], rec["name"], rec["trigger_type"], rec["trigger_cfg"],
                rec["payload"], rec["enabled"], rec["created_at"],
                rec["last_run_at"], rec["last_run_status"], rec["last_run_id"], rec["next_run_at"],
            ),
        )
        return self.get_schedule(sid)

    def list_schedules(self) -> List[Dict]:
        rows = db.query("SELECT * FROM schedules ORDER BY created_at DESC")
        return [self._row_to_dict(r) for r in rows]

    def get_schedule(self, schedule_id: str) -> Optional[Dict]:
        row = db.query_one("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        return self._row_to_dict(row) if row else None

    def remove_schedule(self, schedule_id: str) -> None:
        if self._scheduler is not None:
            try:
                self._scheduler.remove_job(schedule_id)
            except Exception:  # 计划未注册到调度器时不报错
                pass
        db.execute("DELETE FROM schedules WHERE id = ?", (schedule_id,))

    def set_enabled(self, schedule_id: str, enabled: bool) -> Optional[Dict]:
        row = db.query_one("SELECT * FROM schedules WHERE id = ?", (schedule_id,))
        if row is None:
            return None
        db.execute(
            "UPDATE schedules SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, schedule_id),
        )
        if self._scheduler is not None:
            try:
                if enabled:
                    self._add_job(self._row_to_dict(row))
                else:
                    self._scheduler.remove_job(schedule_id)
            except Exception:
                pass
        return self.get_schedule(schedule_id)

    def run_now(self, schedule_id: str) -> Dict:
        """立即触发一次执行（不经过调度器计时）。"""
        rec = self.get_schedule(schedule_id)
        if rec is None:
            raise ScheduleValidationError("计划不存在")
        return self._fire(schedule_id)

    # ------------------------------------------------------------------ #
    # 调度器生命周期
    # ------------------------------------------------------------------ #
    def start(self) -> None:
        if self._scheduler is not None:
            return
        if os.getenv("QF_DISABLE_WORKFLOW_SCHEDULER") == "1":
            logger.info("工作流定时调度已禁用（QF_DISABLE_WORKFLOW_SCHEDULER=1）")
            return
        self._scheduler = BackgroundScheduler()
        for rec in self.list_schedules():
            if rec["enabled"]:
                try:
                    self._add_job(rec)
                except Exception as exc:  # 单条计划异常不影响整体
                    logger.warning("计划 %s 加载失败：%s", rec["id"], exc)
        self._scheduler.start()
        logger.info("工作流定时调度已启动")

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("工作流定时调度已停止")

    # ------------------------------------------------------------------ #
    # 内部
    # ------------------------------------------------------------------ #
    def _add_job(self, rec: Dict) -> None:
        trigger = self._build_trigger(rec["trigger_type"], rec["trigger_cfg"])
        self._scheduler.add_job(
            self._fire,
            trigger=trigger,
            id=rec["id"],
            replace_existing=True,
            args=(rec["id"],),
        )
        job = self._scheduler.get_job(rec["id"])
        if job is not None and job.next_run_time is not None:
            db.execute(
                "UPDATE schedules SET next_run_at = ? WHERE id = ?",
                (job.next_run_time.isoformat(), rec["id"]),
            )

    def _fire(self, schedule_id: str) -> Dict:
        rec = self.get_schedule(schedule_id)
        if rec is None:
            logger.warning("调度触发时计划 %s 已不存在", schedule_id)
            return {}
        payload = json.loads(rec["payload"])
        nodes = payload.get("nodes", [])
        edges = payload.get("edges", [])
        workflow_name = payload.get("workflow_name") or rec["name"]
        status = "failed"
        run_id = None
        try:
            result = run_module.RUN_SERVICE.submit(nodes, edges, workflow_name=workflow_name)
            run_id = result.get("run_id")
            status = "submitted"
        except Exception as exc:  # 提交阶段异常记录失败，不中断调度器
            logger.exception("计划 %s 触发失败：%s", schedule_id, exc)
        now = _utc_now()
        db.execute(
            "UPDATE schedules SET last_run_at = ?, last_run_status = ?, last_run_id = ? WHERE id = ?",
            (now, status, run_id, schedule_id),
        )
        return {"run_id": run_id, "status": status}

    @staticmethod
    def _validate_trigger(trigger_type: str, trigger_cfg: str) -> None:
        try:
            if trigger_type == "cron":
                CronTrigger.from_crontab(trigger_cfg)
            else:  # interval
                cfg = json.loads(trigger_cfg)
                minutes = int(cfg.get("minutes", 0))
                if minutes <= 0:
                    raise ValueError("interval minutes 必须 > 0")
                IntervalTrigger(minutes=minutes)
        except Exception as exc:
            raise ScheduleValidationError(f"trigger 配置非法: {exc}") from exc

    @staticmethod
    def _build_trigger(trigger_type: str, trigger_cfg: str):
        if trigger_type == "cron":
            return CronTrigger.from_crontab(trigger_cfg)
        cfg = json.loads(trigger_cfg)
        return IntervalTrigger(minutes=int(cfg.get("minutes", 1)))

    @staticmethod
    def _row_to_dict(row) -> Dict:
        d = dict(row)
        d["enabled"] = bool(d.get("enabled"))
        return d


# 全局单例（main.py 启动/关闭挂载）
workflow_scheduler = WorkflowScheduler()
