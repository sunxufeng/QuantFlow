"""内置示例节点（M1 原型）。

覆盖四种端口类型的最小集合，验证插件框架 + DAG 引擎闭环。
量化节点库（行情/特征/ML/因子/回测）在 M3 节点库阶段实现。
"""

from typing import Any, Dict

from ..core.data import DataTable
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node


# --------------------------------------------------------------------------- #
# 常量 / 输入
# --------------------------------------------------------------------------- #
@work_node(
    "data.constant",
    label="常量",
    category="数据",
    description="输出一个固定数值",
    outputs=[PortSpec("value", "number")],
    params=[ParamSpec("value", "number", default=1.0, label="值", required=True)],
)
class ConstantNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        return {"value": self.params["value"]}


@work_node(
    "data.sequence",
    label="数列",
    category="数据",
    description="生成 [start, end) 步长 step 的等差数列",
    outputs=[PortSpec("values", "array")],
    params=[
        ParamSpec("start", "number", default=1.0, label="起始"),
        ParamSpec("end", "number", default=10.0, label="结束"),
        ParamSpec("step", "number", default=1.0, label="步长"),
    ],
)
class SequenceNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        import math

        start, end, step = self.params["start"], self.params["end"], self.params["step"]
        values = []
        v = start
        guard = 0
        while v < end and guard < 100000:
            values.append(round(v, 6))
            v += step
            guard += 1
        return {"values": values}


@work_node(
    "data.demo_table",
    label="示例表格",
    category="数据",
    description="生成一张示例表格（数据传递演示）",
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("rows", "number", default=5, label="行数"),
        ParamSpec("seed", "number", default=42, label="随机种子"),
    ],
)
class DemoTableNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        rows = int(self.params["rows"])
        seed = int(self.params["seed"])
        rng = _rng(seed)
        data = []
        for i in range(rows):
            data.append({
                "date": f"2026-08-{(i % 28) + 1:02d}",
                "close": round(100 + rng() * 20, 2),
                "volume": int(rng() * 100000),
            })
        return {"table": DataTable(columns=["date", "close", "volume"], rows=data)}


# --------------------------------------------------------------------------- #
# 数学
# --------------------------------------------------------------------------- #
@work_node(
    "math.add",
    label="加法",
    category="数学",
    description="a + b",
    inputs=[PortSpec("a", "number"), PortSpec("b", "number")],
    outputs=[PortSpec("result", "number")],
)
class AddNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        return {"result": inputs["a"] + inputs["b"]}


@work_node(
    "math.multiply",
    label="乘法",
    category="数学",
    description="a * b * scale",
    inputs=[PortSpec("a", "number"), PortSpec("b", "number")],
    outputs=[PortSpec("result", "number")],
    params=[ParamSpec("scale", "number", default=1.0, label="系数")],
)
class MultiplyNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        return {"result": inputs["a"] * inputs["b"] * self.params["scale"]}


@work_node(
    "math.sum_array",
    label="数组求和",
    category="数学",
    description="对数组求和",
    inputs=[PortSpec("values", "array")],
    outputs=[PortSpec("sum", "number")],
)
class SumArrayNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        values = inputs["values"] or []
        return {"sum": sum(values)}


@work_node(
    "math.mean_array",
    label="数组均值",
    category="数学",
    description="对数组求均值（空数组返回 0）",
    inputs=[PortSpec("values", "array")],
    outputs=[PortSpec("mean", "number")],
)
class MeanArrayNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        values = inputs["values"] or []
        return {"mean": sum(values) / len(values) if values else 0.0}


# --------------------------------------------------------------------------- #
# 表格
# --------------------------------------------------------------------------- #
@work_node(
    "table.head",
    label="表格取前 N 行",
    category="表格",
    description="截取表格前 N 行",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[ParamSpec("n", "number", default=3, label="行数")],
)
class HeadNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        table: DataTable = inputs["table"]
        return {"table": table.head(int(self.params["n"]))}


# --------------------------------------------------------------------------- #
# 辅助
# --------------------------------------------------------------------------- #
def _rng(seed: int):
    """确定性伪随机（无第三方依赖）。"""
    state = (seed * 9301 + 49297) % 233280

    def _next() -> float:
        nonlocal state
        state = (state * 9301 + 49297) % 233280
        return state / 233280

    return _next
