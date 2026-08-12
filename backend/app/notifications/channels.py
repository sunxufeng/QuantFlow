"""具体通知渠道：Webhook / 飞书自定义机器人（V1.1 N5）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import time
from typing import Any, Dict, Optional

import httpx

from .base import NotificationChannel, NotificationMessage


def _post(url: str, payload: Dict[str, Any], timeout: float = 10.0) -> None:
    """同步 POST JSON；非 2xx 抛 RuntimeError。便于测试 monkeypatch。"""
    resp = httpx.post(url, json=payload, timeout=timeout)
    if resp.status_code >= 400:
        raise RuntimeError(f"通知发送失败: HTTP {resp.status_code} {resp.text[:200]}")


class WebhookChannel(NotificationChannel):
    """通用 Webhook：POST JSON 到用户配置的 URL。"""

    type = "webhook"

    def validate(self) -> None:
        if not self.config.get("url"):
            raise ValueError("Webhook 渠道需要 url")

    def send(self, message: NotificationMessage) -> None:
        url = self.config.get("url")
        if not url:
            raise ValueError("Webhook 渠道未配置 url")
        payload = {
            "title": message.title,
            "content": message.content,
            "level": message.level,
            "fields": message.fields,
            "timestamp": int(time.time()),
        }
        _post(url, payload)


class FeishuChannel(NotificationChannel):
    """飞书自定义机器人：支持加签（secret）校验。"""

    type = "feishu"

    def validate(self) -> None:
        if not self.config.get("webhook"):
            raise ValueError("飞书渠道需要 webhook")

    def _sign(self, secret: str, timestamp: int) -> str:
        string_to_sign = f"{timestamp}\n{secret}"
        hmac_code = hmac.new(
            secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha256
        ).digest()
        return base64.b64encode(hmac_code).decode("utf-8")

    def send(self, message: NotificationMessage) -> None:
        webhook = self.config.get("webhook")
        if not webhook:
            raise ValueError("飞书渠道未配置 webhook")
        timestamp = int(time.time() * 1000)
        payload: Dict[str, Any] = {
            "msg_type": "text",
            "content": {"text": message.to_text()},
        }
        secret = self.config.get("secret")
        if secret:
            payload["timestamp"] = timestamp
            payload["sign"] = self._sign(secret, timestamp)
        _post(webhook, payload)


# 已注册渠道类型 → 实现类
CHANNEL_REGISTRY: Dict[str, type] = {
    WebhookChannel.type: WebhookChannel,
    FeishuChannel.type: FeishuChannel,
}


def build_channel(channel_type: str, name: str, config: Dict[str, Any], channel_id: Optional[str] = None) -> NotificationChannel:
    """按类型构造渠道实例并做配置校验。"""
    cls = CHANNEL_REGISTRY.get(channel_type)
    if cls is None:
        raise ValueError(f"未知通知渠道类型: {channel_type}")
    channel = cls(name=name, config=config, channel_id=channel_id)
    channel.validate()
    return channel
