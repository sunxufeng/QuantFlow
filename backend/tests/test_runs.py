"""M2 执行引擎增强测试：事件总线、DataBridge、运行实例持久化与查询。"""

from __future__ import annotations

import threading

import pytest

from app.core.dag import validate_workflow
from app.core.databridge import DataBridge, make_preview
from app.core.events import EVENT_BUS, NODE_SUCCEEDED, EventBus, RunEvent
from app.core.executor import WorkflowExecutor
from app.core.runs import RunCapacityError, RunRepository, RunService
from app.core.data import DataTable


# --------------------------------------------------------------------------- #
# 事件总线
# --------------------------------------------------------------------------- #
class TestEventBus:
    def test_subscribe_and_publish(self):
        got = []
        unsub = EVENT_BUS.subscribe(got.append)
        try:
            EVENT_BUS.publish(RunEvent(run_id="r1", kind="run_started"))
            assert len(got) == 1
            assert got[0].run_id == "r1"
        finally:
            unsub()

    def test_unsubscribe(self):
        got = []
        unsub = EVENT_BUS.subscribe(got.append)
        unsub()
        EVENT_BUS.publish(RunEvent(run_id="r1", kind="run_started"))
        assert got == []

    def test_bad_subscriber_does_not_break(self):
        def bad(event):
            raise RuntimeError("boom")

        got = []
        b1 = EVENT_BUS.subscribe(bad)
        b2 = EVENT_BUS.subscribe(got.append)
        try:
            EVENT_BUS.publish(RunEvent(run_id="r1", kind="run_started"))
            assert len(got) == 1
        finally:
            b1()
            b2()


# --------------------------------------------------------------------------- #
# DataBridge
# --------------------------------------------------------------------------- #
class TestDataBridge:
    def test_capture_preview_table(self):
        bridge = DataBridge()
        table = DataTable(columns=["a", "b"], rows=[{"a": i, "b": i * 2} for i in range(20)])
        rec = bridge.capture("r1", "n1", {"table": table, "value": 3})
        assert rec["storage"] == "memory"
        assert rec["preview"]["value"] == 3
        prev = rec["preview"]["table"]
        assert prev["type"] == "table"
        assert prev["total_rows"] == 20
        assert len(prev["rows"]) == 10  # 截断预览

    def test_capture_read_roundtrip(self):
        bridge = DataBridge()
        bridge.capture("r1", "n1", {"value": 42})
        assert bridge.read("r1", "n1")["value"] == 42
        assert bridge.read("r1", "missing") == {}

    def test_large_output_spills_to_disk(self, tmp_path):
        bridge = DataBridge(data_dir=str(tmp_path), spill_threshold=100)
        big = {"data": list(range(1000))}
        rec = bridge.capture("r1", "n1", big)
        assert rec["storage"] == "disk"
        assert rec["path"]
        assert bridge.read("r1", "n1") == big

    def test_make_preview_array(self):
        p = make_preview(list(range(20)))
        assert p["type"] == "array"
        assert p["length"] == 20
        assert len(p["preview"]) == 10


# --------------------------------------------------------------------------- #
# 执行器事件发布
# --------------------------------------------------------------------------- #
class TestExecutorEvents:
    def test_executor_publishes_node_events(self):
        events = []
        unsub = EVENT_BUS.subscribe(events.append)
        try:
            ex = WorkflowExecutor(max_workers=2, event_bus=EVENT_BUS)
            graph = validate_workflow(
                [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}],
                [],
            )
            result = ex.run(graph, run_id="evt_run")
            assert result.status == "succeeded"
            kinds = [e.kind for e in events if e.run_id == "evt_run"]
            assert NODE_SUCCEEDED in kinds
            assert all(e.run_id == "evt_run" for e in events)
        finally:
            unsub()


