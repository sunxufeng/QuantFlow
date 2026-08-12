"""N1 LLM 策略助手测试。

覆盖：provider 工厂（默认 mock）、MockProvider 确定性、OpenAIProvider 缺 key 报错、
/llm/assist 鉴权与响应、/llm/status、llm.assistant 节点在 DAG 中执行。
无 key 环境下全程使用 mock，保证可测可跑。
"""

import pytest

from app.core.llm import LLMMessage, MockProvider, OpenAIProvider, get_provider, reset_provider
from app.core.runs import RunService, RunStatus


@pytest.fixture(autouse=True)
def _reset():
    reset_provider()
    yield
    reset_provider()


def test_default_provider_is_mock_without_key(monkeypatch):
    monkeypatch.setattr("app.config.settings.LLM_PROVIDER", "mock")
    monkeypatch.setattr("app.config.settings.LLM_API_KEY", "")
    p = get_provider()
    assert isinstance(p, MockProvider)
    assert p.is_configured() is True


def test_mock_provider_is_deterministic_and_echoes_prompt():
    p = MockProvider()
    out = p.chat([LLMMessage(role="user", content="帮我做个动量策略")])
    assert "帮我做个动量策略" in out
    assert "mock" in out.lower()


def test_openai_provider_requires_key():
    with pytest.raises(ValueError):
        OpenAIProvider(api_key="", base_url="https://x", model="m")


def test_assist_requires_auth(client):
    # client 是未鉴权的 TestClient 夹具
    resp = client.post("/api/llm/assist", json={"prompt": "hi"})
    assert resp.status_code == 401


def test_assist_returns_mock_text(auth_client):
    resp = auth_client.post("/api/llm/assist", json={"prompt": "构建均线策略"})
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "mock"
    assert "均线策略" in body["text"]
    assert body["configured"] is True


def test_status_endpoint(auth_client):
    resp = auth_client.get("/api/llm/status")
    assert resp.status_code == 200
    body = resp.json()
    assert body["provider"] == "mock"


def test_llm_node_executes_in_workflow():
    svc = RunService(backend="local")
    resp = svc.submit(
        [
            {
                "id": "a",
                "node_type": "llm.assistant",
                "params": {"prompt": "回测节点怎么连", "system": "量化助手"},
            }
        ],
        [],
        workflow_name="n1-node",
    )
    rec = svc.wait(resp["run_id"], timeout=10)
    assert rec["status"] == RunStatus.SUCCEEDED
    assert "回测节点怎么连" in rec["nodes"]["a"]["outputs"]["text"]
