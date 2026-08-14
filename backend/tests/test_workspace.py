"""V7.0 投研工作区总览快照。

验证：
- GET /api/workspace 需登录（匿名 401）；
- 登录后返回 trading / alerts / watchlist / scheduler / factors 五个分区；
- 每个分区为对象或 None（best-effort，单分区异常不影响整体）。
"""

from __future__ import annotations


def test_workspace_requires_auth(anon_client):
    assert anon_client.get("/api/workspace").status_code == 401


def test_workspace_shape(client):
    r = client.get("/api/workspace")
    assert r.status_code == 200
    data = r.json()
    for key in ("trading", "alerts", "watchlist", "scheduler", "factors"):
        assert key in data
        section = data[key]
        # best-effort：允许为 None（异常时），但存在时必须是 dict
        assert section is None or isinstance(section, dict)

    # 账户快照（如存在）字段形态
    t = data["trading"]
    if t is not None:
        for f in ("equity", "cash", "market_value", "realized_pnl", "position_count", "open_orders", "initial_cash"):
            assert f in t

    # 调度状态（如存在）字段形态
    sc = data["scheduler"]
    if sc is not None:
        assert "data_sync" in sc and "alert_eval" in sc
