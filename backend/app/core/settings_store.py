"""通用键值设置存储（V1.4）。

为「用户可配置项」提供轻量持久化，当前用于 LLM 自定义配置。
- 表 ``app_settings(key PK, value, updated_at)``，value 以 JSON 字符串存储；
- ``get_setting`` / ``set_setting`` 自动序列化，读取失败回退默认值；
- 敏感字段（如 API Key）由调用方负责脱敏，本模块只做存取。

设计取舍：不做字段级 schema，采用单个 JSON blob 存配置对象，足够灵活且
避免频繁改表结构；配置对象字段由调用方约定。
"""

from __future__ import annotations

import json
import time
from typing import Any, Optional

from .db import db


def get_setting(key: str, default: Any = None) -> Any:
    """读取键对应的值（自动 JSON 反序列化）；不存在或解析失败返回 default。"""
    row = db.query_one("SELECT value FROM app_settings WHERE key = ?", (key,))
    if row is None:
        return default
    try:
        return json.loads(row["value"])
    except (json.JSONDecodeError, TypeError, KeyError):
        return default


def set_setting(key: str, value: Any) -> None:
    """写入键值（自动 JSON 序列化），已存在则覆盖 updated_at。"""
    payload = json.dumps(value, ensure_ascii=False)
    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    db.execute(
        "INSERT INTO app_settings (key, value, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value = excluded.value, updated_at = excluded.updated_at",
        (key, payload, now),
    )
