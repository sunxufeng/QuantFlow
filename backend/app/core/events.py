"""运行消息总线（M2 执行引擎）。

对标开发计划 §4.2「运行状态 WebSocket 推送（消息总线）」：

- :class:`RunEvent`：一次运行生命周期内的离散事件（开始 / 节点状态变更 / 结束）
- :class:`EventBus`：进程内发布-订阅总线。执行器发布事件，
  运行持久化服务与 WebSocket 推送器各自订阅消费（同步回调，失败不影响主流程）。

V1.0 采用进程内总线（单进程部署足够）；未来拆分 worker 时替换为
Redis pub/sub 或消息队列实现，接口不变。
"""

from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

# 事件类型
RUN_STARTED = "run_started"
NODE_RUNNING = "node_running"
NODE_SUCCEEDED = "node_succeeded"
NODE_FAILED = "node_failed"
NODE_BLOCKED = "node_blocked"
RUN_SUCCEEDED = "run_succeeded"
RUN_FAILED = "run_failed"


@dataclass
class RunEvent:
    """运行生命周期事件。

    :param run_id: 运行实例 id
    :param kind:   事件类型（见模块级常量）
    :param node_id: 节点事件时的节点 id
    :param payload: 附带数据（状态、耗时、错误等）
    """

    run_id: str
    kind: str
    node_id: Optional[str] = None
    payload: Dict[str, Any] = field(default_factory=dict)
    timestamp: float = field(default_factory=time.time)

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "kind": self.kind,
            "node_id": self.node_id,
            "payload": self.payload,
            "timestamp": self.timestamp,
        }


# 订阅回调签名：(RunEvent) -> None
EventCallback = Callable[[RunEvent], None]


class EventBus:
    """进程内发布-订阅总线（线程安全）。"""

    def __init__(self) -> None:
        self._subscribers: List[EventCallback] = []
        self._lock = threading.Lock()

    def subscribe(self, callback: EventCallback) -> Callable[[], None]:
        """订阅事件流，返回退订函数。"""
        with self._lock:
            self._subscribers.append(callback)

        def _unsubscribe() -> None:
            with self._lock:
                if callback in self._subscribers:
                    self._subscribers.remove(callback)

        return _unsubscribe

    def publish(self, event: RunEvent) -> None:
        """广播事件；订阅者异常被吞掉，不影响执行主流程。"""
        with self._lock:
            subscribers = list(self._subscribers)
        for cb in subscribers:
            try:
                cb(event)
            except Exception:  # noqa: BLE001 - 订阅者失败不得中断运行
                continue

    def clear(self) -> None:
        with self._lock:
            self._subscribers.clear()


# 全局总线（单进程部署）
EVENT_BUS = EventBus()
