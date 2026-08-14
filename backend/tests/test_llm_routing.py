"""V3.3 多 LLM 路由测试。"""
from __future__ import annotations

import pytest

from app.core.llm.providers import (
    LLMMessage,
    MockProvider,
    RoutingProvider,
    build_provider,
    reset_provider,
)
from app.core.llm.config import default_llm_config, load_llm_config, save_llm_config


class _FailProvider(MockProvider):
    name = "fail"

    def chat(self, messages, *, temperature=None, max_tokens=None):
        raise RuntimeError("boom-fail")


def test_build_provider_single_when_no_list():
    p = build_provider({"provider": "mock", "model": "m1"})
    assert not isinstance(p, RoutingProvider)
    assert p.name == "mock"


def test_build_provider_with_list_skips_unbuildable():
    # openai 缺 key 无法构建 -> 跳过；只剩 mock
    cfg = {
        "providers": [
            {"provider": "openai", "api_key": "", "model": "x"},
            {"provider": "mock", "model": "m9"},
        ]
    }
    p = build_provider(cfg)
    assert isinstance(p, RoutingProvider)
    chain = p.chain_info()
    assert chain[0]["name"] == "mock"


def test_routing_falls_back_to_second():
    r = RoutingProvider([_FailProvider(), MockProvider("m2")])
    out = r.chat([LLMMessage(role="user", content="hi")])
    assert "演示模式" in out  # 命中 mock 兜底
    info = r.chain_info()
    assert info[0]["name"] == "fail" and info[1]["name"] == "mock"


def test_routing_all_fail_raises():
    r = RoutingProvider([_FailProvider(), _FailProvider()])
    with pytest.raises(RuntimeError):
        r.chat([LLMMessage(role="user", content="x")])


def test_default_config_has_providers_field():
    assert "providers" in default_llm_config()
    assert default_llm_config()["providers"] == []


def test_save_load_preserves_providers():
    cfg = default_llm_config()
    cfg["providers"] = [
        {"provider": "mock", "model": "a"},
        {"provider": "mock", "model": "b"},
    ]
    saved = save_llm_config(cfg)
    loaded = load_llm_config()
    assert loaded["providers"] == saved["providers"]
    assert len(loaded["providers"]) == 2
    # 复原，避免污染共享 settings store
    reset_provider()
    save_llm_config(default_llm_config())
