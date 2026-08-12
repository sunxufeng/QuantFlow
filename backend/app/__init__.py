"""QuantFlow 应用包。

导入任意 app.* 子模块都会先触发节点包注册（@work_node 装饰器副作用），
确保测试/脚本/服务启动场景下节点库始终可用。
"""

from . import nodes  # noqa: F401  (must come first: 触发节点注册)
