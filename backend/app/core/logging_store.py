"""结构化日志（M4-3）。

- :class:`JsonFormatter`：日志记录序列化为 JSON（含请求上下文字段）；
- :class:`RingBufferHandler`：内存环形缓冲（默认 2000 条），供 /api/logs 查询；
- :class:`RequestContextMiddleware`：为每个 HTTP 请求生成 request_id，解析
  Bearer 令牌得到 user_id，注入 contextvars，使该请求期间的日志自动携带上下文。

查询权限：平台 admin 可见全部日志；普通用户仅可见自身请求上下文日志与系统日志。
"""

from __future__ import annotations

import contextvars
import json
import logging
import threading
import time
import uuid
from collections import deque
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from .security import decode_token

_request_ctx: contextvars.ContextVar[Dict[str, Any]] = contextvars.ContextVar(
    "qf_request_ctx", default={}
)

_EXTRA_FIELDS = ("request_id", "user_id", "status", "method", "path", "duration_ms")


def current_ctx() -> dict:
    return _request_ctx.get()


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        entry: Dict[str, Any] = {
            "ts": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }
        for key in _EXTRA_FIELDS:
            value = record.__dict__.get(key)
            if value is not None:
                entry[key] = value
        ctx = _request_ctx.get()
        if ctx and ctx.get("request_id") and "request_id" not in entry:
            entry["request_id"] = ctx["request_id"]
        if ctx and ctx.get("user_id") and "user_id" not in entry:
            entry["user_id"] = ctx["user_id"]
        if record.exc_info:
            entry["exc_info"] = self.formatException(record.exc_info)
        return json.dumps(entry, ensure_ascii=False)


class RingBufferHandler(logging.Handler):
    """内存环形缓冲日志处理器（供查询 API 使用）。"""

    def __init__(self, capacity: int = 2000) -> None:
        super().__init__()
        self.capacity = capacity
        self._records: deque = deque(maxlen=capacity)
        self._lock = threading.Lock()

    def emit(self, record: logging.LogRecord) -> None:
        try:
            entry: Dict[str, Any] = {
                "ts": datetime.fromtimestamp(
                    record.created, tz=timezone.utc
                ).isoformat(),
                "level": record.levelname,
                "logger": record.name,
                "message": record.getMessage(),
            }
            for key in _EXTRA_FIELDS:
                value = record.__dict__.get(key)
                if value is not None:
                    entry[key] = value
            ctx = _request_ctx.get()
            if ctx.get("request_id") and "request_id" not in entry:
                entry["request_id"] = ctx["request_id"]
            if ctx.get("user_id") and "user_id" not in entry:
                entry["user_id"] = ctx["user_id"]
        except Exception:  # 日志处理器不得影响主流程
            self.handleError(record)
            return
        with self._lock:
            self._records.appendleft(entry)

    def query(
        self,
        level: Optional[str] = None,
        logger: Optional[str] = None,
        keyword: Optional[str] = None,
        limit: int = 100,
        offset: int = 0,
        viewer: Optional[dict] = None,
    ) -> dict:
        with self._lock:
            items = list(self._records)
        if viewer is None or viewer.get("role") != "admin":
            viewer_id = viewer.get("id") if viewer else None
            items = [
                item
                for item in items
                if item.get("user_id") is None or item.get("user_id") == viewer_id
            ]
        if level:
            items = [item for item in items if item["level"] == level.upper()]
        if logger:
            items = [item for item in items if logger in item["logger"]]
        if keyword:
            kw = keyword.lower()
            items = [
                item
                for item in items
                if kw in item["message"].lower()
                or kw in str(item.get("path", "")).lower()
            ]
        total = len(items)
        return {"total": total, "limit": limit, "offset": offset, "items": items[offset : offset + limit]}


LOG_STORE = RingBufferHandler()


def install() -> None:
    """把环形缓冲挂到根 logger 与 quantflow logger。

    - 根 logger：捕获服务运行期全部日志（uvicorn / 第三方）；
    - quantflow logger：显式 DEBUG + 停止向上传播，避免 pytest 等外部 capture
      提高根日志级别时丢失 INFO 记录，同时防止记录被重复写入缓冲。
    """
    root = logging.getLogger()
    if not any(isinstance(h, RingBufferHandler) for h in root.handlers):
        root.addHandler(LOG_STORE)
    qf = logging.getLogger("quantflow")
    qf.setLevel(logging.DEBUG)
    qf.propagate = False
    if not any(isinstance(h, RingBufferHandler) for h in qf.handlers):
        qf.addHandler(LOG_STORE)


class RequestContextMiddleware:
    """HTTP 请求日志中间件（注入 request_id / user_id 上下文）。"""

    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        request_id = f"r_{uuid.uuid4().hex[:12]}"
        user_id = None
        for name, value in scope.get("headers", []):
            if name == b"authorization":
                auth = value.decode("utf-8", "ignore")
                if auth.lower().startswith("bearer "):
                    payload = decode_token(auth[7:].strip())
                    if payload:
                        user_id = payload.get("uid")
        token = _request_ctx.set({"request_id": request_id, "user_id": user_id})
        start = time.time()
        status_code = 0

        async def send_wrapper(message):
            nonlocal status_code
            if message["type"] == "http.response.start":
                status_code = message.get("status", 0)
            await send(message)

        try:
            await self.app(scope, receive, send_wrapper)
        except Exception:
            status_code = status_code or 500
            raise
        finally:
            duration_ms = round((time.time() - start) * 1000, 1)
            log = logging.getLogger("quantflow.request")
            log.info(
                "%s %s -> %s (%.1fms)",
                scope.get("method", ""),
                scope.get("path", ""),
                status_code,
                duration_ms,
                extra={
                    "request_id": request_id,
                    "user_id": user_id,
                    "method": scope.get("method", ""),
                    "path": scope.get("path", ""),
                    "status": status_code,
                    "duration_ms": duration_ms,
                },
            )
            _request_ctx.reset(token)
