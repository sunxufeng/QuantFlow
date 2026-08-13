"""LLM 自定义配置持久化（V1.4）。

配置以单个 JSON 对象存入 app_settings(llm.config)：
    {
      provider:      "mock" | "openai",
      base_url:      str,        # OpenAI 兼容 base（代码自动追加 /chat/completions）
      api_key:       str,        # 敏感，GET 时脱敏
      model:         str,
      system_prompt: str,        # 空 -> 使用内置默认量化系统提示
      temperature:   float,
      max_tokens:    int,
      timeout:       float,      # 单次请求超时（秒）
      enabled:       bool,
    }

优先级：已保存的数据库配置 > 环境变量默认值。未保存过则按环境变量给出默认值，
保证无 key 环境下行为与旧版一致（默认 mock）。
"""

from __future__ import annotations

from typing import Any, Dict

from ..settings_store import get_setting, set_setting
from ...config import settings as env_settings

LLM_CONFIG_KEY = "llm.config"


def default_llm_config() -> Dict[str, Any]:
    """环境变量的默认值（首次使用 / 未保存配置时）。"""
    return {
        "provider": env_settings.LLM_PROVIDER,
        "base_url": env_settings.LLM_BASE_URL,
        "api_key": env_settings.LLM_API_KEY,
        "model": env_settings.LLM_MODEL,
        "system_prompt": "",
        "temperature": env_settings.LLM_TEMPERATURE,
        "max_tokens": env_settings.LLM_MAX_TOKENS,
        "timeout": 90.0,
        "enabled": True,
    }


def load_llm_config() -> Dict[str, Any]:
    """读取当前生效配置（数据库覆盖默认值，缺字段回退默认）。"""
    stored = get_setting(LLM_CONFIG_KEY)
    base = default_llm_config()
    if isinstance(stored, dict):
        base.update({k: v for k, v in stored.items() if k in base})
    return base


def save_llm_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """持久化配置（仅保留约定字段，避免脏数据）。"""
    clean = {k: cfg.get(k, default_llm_config()[k]) for k in default_llm_config()}
    set_setting(LLM_CONFIG_KEY, clean)
    return clean


def mask_api_key(key: str) -> str:
    """脱敏：仅保留末尾 4 位，其余以 **** 替代；无 key 返回空串。"""
    if not key:
        return ""
    if len(key) <= 4:
        return "****"
    return "****" + key[-4:]
