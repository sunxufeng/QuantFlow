"""节点框架测试：注册 / 规格 / 实例化 / 执行。"""

import pytest

from app.core.node import NodeConfigError, instantiate_node
from app.core.registry import REGISTRY


def test_registry_has_builtin_nodes():
    assert REGISTRY.has("math.add")
    assert REGISTRY.has("data.constant")
    assert REGISTRY.has("data.demo_table")


def test_specs_shape():
    specs = REGISTRY.specs()
    assert specs, "节点库为空"
    one = next(s for s in specs if s["node_type"] == "math.add")
    assert one["inputs"] and one["outputs"]
    assert one["inputs"][0]["name"] == "a"
    assert one["inputs"][0]["type"] == "number"


def test_add_node_execute():
    node = instantiate_node("math.add", "n1")
    from app.core.node import WorkNodeContext

    ctx = WorkNodeContext(run_id="r1", node_id="n1")
    out = node.execute(ctx, {"a": 1, "b": 2})
    assert out == {"result": 3}


def test_param_resolution_default():
    node = instantiate_node("math.multiply", "n1", {"a": 2, "b": 3})
    assert node.params["scale"] == 1.0
    node2 = instantiate_node("math.multiply", "n2", {"a": 2, "b": 3, "scale": 5})
    assert node2.params["scale"] == 5


def test_required_param_missing():
    from app.core.node import WorkNodeContext

    with pytest.raises(NodeConfigError):
        instantiate_node("data.constant", "n1", {})  # value 必填


def test_number_coercion():
    node = instantiate_node("data.constant", "n1", {"value": "3.5"})
    assert node.params["value"] == 3.5


def test_unknown_node_type():
    with pytest.raises(KeyError):
        instantiate_node("no.such.node", "n1")


def test_table_head():
    from app.core.data import DataTable
    from app.core.node import WorkNodeContext

    node = instantiate_node("table.head", "n1", {"n": 2})
    ctx = WorkNodeContext(run_id="r1", node_id="n1")
    table = DataTable(["x"], [{"x": i} for i in range(5)])
    out = node.execute(ctx, {"table": table})
    assert len(out["table"]) == 2
