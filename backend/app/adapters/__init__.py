"""V106 适配器目录：统一汇总「市场数据源」与「券商连接器」的接口缝。

panda_quantflow 覆盖 Tushare / CTP / QMT / 数字货币 等多源；本项目已落地
paper-trading + tushare/fixture，其余实盘源在此以「接口缝」形式注册，便于集中
查看哪些适配器已就绪、哪些仍需凭证/SDK。详见各源类的 required_env / required_sdk。
"""

from .catalog import list_adapters

__all__ = ["list_adapters"]
