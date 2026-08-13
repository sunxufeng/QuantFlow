"""节点抽象层：BaseWorkNode + @work_node 装饰器。

对标 panda_quantflow 的核心抽象：
- BaseWorkNode 定义节点生命周期（配置校验 -> 执行 -> 产出）
- @work_node 声明式注册节点类型（type / 端口 / 参数 / 分类），装饰即注册
- 执行上下文 WorkNodeContext 携带 run_id，供日志/埋点/WebSocket 状态推送复用
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Union

from .registry import REGISTRY


# --------------------------------------------------------------------------- #
# 异常定义
# --------------------------------------------------------------------------- #
class NodeConfigError(Exception):
    """节点参数配置错误（工作流校验阶段抛出）。"""


class NodeExecutionError(Exception):
    """节点执行期错误，携带节点 id 便于失败定位。"""

    def __init__(self, node_id: str, message: str, cause: Optional[BaseException] = None):
        self.node_id = node_id
        self.message = message
        super().__init__(f"[node={node_id}] {message}")


class WorkflowValidationError(Exception):
    """工作流图校验错误（拓扑 / 端口 / 类型不匹配）。"""


# --------------------------------------------------------------------------- #
# 类型系统（V1.0 演进：number/string/boolean/array/table，
# 后续补充 datetime/index 等量化专用类型）
# --------------------------------------------------------------------------- #
class PortType:
    NUMBER = "number"
    STRING = "string"
    BOOLEAN = "boolean"
    ARRAY = "array"
    TABLE = "table"

    ALL = {NUMBER, STRING, BOOLEAN, ARRAY, TABLE}


@dataclass
class PortSpec:
    """节点输入/输出端口规格。"""

    name: str
    type: str = PortType.NUMBER
    required: bool = True
    label: str = ""
    description: str = ""

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "required": self.required,
            "label": self.label or self.name,
            "description": self.description,
        }


@dataclass
class ParamSpec:
    """节点可配置参数规格（前端据此渲染表单，M3 自动表单阶段完善）。"""

    name: str
    type: str = PortType.NUMBER
    default: Any = None
    required: bool = False
    label: str = ""
    description: str = ""
    options: Optional[List[str]] = None  # 枚举类参数候选值

    def to_dict(self) -> dict:
        return {
            "name": self.name,
            "type": self.type,
            "default": self.default,
            "required": self.required,
            "label": self.label or self.name,
            "description": self.description,
            "options": self.options,
        }


@dataclass
class WorkNodeContext:
    """节点执行上下文：run_id / node_id / 结构化日志接口。

    V1.0 演进：context.log 落结构化日志 + 推送运行状态到 WebSocket。
    """

    run_id: str
    node_id: str
    logger: Any = field(default=None)

    def log(self, level: str, message: str, **kwargs) -> None:
        if self.logger is not None:
            self.logger.info(f"[run={self.run_id}] [{level}] {message}", extra=kwargs)


# --------------------------------------------------------------------------- #
# 基类
# --------------------------------------------------------------------------- #
class BaseWorkNode(ABC):
    """所有工作流节点必须继承的基类。

    类属性（由 @work_node 装饰器注入或子类直接声明）：
        node_type    唯一类型标识（注册键）
        label        面板展示名
        category     分组
        description  说明
        version      节点版本
        input_ports  输入端口（PortSpec 列表）
        output_ports 输出端口（PortSpec 列表）
        param_schema 参数规格（ParamSpec 列表）
    """

    node_type: str = ""
    label: str = ""
    category: str = "通用"
    description: str = ""
    version: str = "1.0.0"
    input_ports: List[PortSpec] = []
    output_ports: List[PortSpec] = []
    param_schema: List[ParamSpec] = []

    def __init__(self, node_id: str, params: Optional[Dict[str, Any]] = None):
        self.node_id = node_id
        self.params: Dict[str, Any] = self._resolve_params(params or {})

    # ------------------------------------------------------------------ #
    # 子类必须实现
    # ------------------------------------------------------------------ #
    @abstractmethod
    def execute(self, ctx: WorkNodeContext, inputs: Dict[str, Any]) -> Dict[str, Any]:
        """执行节点。

        :param ctx:    执行上下文（run_id 等）
        :param inputs: 上游节点传入的输入值 {端口名: 值}
        :return:       输出值 {端口名: 值}
        """

    # ------------------------------------------------------------------ #
    # 通用流程
    # ------------------------------------------------------------------ #
    def _resolve_params(self, raw: Dict[str, Any]) -> Dict[str, Any]:
        resolved: Dict[str, Any] = {}
        for spec in self.param_schema:
            if spec.name in raw and raw[spec.name] is not None:
                resolved[spec.name] = self._coerce(spec, raw[spec.name])
            elif spec.required:
                raise NodeConfigError(f"节点 {self.node_type} 缺少必填参数: {spec.name}")
            elif spec.default is not None:
                resolved[spec.name] = spec.default
            else:
                resolved[spec.name] = None
        return resolved

    @staticmethod
    def _coerce(spec: ParamSpec, value: Any) -> Any:
        if spec.type == PortType.NUMBER:
            try:
                return float(value)
            except (TypeError, ValueError):
                raise NodeConfigError(f"参数 {spec.name} 需要数值，收到: {value!r}") from None
        if spec.type == PortType.BOOLEAN and not isinstance(value, bool):
            return str(value).lower() in ("true", "1", "yes")
        return value

    def validate_inputs(self, inputs: Dict[str, Any]) -> None:
        """执行前校验输入完整性（端口存在性由 DAG 构建时保证）。"""
        for port in self.input_ports:
            if port.required and (port.name not in inputs or inputs[port.name] is None):
                raise NodeExecutionError(
                    self.node_id,
                    f"缺少必填输入端口 '{port.name}'（来自节点 {self.node_type}）",
                )

    # ------------------------------------------------------------------ #
    # 规格输出
    # ------------------------------------------------------------------ #
    @classmethod
    def spec(cls) -> dict:
        return {
            "node_type": cls.node_type,
            "label": cls.label or cls.node_type,
            "category": cls.category,
            "description": cls.description,
            "version": cls.version,
            "inputs": [p.to_dict() for p in cls.input_ports],
            "outputs": [p.to_dict() for p in cls.output_ports],
            "params": [p.to_dict() for p in cls.param_schema],
        }


# --------------------------------------------------------------------------- #
# @work_node 装饰器：声明式注册
# --------------------------------------------------------------------------- #
def work_node(
    node_type: str,
    *,
    label: Optional[str] = None,
    category: str = "通用",
    description: str = "",
    version: str = "1.0.0",
    inputs: Optional[List[Union[PortSpec, dict]]] = None,
    outputs: Optional[List[Union[PortSpec, dict]]] = None,
    params: Optional[List[Union[ParamSpec, dict]]] = None,
) -> Callable[[type], type]:
    """节点注册装饰器。

    用法：
        @work_node(
            "math.add",
            label="加法",
            category="数学",
            inputs=[PortSpec("a"), PortSpec("b")],
            outputs=[PortSpec("result")],
            params=[ParamSpec("scale", default=1.0)],
        )
        class AddNode(BaseWorkNode):
            def execute(self, ctx, inputs):
                return {"result": inputs["a"] + inputs["b"]}
    """

    def _to_port(item: Union[PortSpec, dict]) -> PortSpec:
        if isinstance(item, PortSpec):
            return item
        return PortSpec(**item)

    def _to_param(item: Union[ParamSpec, dict]) -> ParamSpec:
        if isinstance(item, ParamSpec):
            return item
        return ParamSpec(**item)

    def decorator(cls: type) -> type:
        if not issubclass(cls, BaseWorkNode):
            raise TypeError(f"@work_node 只能装饰 BaseWorkNode 子类，收到 {cls!r}")

        cls.node_type = node_type
        cls.label = label or cls.label or node_type
        cls.category = category
        cls.description = description or cls.description
        cls.version = version
        cls.input_ports = [_to_port(p) for p in inputs] if inputs is not None else cls.input_ports
        cls.output_ports = [_to_port(p) for p in outputs] if outputs is not None else cls.output_ports
        cls.param_schema = [_to_param(p) for p in params] if params is not None else cls.param_schema

        _validate_node_spec(cls)
        REGISTRY.register(cls)
        return cls

    return decorator


def _validate_node_spec(cls: type) -> None:
    if not cls.node_type:
        raise ValueError(f"节点类 {cls.__name__} 缺少 node_type")
    seen_in, seen_out = set(), set()
    for p in cls.input_ports:
        if p.name in seen_in or p.type not in PortType.ALL:
            raise ValueError(f"节点 {cls.node_type} 输入端口定义非法: {p.name}")
        seen_in.add(p.name)
    for p in cls.output_ports:
        if p.name in seen_out or p.type not in PortType.ALL:
            raise ValueError(f"节点 {cls.node_type} 输出端口定义非法: {p.name}")
        seen_out.add(p.name)


def instantiate_node(node_type: str, node_id: str, params: Optional[dict] = None) -> BaseWorkNode:
    """根据类型实例化节点（执行器入口）。"""
    cls = REGISTRY.get(node_type)
    return cls(node_id=node_id, params=params)
