"""V1.2 定时调度测试。

覆盖：计划 CRUD、cron/interval 校验、run_now 触发执行、启用停用、API 鉴权。
"""

import pytest

from app.core.scheduler import ScheduleValidationError, workflow_scheduler

_SAMPLE_PAYLOAD = {
    "nodes": [{"id": "c", "node_type": "data.constant", "params": {"value": 7}}],
    "edges": [],
    "workflow_name": "scheduled_demo",
}


def test_create_and_list_schedule():
    rec = workflow_scheduler.create_schedule(
        name="daily", trigger_type="cron",
        trigger_cfg="0 9 * * 1-5", payload=_SAMPLE_PAYLOAD,
    )
    assert rec["id"].startswith("sch_")
    assert rec["enabled"] is True
    assert any(s["id"] == rec["id"] for s in workflow_scheduler.list_schedules())


def test_invalid_cron_rejected():
    with pytest.raises(ScheduleValidationError):
        workflow_scheduler.create_schedule(
            name="bad", trigger_type="cron",
            trigger_cfg="not a cron", payload=_SAMPLE_PAYLOAD,
        )


def test_invalid_interval_rejected():
    with pytest.raises(ScheduleValidationError):
        workflow_scheduler.create_schedule(
            name="bad", trigger_type="interval",
            trigger_cfg='{"minutes": 0}', payload=_SAMPLE_PAYLOAD,
        )


def test_run_now_triggers_execution():
    rec = workflow_scheduler.create_schedule(
        name="now", trigger_type="cron",
        trigger_cfg="0 0 31 12 *", payload=_SAMPLE_PAYLOAD,
    )
    result = workflow_scheduler.run_now(rec["id"])
    assert result["status"] == "submitted"
    assert result["run_id"]
    updated = workflow_scheduler.get_schedule(rec["id"])
    assert updated["last_run_status"] == "submitted"
    assert updated["last_run_id"] == result["run_id"]


def test_toggle_and_delete():
    rec = workflow_scheduler.create_schedule(
        name="tg", trigger_type="interval",
        trigger_cfg='{"minutes": 60}', payload=_SAMPLE_PAYLOAD,
    )
    disabled = workflow_scheduler.set_enabled(rec["id"], False)
    assert disabled["enabled"] is False
    workflow_scheduler.remove_schedule(rec["id"])
    assert workflow_scheduler.get_schedule(rec["id"]) is None


# ---- API 层 ----
def test_api_requires_auth(client):
    code = client.post("/api/schedules", json={})
    assert code.status_code == 401


def test_api_crud_and_run(auth_client):
    # create
    resp = auth_client.post(
        "/api/schedules",
        json={"name": "api_demo", "trigger_type": "cron",
              "trigger_cfg": "0 0 31 12 *", "payload": _SAMPLE_PAYLOAD},
    )
    assert resp.status_code == 201
    sid = resp.json()["id"]
    # list
    lst = auth_client.get("/api/schedules").json()
    assert any(s["id"] == sid for s in lst)
    # run now
    r = auth_client.post(f"/api/schedules/{sid}/run").json()
    assert r["status"] == "submitted"
    # toggle off
    t = auth_client.post(f"/api/schedules/{sid}/toggle", json={"enabled": False}).json()
    assert t["enabled"] is False
    # delete
    d = auth_client.delete(f"/api/schedules/{sid}")
    assert d.status_code == 204


def test_api_create_invalid(auth_client):
    resp = auth_client.post(
        "/api/schedules",
        json={"name": "x", "trigger_type": "cron",
              "trigger_cfg": "bad", "payload": _SAMPLE_PAYLOAD},
    )
    assert resp.status_code == 400
