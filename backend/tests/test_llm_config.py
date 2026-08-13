"""V1.4 LLM 配置页 API 测试。

覆盖：GET /llm/config（脱敏）、PUT /llm/config（持久化 + 重置 provider）、
PUT 后 assist 立即生效、POST /llm/config/test（mock 连通成功；缺 key 的 openai 报错）。
所有用例使用鉴权客户端与隔离测试库。
"""

import pytest

from app.core.llm import get_provider, reset_provider
from app.core.llm.config import LLM_CONFIG_KEY
from app.core.settings_store import get_setting


@pytest.fixture(autouse=True)
def _reset():
    reset_provider()
    yield
    reset_provider()


def test_get_config_masks_key_and_defaults(auth_client):
    resp = auth_client.get("/api/llm/config")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] in ("mock", "openai")
    assert body["api_key_masked"] == ""  # 默认无 key
    assert body["has_api_key"] is False


def test_put_config_persists_and_masks(auth_client):
    resp = auth_client.put(
        "/api/llm/config",
        json={
            "provider": "openai",
            "base_url": "https://api.beaigo.com/v1",
            "api_key": "sk-secret-1234",
            "model": "gpt-5.6-sol",
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "openai"
    assert body["model"] == "gpt-5.6-sol"
    assert body["has_api_key"] is True
    assert body["api_key_masked"] == "****1234"  # 脱敏：保留末 4 位
    # 数据库里确实存了明文（服务端合法持有）
    stored = get_setting(LLM_CONFIG_KEY)
    assert stored["api_key"] == "sk-secret-1234"
    assert stored["base_url"] == "https://api.beaigo.com/v1"


def test_put_config_keeps_existing_key_when_empty(auth_client):
    # 先存一个 key
    auth_client.put(
        "/api/llm/config",
        json={"provider": "openai", "api_key": "sk-original-9999", "model": "m1"},
    )
    # 再更新但不传 key（空串）-> 保留原 key
    resp = auth_client.put(
        "/api/llm/config",
        json={"provider": "openai", "api_key": "", "model": "m2"},
    )
    assert resp.status_code == 200
    assert resp.json()["model"] == "m2"
    stored = get_setting(LLM_CONFIG_KEY)
    assert stored["api_key"] == "sk-original-9999"


def test_put_config_takes_effect_in_assist(auth_client, monkeypatch):
    # 切到 mock 并自定义 system prompt，验证 assist 实际生效
    resp = auth_client.put(
        "/api/llm/config",
        json={"provider": "mock", "system_prompt": "你是测试助手", "enabled": True},
    )
    assert resp.status_code == 200
    # provider 单例应已重置为 mock
    assert get_provider().name == "mock"
    r2 = auth_client.post("/api/llm/assist", json={"prompt": "任意问题"})
    assert r2.status_code == 200
    assert r2.json()["provider"] == "mock"


def test_test_config_mock_succeeds(auth_client):
    resp = auth_client.post("/api/llm/config/test", json={"provider": "mock", "enabled": True})
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is True
    assert body["provider"] == "mock"


def test_test_config_openai_requires_key(auth_client):
    # 不传 key 的 openai 配置 -> 400（provider_from_config 抛 ValueError）
    resp = auth_client.post(
        "/api/llm/config/test",
        json={"provider": "openai", "base_url": "https://x/v1", "api_key": "", "model": "m"},
    )
    assert resp.status_code == 400


def test_test_config_openai_bad_key_reports_failure(auth_client):
    # 传错误 key 应返回 ok=False（不抛 500）
    resp = auth_client.post(
        "/api/llm/config/test",
        json={
            "provider": "openai",
            "base_url": "https://api.openai.com/v1",
            "api_key": "sk-invalid-key",
            "model": "gpt-4o-mini",
            "enabled": True,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["ok"] is False
    assert "error" in body
