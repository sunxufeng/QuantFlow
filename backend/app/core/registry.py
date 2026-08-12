"""插件注册表（PluginRegistry）：M1 原型 —— 节点类型的注册、发现与规格查询。

对标 panda_quantflow 的插件系统，V1.0 演进方向：
- 动态加载外部插件包（目录 / 安装包），本模块预留 scan/register 扩展点
- 节点分组、搜索、版本管理在 M3 节点库阶段补充
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Dict, List, Type

if TYPE_CHECKING:
    from .node import BaseWorkNode


class PluginRegistry:
    """节点类注册表（进程级单例）。

    用法：
        PluginRegistry.register(MyNodeClass)
        cls = PluginRegistry.get("my_node_type")
        specs = PluginRegistry.specs()
    """

    _nodes: Dict[str, Type["BaseWorkNode"]] = {}

    @classmethod
    def register(cls, node_cls: Type["BaseWorkNode"]) -> Type["BaseWorkNode"]:
        if not getattr(node_cls, "node_type", ""):
            raise ValueError(
                f"节点类 {node_cls.__name__} 未声明 node_type，请使用 @work_node 装饰器注册"
            )
        if node_cls.node_type in cls._nodes:
            raise ValueError(f"节点类型重复注册: {node_cls.node_type}")
        cls._nodes[node_cls.node_type] = node_cls
        return node_cls

    @classmethod
    def get(cls, node_type: str) -> Type["BaseWorkNode"]:
        try:
            return cls._nodes[node_type]
        except KeyError:
            raise KeyError(f"未注册的节点类型: {node_type}") from None

    @classmethod
    def has(cls, node_type: str) -> bool:
        return node_type in cls._nodes

    @classmethod
    def all(cls) -> List[Type["BaseWorkNode"]]:
        return list(cls._nodes.values())

    @classmethod
    def specs(cls) -> List[dict]:
        """返回全部节点规格（供前端面板渲染与 API 下发）。"""
        return [node_cls.spec() for node_cls in cls._nodes.values()]

    @classmethod
    def clear(cls) -> None:
        cls._nodes.clear()


REGISTRY = PluginRegistry()
