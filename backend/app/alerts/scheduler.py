"""预警自动评估调度（V2.3 补充，独立于工作流调度器）。

按固定间隔（默认 2 分钟，受环境变量 QF_ALERT_EVAL_INTERVAL_MINUTES 控制）
调用 ``alert_service.evaluate_all()``：命中规则则经已接入的通知渠道（站内 /
Webhook / 飞书）推送，并走冷却去重。纯离线，无需任何券商凭证。

可用 QF_DISABLE_ALERT_SCHEDULER=1 关闭。
"""

from __future__ import annotations

import logging
import os
import time
from typing import Any, Dict, List

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

logger = logging.getLogger("quantflow.alerts.scheduler")

_JOB_ID = "alerts_auto_eval"
_scheduler: BackgroundScheduler | None = None
_last_run_at: float | None = None  # epoch 秒，最近一次完成评估的时间
_last_run_triggered: int = 0  # 最近一次评估中已通知的条数


def _interval_minutes() -> int:
    try:
        minutes = int(os.getenv("QF_ALERT_EVAL_INTERVAL_MINUTES", "2"))
    except (TypeError, ValueError):
        minutes = 2
    return max(1, minutes)


def _run() -> List[Dict[str, Any]]:
    """单次评估任务：懒加载 alert_service，异常被吞掉以免拖垮调度器。返回评估结果。"""
    global _last_run_at, _last_run_triggered
    results: List[Dict[str, Any]] = []
    try:
        from .service import alert_service

        results = alert_service.evaluate_all()
        if results:
            fired = [r for r in results if r.get("notified")]
            _last_run_triggered = len(fired)
            if fired:
                logger.info("预警自动评估命中 %d 条（已通知 %d 条）", len(results), len(fired))
            else:
                logger.debug("预警自动评估完成 %d 条，无命中", len(results))
        else:
            _last_run_triggered = 0
            logger.debug("预警自动评估：无启用规则")
    except Exception as exc:  # pragma: no cover - 调度容错
        logger.exception("预警自动评估执行异常：%s", exc)
    finally:
        _last_run_at = time.time()
    return results


def trigger_now() -> Dict[str, Any]:
    """手动立即评估一次（与定时任务同路径），并刷新 last_run 时间戳。"""
    results = _run()
    notified = sum(1 for r in results if r.get("notified"))
    return {
        "evaluated": len(results),
        "notified": notified,
        "results": results,
        "last_run_at": _last_run_at,
    }


def start() -> None:
    global _scheduler
    if _scheduler is not None:
        return
    if os.getenv("QF_DISABLE_ALERT_SCHEDULER") == "1":
        logger.info("预警自动评估调度已禁用（QF_DISABLE_ALERT_SCHEDULER=1）")
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
        logger.info("预警自动评估调度已启动（间隔 %d 分钟）", minutes)
    except Exception as exc:  # pragma: no cover - 启动容错
        logger.warning("预警自动评估调度启动失败：%s", exc)
        _scheduler = None


def shutdown() -> None:
    global _scheduler
    if _scheduler is not None:
        try:
            _scheduler.shutdown(wait=False)
        except Exception:  # pragma: no cover
            pass
        _scheduler = None
        logger.info("预警自动评估调度已停止")


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
        "disabled": os.getenv("QF_DISABLE_ALERT_SCHEDULER") == "1",
        "last_run_at": _last_run_at,
        "next_run_at": next_run_at,
        "last_triggered": _last_run_triggered,
    }
