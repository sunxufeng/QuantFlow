"""V6.0 模拟交易账户：可配置初始资金（纯本地、持久化）。

验证：
- GET /trading/account 默认初始资金 1,000,000；
- DELETE /trading/reset 带 initial_cash 可将账户重置为自定义初始资金并持久化；
- summary.initial_cash 与账户初始资金一致（权益曲线基线随之变化）。
"""

from __future__ import annotations


def test_trading_account_default_initial_cash(client):
    r = client.get("/api/trading/account")
    assert r.status_code == 200
    data = r.json()
    assert data["initial_cash"] == 1_000_000
    assert data["cash"] == 1_000_000
    assert data["equity"] == 1_000_000
    assert data["position_count"] == 0


def test_trading_account_reset_requires_auth(anon_client):
    r = anon_client.request("DELETE", "/api/trading/reset")
    assert r.status_code == 401


def test_trading_reset_to_custom_initial_cash(client):
    # 将账户重置为 500,000
    r = client.request("DELETE", "/api/trading/reset", json={"initial_cash": 500_000})
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["initial_cash"] == 500_000

    # 账户概览反映自定义初始资金
    acct = client.get("/api/trading/account").json()
    assert acct["initial_cash"] == 500_000
    assert acct["cash"] == 500_000
    assert acct["equity"] == 500_000

    # summary 中的初始资金基线一致（权益曲线从 500,000 开始）
    summ = client.get("/api/trading/summary").json()
    assert summ["initial_cash"] == 500_000
    assert summ["equity"] == 500_000


def test_trading_reset_keeps_initial_cash_when_omitted(client):
    # 先自定义为 250,000
    client.request("DELETE", "/api/trading/reset", json={"initial_cash": 250_000})
    acct = client.get("/api/trading/account").json()
    assert acct["initial_cash"] == 250_000

    # 不带 initial_cash 重置：保持既有初始资金，仅清空现金/持仓
    r = client.request("DELETE", "/api/trading/reset")
    assert r.status_code == 200
    assert r.json()["initial_cash"] == 250_000
    acct2 = client.get("/api/trading/account").json()
    assert acct2["initial_cash"] == 250_000
    assert acct2["cash"] == 250_000


def test_trading_reset_invalid_initial_cash(client):
    # 负数/非正数应被后端拒绝
    r = client.request("DELETE", "/api/trading/reset", json={"initial_cash": -100})
    assert r.status_code in (400, 422)
