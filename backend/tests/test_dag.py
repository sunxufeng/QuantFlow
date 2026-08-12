"""DAG 构建测试：拓扑 / 环检测 / 端口校验。"""

import pytest

from app.core.dag import WorkflowValidationError, validate_workflow


def _nodes(*types):
    return [{"id": f"n{i}", "node_type": t, "params": {}} for i, t in enumerate(types)]


def test_linear_topo():
    nodes = _nodes("data.constant", "math.add", "math.add")
    edges = [
        {"id": "e1", "source": "n0", "source_port": "value", "target": "n1", "target_port": "a"},
        {"id": "e2", "source": "n1", "source_port": "result", "target": "n2", "target_port": "a"},
    ]
    graph = validate_workflow(nodes, edges)
    assert graph.topo_order() == ["n0", "n1", "n2"]


def test_diamond_topo():
    nodes = _nodes("data.constant", "math.add", "math.add", "math.add")
    edges = [
        {"source": "n0", "source_port": "value", "target": "n1", "target_port": "a"},
        {"source": "n0", "source_port": "value", "target": "n2", "target_port": "a"},
        {"source": "n1", "source_port": "result", "target": "n3", "target_port": "a"},
        {"source": "n2", "source_port": "result", "target": "n3", "target_port": "b"},
    ]
    graph = validate_workflow(nodes, edges)
    order = graph.topo_order()
    assert order.index("n0") < order.index("n1") < order.index("n3")
    assert order.index("n0") < order.index("n2") < order.index("n3")


def test_cycle_detected():
    nodes = _nodes("math.add", "math.add")
    edges = [
        {"source": "n0", "source_port": "result", "target": "n1", "target_port": "a"},
        {"source": "n1", "source_port": "result", "target": "n0", "target_port": "a"},
    ]
    with pytest.raises(WorkflowValidationError, match="环"):
        validate_workflow(nodes, edges)


def test_self_loop_rejected():
    nodes = _nodes("math.add")
    edges = [{"source": "n0", "source_port": "result", "target": "n0", "target_port": "a"}]
    with pytest.raises(WorkflowValidationError, match="自环"):
        validate_workflow(nodes, edges)


def test_unknown_type_rejected():
    with pytest.raises(WorkflowValidationError, match="未注册类型"):
        validate_workflow([{"id": "n0", "node_type": "bad.type", "params": {}}], [])


def test_bad_port_rejected():
    nodes = _nodes("math.add", "math.add")
    edges = [{"source": "n0", "source_port": "nope", "target": "n1", "target_port": "a"}]
    with pytest.raises(WorkflowValidationError, match="无输出端口"):
        validate_workflow(nodes, edges)


def test_duplicate_node_id_rejected():
    with pytest.raises(WorkflowValidationError, match="重复"):
        validate_workflow(
            [{"id": "n0", "node_type": "math.add", "params": {}}] * 2, []
        )


def test_incompatible_type_rejected():
    # table 端口不能接入 number 端口
    nodes = _nodes("data.demo_table", "math.add")
    edges = [{"source": "n0", "source_port": "table", "target": "n1", "target_port": "a"}]
    with pytest.raises(WorkflowValidationError, match="类型不兼容"):
        validate_workflow(nodes, edges)


def test_single_source_per_input():
    nodes = _nodes("math.add", "data.constant", "data.constant")
    edges = [
        {"source": "n1", "source_port": "value", "target": "n0", "target_port": "a"},
        {"source": "n2", "source_port": "value", "target": "n0", "target_port": "a"},
    ]
    with pytest.raises(WorkflowValidationError, match="单一来源"):
        validate_workflow(nodes, edges)
