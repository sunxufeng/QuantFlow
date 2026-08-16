"""V101 监控告警推送：规则 CRUD / 评估触发通知 / 冷却 / API / 调度。"""

import pytest

from app.monitoring import monalert_service as msa
from app.notifications.service import notification_service


@pytest.fixture
def notify_spy(monkeypatch):
    calls = []

    def fake_notify(message):
        calls.append(message)
        return 1

    monkeypatch.setattr(notification_service, "notify", fake_notify)
    return calls


def _drift_breach_params():
    return {"weights": [0.8, 0.2], "target": [0.5, 0.5], "asset_names": ["A", "B"], "threshold": 0.05}


def _drift_ok_params():
    return {"weights": [0.5, 0.5], "target": [0.5, 0.5], "asset_names": ["A", "B"], "threshold": 0.05}


def test_create_and_list_rule():
    rule = msa.monitor_alert_service.create_rule(
        name="测试偏离", monitor_type="drift", params=_drift_breach_params()
    )
    assert rule["id"]
    assert rule["monitor_type"] == "drift"
    rules = msa.monitor_alert_service.list_rules()
    assert any(r["id"] == rule["id"] for r in rules)
    assert msa.monitor_alert_service.delete_rule(rule["id"])


def test_create_invalid_type():
    with pytest.raises(ValueError):
        msa.monitor_alert_service.create_rule(name="x", monitor_type="nope", params={})


def test_evaluate_triggers_notify(notify_spy):
    rule = msa.monitor_alert_service.create_rule(
        name="偏离告警", monitor_type="drift", params=_drift_breach_params(), cooldown_minutes=60
    )
    try:
        out = msa.monitor_alert_service.evaluate_all()
        assert len(out) == 1
        assert out[0]["triggered"] is True
        assert out[0]["notified"] is True
        assert len(notify_spy) == 1
        assert "监控告警" in notify_spy[0].title
    finally:
        msa.monitor_alert_service.delete_rule(rule["id"])


def test_evaluate_no_breach(notify_spy):
    rule = msa.monitor_alert_service.create_rule(
        name="无偏离", monitor_type="drift", params=_drift_ok_params(), cooldown_minutes=60
    )
    try:
        out = msa.monitor_alert_service.evaluate_all()
        assert out[0]["triggered"] is False
        assert out[0]["notified"] is False
        assert len(notify_spy) == 0
    finally:
        msa.monitor_alert_service.delete_rule(rule["id"])


def test_cooldown_suppresses_second_notify(notify_spy):
    rule = msa.monitor_alert_service.create_rule(
        name="冷却测试", monitor_type="drift", params=_drift_breach_params(), cooldown_minutes=60
    )
    try:
        msa.monitor_alert_service.evaluate_all()
        msa.monitor_alert_service.evaluate_all()
        # 冷却期内第二次不应再通知
        assert len(notify_spy) == 1
    finally:
        msa.monitor_alert_service.delete_rule(rule["id"])


def test_other_monitor_types_trigger():
    # 收益质量：构造低胜率序列触发 breach
    params = {"returns": [-0.01, -0.02, -0.03, 0.005, -0.01], "hit_rate_limit": 0.45, "payoff_ratio_limit": 0.8}
    rule = msa.monitor_alert_service.create_rule(name="质量", monitor_type="return_quality", params=params)
    try:
        out = msa.monitor_alert_service.evaluate_all()
        assert out[0]["triggered"] is True
    finally:
        msa.monitor_alert_service.delete_rule(rule["id"])


# ----------------------------- API 层 ----------------------------- #
def test_api_create_rule(client):
    r = client.post(
        "/api/monalert/rules",
        json={"name": "API偏离", "monitor_type": "drift", "params": _drift_breach_params()},
    )
    assert r.status_code == 201
    rid = r.json()["id"]
    lst = client.get("/api/monalert/rules")
    assert lst.status_code == 200
    assert any(x["id"] == rid for x in lst.json())
    assert client.delete(f"/api/monalert/rules/{rid}").status_code == 204


def test_api_create_rule_invalid(client):
    r = client.post(
        "/api/monalert/rules", json={"name": "x", "monitor_type": "bad", "params": {}}
    )
    assert r.status_code == 400


def test_api_evaluate(client):
    r = client.post("/api/monalert/evaluate")
    assert r.status_code == 200
    assert "evaluated" in r.json()


def test_api_scheduler_status(client):
    r = client.get("/api/monalert/scheduler")
    assert r.status_code == 200
    assert "running" in r.json()


def test_api_requires_auth(anon_client):
    assert anon_client.get("/api/monalert/rules").status_code == 401
    assert anon_client.post("/api/monalert/rules", json={"name": "x", "monitor_type": "drift", "params": {}}).status_code == 401
