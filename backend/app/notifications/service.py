"""通知服务：渠道配置持久化 + 统一触发（V1.1 N5）。

渠道配置存于 notification_channels 表；运行完成/失败时遍历启用渠道发送，
单个渠道失败不影响其他渠道与运行结果。
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Dict, List, Optional

from ..core.db import db
from .base import NotificationMessage
from .channels import build_channel

logger = logging.getLogger("quantflow.notifications")


class NotificationService:
    def configure(self, channel_type: str, name: str, config: Dict[str, Any]) -> dict:
        """新增渠道配置（先做配置校验），返回记录。"""
        build_channel(channel_type, name, config)  # 校验失败直接抛
        channel_id = uuid.uuid4().hex[:12]
        now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
        db.execute(
            "INSERT INTO notification_channels (id, type, name, config, enabled, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                channel_id,
                channel_type,
                name,
                json.dumps(config, ensure_ascii=False),
                1,
                now,
            ),
        )
        return {
            "id": channel_id,
            "type": channel_type,
            "name": name,
            "config": config,
            "enabled": True,
            "created_at": now,
        }

    def list(self) -> List[dict]:
        rows = db.query(
            "SELECT id, type, name, config, enabled, created_at "
            "FROM notification_channels ORDER BY created_at DESC, id"
        )
        return [
            {
                "id": r["id"],
                "type": r["type"],
                "name": r["name"],
                "config": json.loads(r["config"]),
                "enabled": bool(r["enabled"]),
                "created_at": r["created_at"],
            }
            for r in rows
        ]

    def get(self, channel_id: str) -> Optional[dict]:
        for c in self.list():
            if c["id"] == channel_id:
                return c
        return None

    def remove(self, channel_id: str) -> bool:
        cur = db.execute("DELETE FROM notification_channels WHERE id = ?", (channel_id,))
        return (cur.rowcount or 0) > 0

    def set_enabled(self, channel_id: str, enabled: bool) -> bool:
        cur = db.execute(
            "UPDATE notification_channels SET enabled = ? WHERE id = ?",
            (1 if enabled else 0, channel_id),
        )
        return (cur.rowcount or 0) > 0

    def test_send(self, channel_id: str) -> None:
        """向指定渠道发送一条测试通知（用于校验配置是否可用）。"""
        rec = self.get(channel_id)
        if not rec:
            raise KeyError(f"渠道不存在: {channel_id}")
        channel = build_channel(rec["type"], rec["name"], rec["config"], rec["id"])
        channel.send(
            NotificationMessage(
                title="QuantFlow 通知测试",
                content="这是一条来自 QuantFlow 的测试通知，说明渠道配置可用。",
                level="info",
                fields={"channel": rec["name"], "type": rec["type"]},
            )
        )

    def notify_run_finished(
        self,
        run_id: str,
        workflow_name: str,
        status: str,
        error: Optional[str] = None,
    ) -> None:
        """工作流运行成功/失败后统一推送（由 RunService 调用）。"""
        ok = status in ("SUCCEEDED", "success", "succeeded")
        title = f"工作流运行{'成功' if ok else '失败'}"
        content = (
            f"工作流「{workflow_name or '未命名'}」运行{'已完成' if ok else '失败'}。"
        )
        if error:
            content += f"\n错误：{error}"
        message = NotificationMessage(
            title=title,
            content=content,
            level="success" if ok else "error",
            fields={
                "run_id": run_id,
                "workflow": workflow_name or "-",
                "status": status,
            },
        )
        for rec in self.list():
            if not rec["enabled"]:
                continue
            try:
                channel = build_channel(rec["type"], rec["name"], rec["config"], rec["id"])
                channel.send(message)
            except Exception as exc:  # 单渠道失败不影响其他渠道
                logger.warning("通知渠道 %s 发送失败: %s", rec["id"], exc)

    def channels_summary(self) -> Dict[str, int]:
        rows = self.list()
        return {
            "total": len(rows),
            "enabled": sum(1 for r in rows if r["enabled"]),
        }


notification_service = NotificationService()
