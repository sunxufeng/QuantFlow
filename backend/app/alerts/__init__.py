"""预警规则引擎（V2.3）。

用户定义预警规则（标的 + 指标 + 比较算子 + 阈值），引擎在手动或定时触发时
拉取最新行情，评估条件是否满足，满足则通过已接入的通知渠道（站内/Webhook/飞书）
推送，并做冷却去重避免刷屏。

复用：
- ``core.db`` 持久化规则
- ``notifications.service`` 广播通知
- ``market.service`` 拉取行情
"""

from __future__ import annotations

import datetime as dt
import logging
import uuid
from typing import Any, Dict, List, Optional

from ..core.db import db
from ..market.service import market_service
from ..notifications.base import NotificationMessage
from ..notifications.service import notification_service

logger = logging.getLogger("quantflow.alerts")

VALID_METRICS = ("price", "daily_change_pct")
VALID_OPERATORS = (">", "<", ">=", "<=", "cross_above", "cross_below")


def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _today() -> str:
    return dt.date.today().isoformat()


class AlertService:
    # ------------------------------------------------------------------ #
    # CRUD
    # ------------------------------------------------------------------ #
    def list_rules(self) -> List[dict]:
        rows = db.query(
            "SELECT * FROM alert_rules ORDER BY created_at DESC, id"
        )
        return [self._row_to_dict(r) for r in rows]

    def get_rule(self, rule_id: str) -> Optional[dict]:
        r = db.query_one("SELECT * FROM alert_rules WHERE id = ?", (rule_id,))
        return self._row_to_dict(r) if r else None

    def create_rule(
        self,
        name: str,
        symbol: str,
        metric: str = "price",
        operator: str = ">",
        threshold: float = 0.0,
        cooldown_minutes: int = 60,
        enabled: bool = True,
    ) -> dict:
        if metric not in VALID_METRICS:
            raise ValueError(f"不支持的指标 {metric!r}，可选: {VALID_METRICS}")
        if operator not in VALID_OPERATORS:
            raise ValueError(f"不支持的算子 {operator!r}，可选: {VALID_OPERATORS}")
        rule_id = uuid.uuid4().hex[:12]
        now = _now_iso()
        db.execute(
            "INSERT INTO alert_rules "
            "(id, name, symbol, metric, operator, threshold, cooldown_minutes, enabled, created_at, trigger_count) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0)",
            (
                rule_id,
                name,
                symbol,
                metric,
                operator,
                float(threshold),
                int(cooldown_minutes),
                1 if enabled else 0,
                now,
            ),
        )
        return self.get_rule(rule_id)

    def delete_rule(self, rule_id: str) -> bool:
        cur = db.execute("DELETE FROM alert_rules WHERE id = ?", (rule_id,))
        return (cur.rowcount or 0) > 0

    def set_enabled(self, rule_id: str, enabled: bool) -> bool:
        cur = db.execute(
            "UPDATE alert_rules SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, rule_id),
        )
        return (cur.rowcount or 0) > 0

    # ------------------------------------------------------------------ #
    # 评估
    # ------------------------------------------------------------------ #
    def evaluate_all(self) -> List[Dict[str, Any]]:
        """评估全部启用规则，触发满足条件的通知。返回每条规则的评估结果。"""
        rules = [r for r in self.list_rules() if r["enabled"]]
        return [self._evaluate_rule(r) for r in rules]

    def _evaluate_rule(self, rule: dict) -> Dict[str, Any]:
        rule_id = rule["id"]
        symbol = rule["symbol"]
        result: Dict[str, Any] = {
            "id": rule_id,
            "name": rule["name"],
            "symbol": symbol,
            "metric": rule["metric"],
            "operator": rule["operator"],
            "threshold": rule["threshold"],
            "triggered": False,
            "notified": False,
            "value": None,
            "error": None,
        }
        try:
            value = self._metric_value(symbol, rule["metric"])
            result["value"] = value
            if value is None:
                result["error"] = "无行情数据"
                return result
            if rule["operator"] in ("cross_above", "cross_below"):
                triggered = self._compare_cross(symbol, rule["operator"], rule["threshold"])
            else:
                triggered = self._compare(value, rule["operator"], rule["threshold"])
            result["triggered"] = triggered
            if triggered:
                if self._in_cooldown(rule):
                    result["notified"] = False
                    return result
                self._notify(rule, value)
                now = _now_iso()
                db.execute(
                    "UPDATE alert_rules SET last_triggered = ?, trigger_count = trigger_count + 1 WHERE id = ?",
                    (now, rule_id),
                )
                result["notified"] = True
        except Exception as exc:  # 单规则失败不影响其他
            logger.warning("预警规则 %s 评估失败: %s", rule_id, exc)
            result["error"] = str(exc)
        return result

    def _metric_value(self, symbol: str, metric: str) -> Optional[float]:
        bars = market_service.bars(symbol, "2000-01-01", _today())
        if not bars:
            return None
        if metric == "price":
            return float(bars[-1].close)
        if metric == "daily_change_pct":
            if len(bars) < 2:
                return None
            prev, cur = bars[-2].close, bars[-1].close
            if prev <= 0:
                return None
            return (cur - prev) / prev * 100.0
        return None

    @staticmethod
    def _compare(value: float, operator: str, threshold: float) -> bool:
        if operator == ">":
            return value > threshold
        if operator == "<":
            return value < threshold
        if operator == ">=":
            return value >= threshold
        if operator == "<=":
            return value <= threshold
        return False

    def _compare_cross(self, symbol: str, operator: str, threshold: float) -> bool:
        bars = market_service.bars(symbol, "2000-01-01", _today())
        if len(bars) < 2:
            return False
        prev = float(bars[-2].close)
        cur = float(bars[-1].close)
        if operator == "cross_above":
            return prev <= threshold < cur
        if operator == "cross_below":
            return prev >= threshold > cur
        return False

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

    def _notify(self, rule: dict, value: float) -> None:
        op_text = {
            ">": "高于",
            "<": "低于",
            ">=": "不低于",
            "<=": "不高于",
            "cross_above": "上穿",
            "cross_below": "下穿",
        }.get(rule["operator"], rule["operator"])
        metric_text = {"price": "最新价", "daily_change_pct": "当日涨跌幅(%)"}.get(
            rule["metric"], rule["metric"]
        )
        title = f"预警触发：{rule['name']}"
        content = (
            f"标的 {rule['symbol']} 的{metric_text} {value:.4f} {op_text} 阈值 {rule['threshold']:.4f}。"
        )
        message = NotificationMessage(
            title=title,
            content=content,
            level="warning",
            fields={
                "symbol": rule["symbol"],
                "metric": rule["metric"],
                "value": round(value, 4),
                "threshold": rule["threshold"],
            },
        )
        notification_service.notify(message)

    @staticmethod
    def _row_to_dict(row: dict) -> dict:
        return {
            "id": row["id"],
            "name": row["name"],
            "symbol": row["symbol"],
            "metric": row["metric"],
            "operator": row["operator"],
            "threshold": row["threshold"],
            "cooldown_minutes": row["cooldown_minutes"],
            "enabled": bool(row["enabled"]),
            "created_at": row["created_at"],
            "last_triggered": row.get("last_triggered"),
            "trigger_count": row.get("trigger_count") or 0,
        }


alert_service = AlertService()
