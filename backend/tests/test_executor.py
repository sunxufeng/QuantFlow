"""执行引擎测试：线性 / 菱形并行 / 失败传播。"""

from app.core.dag import validate_workflow
from app.core.executor import NodeStatus, WorkflowExecutor

executor = WorkflowExecutor(max_workers=4)


def test_linear_chain():
    nodes = [
        {"id": "c", "node_type": "data.constant", "params": {"value": 10}},
        {"id": "a", "node_type": "math.add", "params": {}},
        {"id": "b", "node_type": "math.add", "params": {}},
    ]
    edges = [
        {"source": "c", "source_port": "value", "target": "a", "target_port": "a"},
        {"source": "c", "source_port": "value", "target": "a", "target_port": "b"},
        {"source": "a", "source_port": "result", "target": "b", "target_port": "a"},
        {"source": "c", "source_port": "value", "target": "b", "target_port": "b"},
    ]
    graph = validate_workflow(nodes, edges)
    result = executor.run(graph)
    assert result.status == "succeeded"
    assert result.node_states["c"].outputs["value"] == 10
    assert result.node_states["a"].outputs["result"] == 20  # 10 + 10
    assert result.node_states["b"].outputs["result"] == 30  # 20 + 10


def test_diamond_parallel():
    nodes = [
        {"id": "c", "node_type": "data.constant", "params": {"value": 2}},
        {"id": "a", "node_type": "math.add", "params": {}},
        {"id": "b", "node_type": "math.add", "params": {}},
        {"id": "out", "node_type": "math.multiply", "params": {"scale": 10}},
    ]
    edges = [
        {"source": "c", "source_port": "value", "target": "a", "target_port": "a"},
        {"source": "c", "source_port": "value", "target": "a", "target_port": "b"},
        {"source": "c", "source_port": "value", "target": "b", "target_port": "a"},
        {"source": "c", "source_port": "value", "target": "b", "target_port": "b"},
        {"source": "a", "source_port": "result", "target": "out", "target_port": "a"},
        {"source": "b", "source_port": "result", "target": "out", "target_port": "b"},
    ]
    result = executor.run(validate_workflow(nodes, edges))
    assert result.status == "succeeded"
    # out = (2+2) * (2+2) * 10
    assert result.node_states["out"].outputs["result"] == 160


def test_array_pipeline():
    nodes = [
        {"id": "seq", "node_type": "data.sequence", "params": {"start": 1, "end": 6}},
        {"id": "sum", "node_type": "math.sum_array", "params": {}},
        {"id": "avg", "node_type": "math.mean_array", "params": {}},
    ]
    edges = [
        {"source": "seq", "source_port": "values", "target": "sum", "target_port": "values"},
        {"source": "seq", "source_port": "values", "target": "avg", "target_port": "values"},
    ]
    result = executor.run(validate_workflow(nodes, edges))
    assert result.status == "succeeded"
    assert result.node_states["sum"].outputs["sum"] == 15
    assert result.node_states["avg"].outputs["mean"] == 3.0


def test_failure_propagates_to_downstream_only():
    # 失败节点（输入 a 缺失 required → 校验失败）下游被 BLOCKED，兄弟分支不受影响
    nodes = [
        {"id": "bad", "node_type": "math.add", "params": {}},   # 输入 a 缺失（required）→ 失败
        {"id": "dep", "node_type": "math.add", "params": {}},   # bad 的下游 → blocked
        {"id": "ok", "node_type": "data.constant", "params": {"value": 7}},
    ]
    edges = [
        {"source": "bad", "source_port": "result", "target": "dep", "target_port": "a"},
    ]
    result = executor.run(validate_workflow(nodes, edges))
    assert result.status == "failed"
    assert result.node_states["bad"].status == NodeStatus.FAILED
    assert result.node_states["dep"].status == NodeStatus.BLOCKED
    assert result.node_states["ok"].status == NodeStatus.SUCCEEDED  # 独立分支继续


def test_run_result_serializable():
    nodes = [{"id": "c", "node_type": "data.constant", "params": {"value": 3.0}}]
    result = executor.run(validate_workflow(nodes, []))
    payload = result.to_dict()
    assert payload["status"] == "succeeded"
    assert payload["nodes"][0]["outputs"]["value"] == 3.0
    assert "duration_ms" in payload
