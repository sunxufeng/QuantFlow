"""V31 实盘 QMT/CTP 接入测试。

覆盖：连接器可用性检测（无 SDK/凭证时不可用）、gated 抛 GatewayNotConfigured、
live_capable/live_status 对 qmt/ctp 的识别、live positions/fills 端点在未配置时
返回结构化 409、broker 配置支持 qmt/ctp。真实柜台接入点已就位，凭证就绪即可连线。
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from app.core.broker import ctp, qmt
from app.core.broker.registry import connector_status, get_live_connector
from app.core.broker.config import SUPPORTED_BROKERS
from app.execution.gateway import GatewayNotConfigured, LiveExecutionGateway, Order, OrderSide
from app.main import app
from app.trading import engine

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v31_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v31_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    return c


def test_qmt_ctp_in_supported_brokers():
    assert "qmt" in SUPPORTED_BROKERS
    assert "ctp" in SUPPORTED_BROKERS


def test_qmt_connector_not_configured_without_sdk(monkeypatch):
    monkeypatch.delenv("QF_QMT_ACCOUNT", raising=False)
    conn = qmt.QmtConnector()
    assert conn.is_configured() is False
    with pytest.raises(GatewayNotConfigured):
        conn.submit_order(Order("600519.SH", OrderSide.BUY, 100))
    with pytest.raises(GatewayNotConfigured):
        conn.get_positions()


def test_ctp_connector_not_configured_without_sdk(monkeypatch):
    monkeypatch.delenv("QF_CTP_USER", raising=False)
    monkeypatch.delenv("QF_CTP_BROKER_ID", raising=False)
    monkeypatch.delenv("QF_CTP_TD_FRONT", raising=False)
    conn = ctp.CtpConnector()
    assert conn.is_configured() is False
    with pytest.raises(GatewayNotConfigured):
        conn.submit_order(Order("IF2409", OrderSide.BUY, 1, market="future"))


def test_registry_returns_connector_for_qmt_ctp():
    assert isinstance(get_live_connector({"broker": "qmt"}), qmt.QmtConnector)
    assert isinstance(get_live_connector({"broker": "ctp"}), ctp.CtpConnector)
    assert get_live_connector({"broker": "none"}) is None


def test_connector_status_reports_unrecognized_for_none():
    st = connector_status({"broker": "none"})
    assert st["connector"] is None
    assert st["configured"] is False


def test_live_gateway_delegates_to_connector_and_raises_when_not_configured(monkeypatch):
    monkeypatch.delenv("QF_QMT_ACCOUNT", raising=False)
    gw = LiveExecutionGateway()
    # broker 默认 none -> 连接器为 None -> 下单应 GatewayNotConfigured（无 api_key）
    with pytest.raises(GatewayNotConfigured):
        gw.submit_order(Order("600519.SH", OrderSide.BUY, 100))


def test_engine_live_capable_false_for_unconfigured():
    assert engine.live_capable() is False


def test_api_live_positions_returns_409_when_not_configured():
    r = client.get("/api/trading/live/positions")
    assert r.status_code == 409


def test_api_live_fills_returns_409_when_not_configured():
    r = client.get("/api/trading/live/fills")
    assert r.status_code == 409


def test_api_live_status_lists_missing_for_qmt(monkeypatch):
    # 用环境变量模拟 broker=qmt 但缺凭证
    monkeypatch.setenv("QF_BROKER", "qmt")
    monkeypatch.delenv("QF_QMT_ACCOUNT", raising=False)
    monkeypatch.delenv("QF_BROKER_API_KEY", raising=False)
    r = client.get("/api/trading/live/status")
    assert r.status_code == 200
    body = r.json()
    assert body["broker"] == "qmt"
    assert body["live_capable"] is False
    assert any("QF_QMT_ACCOUNT" in m for m in body["missing"])
