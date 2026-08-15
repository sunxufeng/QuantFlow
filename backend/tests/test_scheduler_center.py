"""V5.2 调度中心总览端点。"""

from __future__ import annotations


def test_schedules_center_requires_auth(anon_client) -> None:
    r = anon_client.get("/api/schedules/center")
    assert r.status_code == 401


def test_schedules_center_shape(client) -> None:
    r = client.get("/api/schedules/center")
    assert r.status_code == 200, r.text
    data = r.json()
    assert "workflow_schedules" in data
    assert "data_sync" in data
    assert "alert_eval" in data
    assert isinstance(data["workflow_schedules"], list)
    # 系统自动任务状态字段存在
    assert "status" in data["data_sync"]
    assert "running" in data["alert_eval"]
