"""QuantFlow SDK 端到端测试（V1.1 N2）。

通过 FastAPI ASGITransport 在进程内驱动后端，验证 SDK 可脚本化跑通：
注册/登录 → 行情 → 回测运行 → run_id 取回报告；以及 API Token 全流程。
"""

from __future__ import annotations

import os
import sys
import tempfile

# 隔离测试库，避免污染业务库；禁用调度器后台线程
_TMP = tempfile.mkdtemp(prefix="qf_sdk_test_")
os.environ.setdefault("QF_DB_PATH", os.path.join(_TMP, "sdk_test.db"))
os.environ.setdefault("QF_MARKET_PROVIDER", "fixture")
os.environ["QF_DISABLE_SCHEDULER"] = "1"

_HERE = os.path.dirname(os.path.abspath(__file__))  # sdk/python/tests
_ROOT = os.path.dirname(_HERE)  # sdk/python
_REPO = os.path.dirname(os.path.dirname(_ROOT))  # 仓库根（quantflow）
sys.path.insert(0, os.path.join(_REPO, "backend"))
sys.path.insert(0, _ROOT)

import pytest  # noqa: E402
from starlette.testclient import TestClient  # noqa: E402
from app.main import app  # noqa: E402
from app.core.db import db  # noqa: E402
from quantflow import QuantFlowClient, QuantFlowError  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_db():
    # 每个用例隔离业务库，避免多 TestClient 实例共享 WAL 连接的可见性干扰
    db.reset()
    yield
    db.reset()


@pytest.fixture
def client():
    # TestClient 本身是 httpx.Client 子类，可同步驱动 ASGI 应用
    with TestClient(app) as http_client:
        yield QuantFlowClient(base_url="http://testserver", _client=http_client)


def test_health(client):
    h = client.health()
    assert h["status"] == "ok"
    assert h["version"].startswith("2.")


def test_register_login_and_backtest_flow(client):
    user = client.register("sdk_user_1", "Test1234")
    assert user["username"] == "sdk_user_1"
    assert client._token  # 注册后自动持有令牌

    inst = client.instruments()
    assert inst["total"] >= 1

    bars = client.bars("TEST.STOCK", start="2024-01-01", end="2024-02-01")
    assert bars["count"] > 0

    report = client.run_backtest(
        symbols=["TEST.STOCK"],
        strategy="buy_hold",
        initial_cash=100000,
        start="2024-01-01",
        end="2024-12-31",
    )
    run_id = report["run_id"]
    assert run_id

    # 通过 run_id 取回报告
    fetched = client.get_backtest(run_id)
    assert fetched["run_id"] == run_id
    assert "metrics" in fetched


def test_api_token_lifecycle(client):
    client.register("sdk_user_2", "Test1234")

    created = client.create_token("sdk-ci", scopes=["*"])
    assert created["token"].startswith("qf.")
    prefix = created["prefix"]

    # 用 token 直接鉴权（复用同一 HTTP 客户端，无账号密码）
    # 注：list_tokens 需鉴权，可验证 token 真实生效
    token_client = QuantFlowClient(
        base_url="http://testserver", _client=client._client
    )
    token_client.set_token(created["token"])
    own_tokens = token_client.list_tokens()
    assert any(t["prefix"] == prefix for t in own_tokens)

    # 吊销后失效（list_tokens 需鉴权，吊销的 token 应被拒）
    client.revoke_token(prefix)
    bad = QuantFlowClient(base_url="http://testserver", _client=client._client)
    bad.set_token(created["token"])
    try:
        bad.list_tokens()
        assert False, "吊销的 token 应被拒"
    except QuantFlowError as exc:
        assert exc.status == 401


def _seed_price(symbol, price):
    db.execute(
        "INSERT OR REPLACE INTO market_bars(symbol, date, interval, open, high, low, close, volume, amount, source, adjustment) "
        "VALUES(?, '2024-01-01', 'daily', ?, ?, ?, ?, 1, ?, 'fixture', 'none')",
        (symbol, price * 0.99, price * 1.01, price * 0.99, price, price),
    )


def test_factor_and_workflow_and_trading_sdk_methods(client):
    client.register("sdk_user_3", "Test1234")

    # 因子库
    factor = client.create_factor("momentum_20", "close.pct_change(20)", category="动量")
    assert factor["name"] == "momentum_20"
    factors = client.list_factors()
    assert any(f["id"] == factor["id"] for f in factors["items"])

    # 工作流：使用一个最小节点构建有效工作流
    nodes = client.list_nodes()
    assert nodes
    first = nodes[0]
    wf = client.create_workflow(
        "sdk_wf",
        nodes=[{"id": "n1", "node_type": first["node_type"], "position": {"x": 0, "y": 0}, "data": {}}],
        edges=[],
        description="created by sdk",
    )
    assert wf["name"] == "sdk_wf"
    fetched = client.get_workflow(wf["id"])
    assert fetched["id"] == wf["id"]
    exported = client.export_workflow(wf["id"])
    assert "nodes" in exported

    # 交易
    _seed_price("TEST.STOCK", 100.0)
    summary = client.trading_summary()
    assert summary["cash"] == 1_000_000
    order = client.submit_order("TEST.STOCK", "buy", "market", 10)
    assert order["status"] == "filled"
    positions = client.trading_positions()
    assert len(positions) == 1
    analytics = client.trading_analytics()
    assert "max_drawdown" in analytics

    # LLM 配置读取（未配置时也应返回结构）
    cfg = client.llm_config()
    assert "provider" in cfg
