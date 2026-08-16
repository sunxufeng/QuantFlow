"""V102 定时报告自动投递：deliver_report / 任务 CRUD / run / API。"""

import pytest

from app.notifications.service import notification_service
from app.reports import delivery as dv


@pytest.fixture
def notify_spy(monkeypatch):
    calls = []

    def fake_notify(message):
        calls.append(message)
        return 1

    monkeypatch.setattr(notification_service, "notify", fake_notify)
    return calls


def _ret(n=30):
    import math
    return [round(0.001 + 0.01 * math.sin(i), 5) for i in range(n)]


def test_deliver_performance(notify_spy):
    out = dv.deliver_report("performance", {"returns": _ret()})
    assert out["sent"] == 1
    assert out["metric_count"] > 0
    assert len(notify_spy) == 1
    assert "量化报告投递" in notify_spy[0].title


def test_deliver_risk(notify_spy):
    out = dv.deliver_report("risk", {"returns": _ret(), "weights": {"A": 0.6, "B": 0.4}})
    assert out["sent"] == 1


def test_deliver_periodic(notify_spy):
    dates = [f"2024-01-{i:02d}" for i in range(1, 31)]
    out = dv.deliver_report("periodic", {"returns": _ret(30), "dates": dates, "freq": "W"})
    assert out["sent"] == 1


def test_deliver_consolidate(notify_spy):
    out = dv.deliver_report("consolidate", {"returns": _ret()})
    assert out["sent"] == 1


def test_deliver_invalid_type():
    with pytest.raises(ValueError):
        dv.deliver_report("nope", {"returns": _ret()})


def test_deliver_requires_returns():
    with pytest.raises((ValueError, TypeError)):
        dv.deliver_report("performance", {})


def test_job_crud_and_run(notify_spy):
    job = dv.delivery_service.create_job(
        name="每日绩效", report_type="performance", params={"returns": _ret()}, interval_minutes=60
    )
    assert job["id"]
    assert any(j["id"] == job["id"] for j in dv.delivery_service.list_jobs())
    res = dv.delivery_service.run_job(job["id"])
    assert res["status"] == "delivered"
    assert res["sent"] == 1
    assert dv.delivery_service.set_enabled(job["id"], False) is True
    assert dv.delivery_service.delete_job(job["id"]) is True
    assert dv.delivery_service.get_job(job["id"]) is None


def test_run_all_empty():
    assert dv.delivery_service.run_all() == []


# ----------------------------- API 层 ----------------------------- #
def test_api_deliver(client):
    r = client.post("/api/reports/deliver", json={"report_type": "performance", "params": {"returns": _ret()}})
    assert r.status_code == 200
    assert r.json()["sent"] >= 0


def test_api_deliver_invalid(client):
    r = client.post("/api/reports/deliver", json={"report_type": "bad", "params": {}})
    assert r.status_code == 400


def test_api_job_lifecycle(client):
    c = client.post("/api/reports/delivery-jobs", json={
        "name": "任务", "report_type": "performance", "params": {"returns": _ret()}, "interval_minutes": 60,
    })
    assert c.status_code == 201
    jid = c.json()["id"]
    assert client.get("/api/reports/delivery-jobs").status_code == 200
    assert client.post(f"/api/reports/delivery-jobs/{jid}/run").status_code == 200
    assert client.post(f"/api/reports/delivery-jobs/{jid}/toggle", json={"enabled": False}).status_code == 200
    assert client.delete(f"/api/reports/delivery-jobs/{jid}").status_code == 204


def test_api_scheduler_status(client):
    assert client.get("/api/reports/delivery/scheduler").status_code == 200


def test_api_requires_auth(anon_client):
    assert anon_client.get("/api/reports/delivery-jobs").status_code == 401
    assert anon_client.post("/api/reports/deliver", json={"report_type": "performance", "params": {}}).status_code == 401
