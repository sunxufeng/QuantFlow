"""报告投递自动调度（V102，独立于工作流/预警/监控调度器）。

按固定间隔（默认 60 分钟，受环境变量 QF_REPORT_DELIVERY_INTERVAL_MINUTES 控制）
调用 ``delivery_service.run_all()``：遍历启用任务，生成报告并推送至已配置渠道。
纯离线，无需券商凭证。

可用 QF_DISABLE_REPORT_DELIVERY_SCHEDULER=1 关闭。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("quantflow.reports.delivery.scheduler")

_JOB_ID = "report_delivery_auto"
_scheduler: BackgroundScheduler | None = None
_last_run_at: float | None = None
_last_run_count: int = 0


def _interval_minutes() -> int:
    try:
        minutes = int(os.getenv("QF_REPORT_DELIVERY_INTERVAL_MINUTES", "60"))
    except (TypeError, ValueError):
        minutes = 60
    return max(1, minutes)


def _run() -> List[Dict[str, Any]]:
    global _last_run_at, _last_run_count
    results: List[Dict[str, Any]] = []
    try:
        from . import delivery

        results = delivery.delivery_service.run_all()
        _last_run_count = len(results)
        if results:
            delivered = sum(1 for r in results if r.get("status") == "delivered")
            logger.info("报告投递自动执行 %d 个任务（已投递 %d 个）", len(results), delivered)
        else:
            logger.debug("报告投递自动执行：无启用任务")
    except Exception as exc:  # pragma: no cover - 调度容错
        logger.exception("报告投递自动执行异常：%s", exc)
    finally:
        _last_run_at = time.time()
    return results


def trigger_now() -> Dict[str, Any]:
    results = _run()
    delivered = sum(1 for r in results if r.get("status") == "delivered")
    return {
        "executed": len(results),
        "delivered": delivered,
        "results": results,
        "last_run_at": _last_run_at,
    }


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if os.getenv("QF_DISABLE_REPORT_DELIVERY_SCHEDULER") == "1":
        logger.info("报告投递自动调度已禁用（QF_DISABLE_REPORT_DELIVERY_SCHEDULER=1）")
        return
    minutes = _interval_minutes()
    try:
        _scheduler = BackgroundScheduler()
        _scheduler.add_job(
            _run,
            IntervalTrigger(minutes=minutes),
            id=_JOB_ID,
            replace_existing=True,
            max_instances=1,
            coalesce=True,
        )
        _scheduler.start()
        logger.info("报告投递自动调度已启动（间隔 %d 分钟）", minutes)
    except Exception as exc:  # pragma: no cover - 启动容错
        logger.warning("报告投递自动调度启动失败：%s", exc)
        _scheduler = None


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover
            pass
        _scheduler = None
        logger.info("报告投递自动调度已停止")


def is_running() -> bool:
    return _scheduler is not None and _scheduler.running


def status() -> dict:
    running = is_running()
    interval = _interval_minutes()
    next_run_at = None
    if running and _last_run_at is not None:
        next_run_at = _last_run_at + interval * 60
    return {
        "running": running,
        "interval_minutes": interval,
        "disabled": os.getenv("QF_DISABLE_REPORT_DELIVERY_SCHEDULER") == "1",
        "last_run_at": _last_run_at,
        "next_run_at": next_run_at,
        "last_executed": _last_run_count,
    }
