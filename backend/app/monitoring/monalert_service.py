"""监控告警服务（V101）。

把 V87-V91 五大组合监控器（drift / 收益质量 / 跟踪误差 / 行业敞口 / 风险预算）
的 breach 结果接入通知管道（notification_service），实现「监控命中即推送」。

设计（对齐 alerts 模块的预警规则引擎）：
- 规则持久化于 ``monitor_alert_rules`` 表（monitor_type + params JSON + 冷却）；
- ``evaluate_all`` 遍历启用规则，调用对应监控纯函数，命中 breach 则经
  ``notification_service.notify`` 广播到所有启用渠道，并按 cooldown 去重；
- 单规则异常不影响其他规则；
- 纯离线，无需任何券商凭证（监控器本身为纯函数）。
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
from .alerts import (
    drift_monitor,
    return_quality_monitor,
    risk_budget_monitor,
    sector_exposure_monitor,
    tracking_error_monitor,
)

logger = logging.getLogger("quantflow.monalert")

VALID_TYPES = ("drift", "return_quality", "tracking_error", "sector_exposure", "risk_budget")

# monitor_type -> 监控纯函数
_MONITORS: Dict[str, Callable] = {
    "drift": drift_monitor,
    "return_quality": return_quality_monitor,
    "tracking_error": tracking_error_monitor,
    "sector_exposure": sector_exposure_monitor,
    "risk_budget": risk_budget_monitor,
}

_TYPE_LABEL = {
    "drift": "持仓偏离",
    "return_quality": "收益质量",
    "tracking_error": "跟踪误差",
    "sector_exposure": "行业敞口",
    "risk_budget": "风险预算",
}


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return dt.date.today().isoformat()


def _extract_breach(monitor_type: str, result: Dict[str, Any]) -> Tuple[bool, str]:
    """从监控结果中抽取是否命中以及人类可读的命中摘要。"""
    if monitor_type == "drift":
        n = result.get("n_flagged") or 0
        if n <= 0:
            return False, ""
        flagged = result.get("flagged") or []
        max_drift = result.get("max_drift") or 0.0
        return True, f"偏离标的 {n} 个（{', '.join(map(str, flagged[:8]))}），最大偏离 {max_drift:.2%}"
    breaches = result.get("breaches") or []
    if not breaches:
        return False, ""
    if isinstance(breaches[0], str):
        return True, "；".join(breaches[:6])
    # 结构化 breach（dict 列表）：取前几条关键信息
    parts = []
    for b in breaches[:6]:
        if isinstance(b, dict):
            parts.append("，".join(f"{k}={v}" for k, v in b.items()))
        else:
            parts.append(str(b))
    return True, "；".join(parts)


class MonitorAlertService:
    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def list_rules(self) -> List[dict]:
        rows = db.query(
            "SELECT * FROM monitor_alert_rules ORDER BY created_at DESC, id"
        )
        return [self._row_to_dict(r) for r in rows]

    def get_rule(self, rule_id: str) -> Optional[dict]:
        r = db.query_one("SELECT * FROM monitor_alert_rules WHERE id = ?", (rule_id,))
        return self._row_to_dict(r) if r else None

    def create_rule(
        self,
        name: str,
        monitor_type: str,
        params: Dict[str, Any],
        cooldown_minutes: int = 60,
        enabled: bool = True,
    ) -> dict:
        if monitor_type not in VALID_TYPES:
            raise ValueError(f"不支持的监控类型 {monitor_type!r}，可选: {VALID_TYPES}")
        if not isinstance(params, dict):
            raise ValueError("params 必须为对象")
        # 入参合法性在评估时由纯函数校验；此处做一次轻量结构校验
        rule_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        db.execute(
            "INSERT INTO monitor_alert_rules "
            "(id, name, monitor_type, params, cooldown_minutes, enabled, created_at, trigger_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 0)",
            (
                rule_id,
                name,
                monitor_type,
                json.dumps(params, ensure_ascii=False),
                int(cooldown_minutes),
                1 if enabled else 0,
                now,
            ),
        )
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> bool:
        cur = db.execute("DELETE FROM monitor_alert_rules WHERE id = ?", (rule_id,))
        return (cur.rowcount or 0) > 0

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        cur = db.execute(
            "UPDATE monitor_alert_rules SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, rule_id),
        )
        return (cur.rowcount or 0) > 0

    # ------------------------------------------------------------------ #
    # 评估
    # ------------------------------------------------------------------ #
    def evaluate_all(self) -> List[Dict[str, Any]]:
        rules = [r for r in self.list_rules() if r["enabled"]]
        return [self._evaluate_rule(r) for r in rules]

    def _evaluate_rule(self, rule: dict) -> Dict[str, Any]:
        rule_id = rule["id"]
        monitor_type = rule["monitor_type"]
        result: Dict[str, Any] = {
            "id": rule_id,
            "name": rule["name"],
            "monitor_type": monitor_type,
            "triggered": False,
            "notified": False,
            "breaches": None,
            "error": None,
        }
        try:
            func = _MONITORS.get(monitor_type)
            if func is None:
                result["error"] = f"未知监控类型 {monitor_type}"
                return result
            params = rule.get("params") or {}
            raw = func(**params)
            triggered, summary = _extract_breach(monitor_type, raw)
            result["breaches"] = raw.get("breaches")
            result["triggered"] = triggered
            if triggered:
                if self._in_cooldown(rule):
                    result["notified"] = False
                    return result
                self._notify(rule, monitor_type, summary)
                db.execute(
                    "UPDATE monitor_alert_rules SET last_triggered = ?, trigger_count = trigger_count + 1 WHERE id = ?",
                    (_now_iso(), rule_id),
                )
                result["notified"] = True
        except Exception as exc:  # 单规则失败不影响其他
            logger.warning("监控告警规则 %s 评估失败: %s", rule_id, exc)
            result["error"] = str(exc)
        return result

    def _in_cooldown(self, rule: dict) -> bool:
        last = rule.get("last_triggered")
        if not last:
            return False
        try:
            last_dt = dt.datetime.strptime(last, "%Y-%m-%dT%H:%M:%SZ").replace(
                tzinfo=dt.timezone.utc
            )
        except Exception:
            return False
        cooldown = dt.timedelta(minutes=rule.get("cooldown_minutes") or 0)
        return dt.datetime.now(dt.timezone.utc) - last_dt < cooldown

    def _notify(self, rule: dict, monitor_type: str, summary: str) -> None:
        label = _TYPE_LABEL.get(monitor_type, monitor_type)
        title = f"监控告警：{rule['name']}"
        content = f"组合监控「{label}」触发告警。\n{summary}"
        message = NotificationMessage(
            title=title,
            content=content,
            level="warning",
            fields={
                "monitor_type": monitor_type,
                "rule": rule["name"],
                "summary": summary,
            },
        )
        try:
            notification_service.notify(message)
        except Exception as exc:  # 通知失败记录但不影响评估流程
            logger.warning("监控告警 %s 通知发送失败: %s", rule["id"], exc)

    @staticmethod
    def _row_to_dict(row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "monitor_type": row["monitor_type"],
            "params": json.loads(row["params"]),
            "cooldown_minutes": row["cooldown_minutes"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "last_triggered": row.get("last_triggered"),
            "trigger_count": row.get("trigger_count") or 0,
        }


monitor_alert_service = MonitorAlertService()
