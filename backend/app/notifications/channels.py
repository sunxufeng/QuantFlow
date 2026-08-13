"""具体通知渠道：Webhook / 飞书自定义机器人（V1.1 N5）。"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import smtplib
import ssl
import time
from email.message import EmailMessage
from typing import Any, Dict, List, Optional, Sequence

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


def _send_email(
    smtp_host: str,
    smtp_port: int,
    sender: str,
    recipients: Sequence[str],
    subject: str,
    body: str,
    username: Optional[str] = None,
    password: Optional[str] = None,
    use_tls: bool = True,
    timeout: float = 15.0,
) -> None:
    """通过 SMTP 发送纯文本邮件；抽取为独立函数便于测试 monkeypatch。

    - ``use_tls=True``：隐式 SSL（SMTP_SSL，常用于 465）；
    - ``use_tls=False``：明文连接后 STARTTLS（常用于 587）。
    """
    msg = EmailMessage()
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg["Subject"] = subject
    msg.set_content(body)

    if use_tls:
        server = smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=timeout, context=ssl.create_default_context())
    else:
        server = smtplib.SMTP(smtp_host, smtp_port, timeout=timeout)
    try:
        if not use_tls:
            server.starttls(context=ssl.create_default_context())
        if username:
            server.login(username, password or "")
        server.sendmail(sender, list(recipients), msg.as_string())
    finally:
        server.quit()


class EmailChannel(NotificationChannel):
    """邮件渠道（SMTP）：运行完成/失败时向配置的收件人发送邮件。

    配置（config）：
      - smtp_host  必填，SMTP 服务器地址
      - smtp_port  端口，默认 465（use_tls=True）或 587（use_tls=False）
      - username   可选，SMTP 登录用户名（为空则不登录）
      - password   可选，SMTP 登录密码/授权码
      - use_tls    bool，默认 True（SMTP_SSL）；False 走 STARTTLS
      - from_addr  可选，发件人；缺省用 username 或 username@smtp_host 兜底
      - to_addrs   必填，收件人；支持 list 或逗号/分号分隔字符串
    """

    type = "email"

    def validate(self) -> None:
        if not self.config.get("smtp_host"):
            raise ValueError("邮件渠道需要 smtp_host")
        to = self.config.get("to_addrs")
        if not to:
            raise ValueError("邮件渠道需要 to_addrs（收件人）")
        if isinstance(to, str):
            if not to.strip():
                raise ValueError("邮件渠道 to_addrs 不能为空")
        elif isinstance(to, (list, tuple)):
            if not to:
                raise ValueError("邮件渠道 to_addrs 不能为空")

    @staticmethod
    def _normalize_recipients(to_addrs: Any) -> List[str]:
        if isinstance(to_addrs, str):
            return [a.strip() for a in to_addrs.replace(";", ",").split(",") if a.strip()]
        return [str(a).strip() for a in to_addrs if str(a).strip()]

    def send(self, message: NotificationMessage) -> None:
        host = self.config.get("smtp_host")
        if not host:
            raise ValueError("邮件渠道未配置 smtp_host")
        port = int(self.config.get("smtp_port", 465))
        use_tls = bool(self.config.get("use_tls", True))
        username = self.config.get("username") or None
        password = self.config.get("password") or None
        sender = self.config.get("from_addr") or username or ""
        if not sender:
            raise ValueError("邮件渠道无法推断发件人（请配置 from_addr 或 username）")
        recipients = self._normalize_recipients(self.config.get("to_addrs"))
        if not recipients:
            raise ValueError("邮件渠道无有效收件人")
        subject = f"[QuantFlow] {message.title}"
        body = message.to_text()
        _send_email(
            smtp_host=host,
            smtp_port=port,
            sender=sender,
            recipients=recipients,
            subject=subject,
            body=body,
            username=username,
            password=password,
            use_tls=use_tls,
        )


# 已注册渠道类型 → 实现类（置于所有渠道类定义之后）
CHANNEL_REGISTRY: Dict[str, type] = {
    WebhookChannel.type: WebhookChannel,
    FeishuChannel.type: FeishuChannel,
    EmailChannel.type: EmailChannel,
}


def build_channel(channel_type: str, name: str, config: Dict[str, Any], channel_id: Optional[str] = None) -> NotificationChannel:
    """按类型构造渠道实例并做配置校验。"""
    cls = CHANNEL_REGISTRY.get(channel_type)
    if cls is None:
        raise ValueError(f"未知通知渠道类型: {channel_type}")
    channel = cls(name=name, config=config, channel_id=channel_id)
    channel.validate()
    return channel
