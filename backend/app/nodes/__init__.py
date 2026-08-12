"""节点包入口：导入即触发注册（@work_node 装饰器）。

V1.0 演进：discover() 改为按插件目录/命名空间自动加载外部插件，
当前原型先支持内置节点包的显式导入。
"""

from . import basic  # noqa: F401  触发节点注册
from . import backtest_nodes  # noqa: F401  M3 回测节点
from . import factors  # noqa: F401  M3 因子节点
from . import indicators  # noqa: F401  M3 特征节点
from . import market_data  # noqa: F401  M3 数据节点
from . import ml_nodes  # noqa: F401  M3 ML 节点
from . import processing  # noqa: F401  M3 处理节点


def discover() -> None:
    """启动时调用，确保所有内置节点完成注册。"""
    from ..core.registry import REGISTRY

    return REGISTRY
