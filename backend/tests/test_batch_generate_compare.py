"""V3.4 批量生成并对比回测 API 测试。"""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def _auth(username: str = "batch_u") -> dict:
    client.post("/api/auth/register", json={"username": username, "password": "secret123"})
    r = client.post("/api/auth/login", json={"username": username, "password": "secret123"})
    return {"Authorization": f"Bearer {r.json()['token']}"}


def test_batch_requires_auth():
    resp = client.post("/api/workflows/batch-generate-compare", json={"prompts": ["动量"]})
    assert resp.status_code == 401


def test_batch_empty_prompts_422():
    headers = _auth("batch_u1")
    resp = client.post(
        "/api/workflows/batch-generate-compare", json={"prompts": []}, headers=headers
    )
    assert resp.status_code == 422


def test_batch_generates_runs_and_compares():
    headers = _auth("batch_u2")
    resp = client.post(
        "/api/workflows/batch-generate-compare",
        headers=headers,
        json={"prompts": ["动量因子策略，用 TEST.STOCK", "均线金叉策略，用 TEST.BANK"], "use_llm": False},
    )
    assert resp.status_code == 200
    d = resp.json()
    items = d["items"]
    assert len(items) == 2
    for it in items:
        assert it["ok"] is True, it.get("error")
        assert "total_return" in it["metrics"]
        assert isinstance(it["curve_pct"], list) and len(it["curve_pct"]) > 0
        # 曲线首点应为 0.0（归一化）
        assert it["curve_pct"][0]["pct"] == 0.0


def test_batch_caps_at_five():
    headers = _auth("batch_u3")
    prompts = [f"策略{i}，用 TEST.STOCK" for i in range(8)]
    resp = client.post(
        "/api/workflows/batch-generate-compare",
        headers=headers,
        json={"prompts": prompts, "use_llm": False},
    )
    assert resp.status_code == 200
    assert len(resp.json()["items"]) == 5


def test_batch_falls_back_to_rule_when_llm_backtest_unrunnable(monkeypatch):
    """LLM 生成的策略表达式非法致回测节点 blocked，应回退规则模板并重跑成功。"""
    import app.api.workflows as wf

    state = {"gen": 0, "run": 0}

    def fake_gen(text, use_llm=True):
        state["gen"] += 1
        if use_llm:
            # 结构合法、以 backtest.run 收口，但运行期回测节点无输出（模拟表达式非法）
            return {
                "name": "llm", "description": "", "source": "llm", "warnings": [],
                "nodes": [
                    {"id": "n1", "node_type": "data.quotes", "params": {}},
                    {"id": "n2", "node_type": "backtest.run", "params": {}},
                ],
                "edges": [{"id": "e1", "source": "n1", "source_port": "table", "target": "n2", "target_port": "table"}],
            }
        from app.workflows.generate import generate_from_text as real

        return real(text, use_llm=False)

    monkeypatch.setattr(wf, "generate_from_text", fake_gen)

    class FakeResult:
        def __init__(self, has_bt: bool) -> None:
            self._has_bt = has_bt

        def to_dict(self, include_outputs: bool = False) -> dict:
            if self._has_bt:
                return {
                    "nodes": [
                        {
                            "node_id": "x", "status": "succeeded",
                            "outputs": {
                                "out": {
                                    "summary": {"__type__": "table", "rows": [{"metric": "sharpe", "value": 1.2}]},
                                    "equity": {"__type__": "table", "rows": [
                                        {"date": "2024-01-01", "total_value": 1.0},
                                        {"date": "2024-01-02", "total_value": 1.05},
                                    ]},
                                }
                            },
                        }
                    ]
                }
            return {"nodes": [{"node_id": "x", "status": "blocked", "outputs": {}}]}

    def fake_exec(nodes, edges, workflow_name=None):
        state["run"] += 1
        return FakeResult(state["run"] >= 2)  # 第一次(llm)无回测，第二次(规则)有回测

    monkeypatch.setattr(wf.run_module.RUN_SERVICE, "execute_sync", fake_exec)

    headers = _auth("batch_u4")
    resp = client.post(
        "/api/workflows/batch-generate-compare",
        headers=headers,
        json={"prompts": ["用 RSI 做回测"], "use_llm": True},
    )
    assert resp.status_code == 200
    items = resp.json()["items"]
    assert len(items) == 1
    it = items[0]
    assert it["ok"] is True, it.get("error")
    assert it["source"] == "llm→rule(fallback)"
    assert it["metrics"].get("sharpe") == 1.2
    assert state["gen"] == 2 and state["run"] == 2

