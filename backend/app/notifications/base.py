"""通知抽象层（V1.1 N5）。

定义统一的通知消息与渠道接口，供 Webhook / 飞书机器人等具体渠道实现，
以及工作流运行完成/失败时统一触发。
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Dict, Optional


@dataclass
class NotificationMessage:
    """一条通知：标题 + 正文 + 级别 + 附加字段。"""

    title: str
    content: str
    level: str = "info"  # info | success | warning | error
    fields: Dict[str, Any] = field(default_factory=dict)

    def to_text(self) -> str:
        lines = [self.title, "", self.content]
        for k, v in self.fields.items():
            lines.append(f"{k}: {v}")
        return "\n".join(lines)


class NotificationChannel(ABC):
    """渠道抽象：每个渠道由 type 标识，配置以 dict 传入。"""

    type: str = "base"

    def __init__(self, name: str, config: Dict[str, Any], channel_id: Optional[str] = None) -> None:
        self.name = name
        self.config = config or {}
        self.channel_id = channel_id

    @abstractmethod
    def send(self, message: NotificationMessage) -> None:
        """发送通知；失败抛异常。"""

    def validate(self) -> None:
        """配置校验，失败抛 ValueError。默认不校验。"""