# --------------------------------------------------------------------------- #
# RunService：持久化与查询
# --------------------------------------------------------------------------- #
class TestRunService:
    def _service(self, tmp_path):
        repo = RunRepository()
        bridge = DataBridge(data_dir=str(tmp_path))
        service = RunService(repository=repo, bridge=bridge)
        return service, repo

    def test_submit_and_wait(self, tmp_path):
        service, repo = self._service(tmp_path)
        resp = service.submit(
            [{"id": "c", "node_type": "data.constant", "params": {"value": 5}}],
            [],
            workflow_name="简单运行",
        )
        assert resp["status"] == "running"
        assert resp["run_id"]
        record = service.wait(resp["run_id"], timeout=10)
        assert record["status"] == "succeeded"
        assert record["workflow_name"] == "简单运行"
        assert record["finished_at"] is not None
        # 结果只带预览（无全量 outputs）
        result = record["result"]
        assert result["status"] == "succeeded"
        assert result["nodes"][0]["outputs"]["value"] == 5  # 标量预览即值

    def test_node_states_recorded(self, tmp_path):
        service, repo = self._service(tmp_path)
        resp = service.submit(
            [{"id": "c", "node_type": "data.constant", "params": {"value": 5}}],
            [],
        )
        record = service.wait(resp["run_id"], timeout=10)
        node = record["nodes"]["c"]
        assert node["status"] == "succeeded"

    def test_list_filters_by_workflow(self, tmp_path):
        service, repo = self._service(tmp_path)
        service.submit(
            [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}],
            [],
            workflow_id="wf_a",
        )
        service.submit(
            [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}],
            [],
            workflow_id="wf_b",
        )
        items = service.list()
        assert len(items) == 2
        items_a = service.list(workflow_id="wf_a")
        assert len(items_a) == 1
        assert all(i["workflow_id"] == "wf_a" for i in items_a)

    def test_failed_run_persisted(self, tmp_path):
        service, repo = self._service(tmp_path)
        resp = service.submit(
            [{"id": "bad", "node_type": "math.add", "params": {}}],
            [],
        )
        record = service.wait(resp["run_id"], timeout=10)
        assert record["status"] == "failed"
        assert record["nodes"]["bad"]["status"] == "failed"

    def test_execute_sync_returns_full_outputs(self, tmp_path):
        service, repo = self._service(tmp_path)
        result = service.execute_sync(
            [{"id": "c", "node_type": "data.constant", "params": {"value": 5}}],
            [],
        )
        assert result.to_dict()["nodes"][0]["outputs"]["value"] == 5
        # 也持久化了
        assert repo.get(result.run_id)["status"] == "succeeded"

    def test_get_missing_raises(self, tmp_path):
        service, repo = self._service(tmp_path)
        from app.core.runs import RunNotFoundError

        with pytest.raises(RunNotFoundError):
            service.get("missing_run")

    def test_twenty_runs_execute_concurrently_without_state_leaks(self, tmp_path):
        barrier = threading.Barrier(20, timeout=10)
        bus = EventBus()
        bridge = DataBridge(data_dir=str(tmp_path))

        class BarrierExecutor(WorkflowExecutor):
            def run(self, graph, run_id=None):
                barrier.wait()
                return super().run(graph, run_id=run_id)

        executor = BarrierExecutor(max_workers=1, event_bus=bus, bridge=bridge)
        service = RunService(
            executor=executor,
            repository=RunRepository(),
            bridge=bridge,
            bus=bus,
            run_workers=20,
            queue_size=0,
        )

        submissions = [
            service.submit(
                [{"id": "c", "node_type": "data.constant", "params": {"value": value}}],
                [],
                workflow_name=f"run-{value}",
            )
            for value in range(20)
        ]
        run_ids = [item["run_id"] for item in submissions]
        assert len(set(run_ids)) == 20

        records = [service.wait(run_id, timeout=10) for run_id in run_ids]
        assert all(record["status"] == "succeeded" for record in records)
        for value, record in enumerate(records):
            assert record["workflow_name"] == f"run-{value}"
            assert record["nodes"]["c"]["outputs"]["value"] == value
            assert bridge.read(record["run_id"], "c")["value"] == value

    def test_submit_rejects_when_run_capacity_is_full(self, tmp_path):
        release = threading.Event()
        started = threading.Event()
        bus = EventBus()
        bridge = DataBridge(data_dir=str(tmp_path))

        class BlockingExecutor(WorkflowExecutor):
            def run(self, graph, run_id=None):
                started.set()
                release.wait(timeout=10)
                return super().run(graph, run_id=run_id)

        service = RunService(
            executor=BlockingExecutor(max_workers=1, event_bus=bus, bridge=bridge),
            repository=RunRepository(),
            bridge=bridge,
            bus=bus,
            run_workers=1,
            queue_size=0,
        )
        first = service.submit(
            [{"id": "c", "node_type": "data.constant", "params": {"value": 1}}],
            [],
        )
        assert started.wait(timeout=2)
        try:
            with pytest.raises(RunCapacityError):
                service.submit(
                    [{"id": "c", "node_type": "data.constant", "params": {"value": 2}}],
                    [],
                )
        finally:
            release.set()
        assert service.wait(first["run_id"], timeout=10)["status"] == "succeeded"
