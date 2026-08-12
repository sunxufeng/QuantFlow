"""QuantFlow 通知模块（V1.1 N5）：渠道抽象 + Webhook/飞书 + 服务。"""

from __future__ import annotations

from .base import NotificationChannel, NotificationMessage
from .channels import FeishuChannel, WebhookChannel, build_channel
from .service import NotificationService, notification_service

__all__ = [
    "NotificationChannel",
    "NotificationMessage",
    "WebhookChannel",
    "FeishuChannel",
    "build_channel",
    "NotificationService",
    "notification_service",
]
