"""券商凭证配置持久化（V1.7）。

配置以单个 JSON 对象存入 app_settings(broker.config)：
    {
      broker:     "none" | "simulated" | "universal" | "easytrade" | "xuntou",
      api_key:    str,
      api_secret: str,
      base_url:   str,
      account_id: str,
      extra:      dict,
    }

优先级：已保存的数据库配置 > 环境变量默认值。
敏感字段（api_key / api_secret / account_id）GET 时由调用方负责脱敏。
"""

from __future__ import annotations

import os
from typing import Any, Dict

from ..settings_store import get_setting, set_setting

BROKER_CONFIG_KEY = "broker.config"

SUPPORTED_BROKERS = ("none", "simulated", "universal", "easytrade", "xuntou", "qmt", "ctp")


def default_broker_config() -> Dict[str, Any]:
    """环境变量默认值（首次使用 / 未保存配置时）。"""
    return {
        "broker": os.getenv("QF_BROKER", "none"),
        "api_key": os.getenv("QF_BROKER_API_KEY", ""),
        "api_secret": os.getenv("QF_BROKER_SECRET", ""),
        "base_url": os.getenv("QF_BROKER_BASE_URL", ""),
        "account_id": os.getenv("QF_BROKER_ACCOUNT", ""),
        "extra": {},
    }


def load_broker_config() -> Dict[str, Any]:
    """读取当前生效配置（数据库覆盖默认值，缺字段回退默认）。"""
    stored = get_setting(BROKER_CONFIG_KEY)
    base = default_broker_config()
    if isinstance(stored, dict):
        base.update({k: v for k, v in stored.items() if k in base})
    return base


def save_broker_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """持久化配置（仅保留约定字段，避免脏数据）。"""
    clean = {k: cfg.get(k, default_broker_config()[k]) for k in default_broker_config()}
    set_setting(BROKER_CONFIG_KEY, clean)
    return clean


def mask_secret(key: str) -> str:
    """脱敏：仅保留末尾 4 位，其余以 **** 替代；无 key 返回空串。"""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]
