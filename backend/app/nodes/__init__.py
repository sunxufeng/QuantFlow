"""节点包入口：导入即触发注册（@work_node 装饰器）。

V1.0 演进：discover() 改为按插件目录/命名空间自动加载外部插件，
当前原型先支持内置节点包的显式导入。
"""

from . import basic  # noqa: F401  触发节点注册


def discover() -> None:
    """启动时调用，确保所有内置节点完成注册。"""
    from ..core.registry import REGISTRY

    return REGISTRY
