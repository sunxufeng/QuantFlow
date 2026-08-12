"""行情数据源抽象（M2 数据层）。

设计目标（对齐开发计划 §4.2 数据层）：
- 多数据源适配：tushare 等商业源 + 本地内置数据（离线可用）
- 统一返回 ``Bar`` 列表，服务层负责缓存与落库
- 数据源缺 Key / 网络不可用时自动降级到本地数据，保证平台可运行
"""

from __future__ import annotations

import abc
import hashlib
import logging
from typing import List, Optional, Tuple

from .models import Bar, Instrument

logger = logging.getLogger("quantflow.market")


class DataSourceError(Exception):
    """数据源异常（授权缺失 / 网络失败 / 返回异常）。"""


class MarketDataSource(abc.ABC):
    """行情数据源接口。"""

    name: str = "base"

    @abc.abstractmethod
    def fetch_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        """拉取日线，区间闭区间 [start, end]（YYYY-MM-DD）。"""

    @abc.abstractmethod
    def symbols(self) -> List[Instrument]:
        """返回该数据源可用的标的列表。"""


# --------------------------------------------------------------------------- #
# 本地内置数据源（离线可用，演示/回测基准）
# --------------------------------------------------------------------------- #
# fmt: off
_BUILTIN_DAILY = {
    "600519.SH": [
        ("2024-01-02", 1685.0, 1700.0, 1678.0, 1692.5, 3200000),
        ("2024-01-03", 1692.0, 1698.0, 1670.0, 1675.0, 2800000),
        ("2024-01-04", 1672.0, 1680.0, 1655.0, 1660.0, 3100000),
        ("2024-01-05", 1662.0, 1675.0, 1640.0, 1648.5, 3500000),
        ("2024-01-08", 1650.0, 1658.0, 1622.0, 1630.0, 3800000),
        ("2024-01-09", 1632.0, 1660.0, 1628.0, 1655.0, 3300000),
        ("2024-01-10", 1658.0, 1662.0, 1630.0, 1638.0, 2600000),
        ("2024-01-11", 1640.0, 1670.0, 1635.0, 1666.0, 3600000),
        ("2024-01-12", 1668.0, 1688.0, 1660.0, 1682.0, 3200000),
        ("2024-01-15", 1680.0, 1695.0, 1668.0, 1678.0, 2900000),
        ("2024-01-16", 1680.0, 1690.0, 1650.0, 1658.0, 3400000),
        ("2024-01-17", 1656.0, 1660.0, 1610.0, 1618.0, 4200000),
        ("2024-01-18", 1620.0, 1655.0, 1615.0, 1648.0, 3900000),
        ("2024-01-19", 1650.0, 1672.0, 1640.0, 1660.0, 3000000),
        ("2024-01-22", 1662.0, 1668.0, 1608.0, 1615.0, 4500000),
        ("2024-01-23", 1618.0, 1650.0, 1612.0, 1642.0, 3500000),
        ("2024-01-24", 1644.0, 1680.0, 1638.0, 1675.0, 3800000),
        ("2024-01-25", 1678.0, 1715.0, 1670.0, 1708.0, 4000000),
        ("2024-01-26", 1710.0, 1720.0, 1690.0, 1698.0, 3600000),
        ("2024-01-29", 1700.0, 1705.0, 1650.0, 1658.0, 3700000),
    ],
    "000001.SZ": [
        ("2024-01-02", 9.02, 9.15, 8.98, 9.10, 58000000),
        ("2024-01-03", 9.12, 9.20, 9.05, 9.08, 52000000),
        ("2024-01-04", 9.06, 9.12, 8.95, 8.98, 61000000),
        ("2024-01-05", 9.00, 9.05, 8.88, 8.90, 65000000),
        ("2024-01-08", 8.92, 8.98, 8.70, 8.75, 70000000),
        ("2024-01-09", 8.78, 9.00, 8.75, 8.95, 60000000),
        ("2024-01-10", 8.98, 9.02, 8.80, 8.85, 48000000),
        ("2024-01-11", 8.88, 9.20, 8.85, 9.15, 75000000),
        ("2024-01-12", 9.18, 9.30, 9.10, 9.25, 70000000),
        ("2024-01-15", 9.22, 9.35, 9.12, 9.20, 62000000),
        ("2024-01-16", 9.20, 9.25, 8.95, 9.02, 68000000),
        ("2024-01-17", 9.00, 9.05, 8.72, 8.80, 80000000),
        ("2024-01-18", 8.82, 9.05, 8.78, 9.00, 72000000),
        ("2024-01-19", 9.02, 9.15, 8.90, 9.08, 55000000),
        ("2024-01-22", 9.10, 9.12, 8.68, 8.75, 85000000),
        ("2024-01-23", 8.78, 9.00, 8.75, 8.92, 65000000),
        ("2024-01-24", 8.94, 9.25, 8.90, 9.20, 72000000),
        ("2024-01-25", 9.22, 9.50, 9.18, 9.45, 82000000),
        ("2024-01-26", 9.48, 9.55, 9.20, 9.30, 66000000),
        ("2024-01-29", 9.32, 9.35, 8.95, 9.05, 71000000),
    ],
    "510300.SH": [  # 沪深300 ETF（基金回测 Q-01 用例）
        ("2024-01-02", 3.412, 3.450, 3.400, 3.445, 89000000),
        ("2024-01-03", 3.448, 3.452, 3.410, 3.420, 76000000),
        ("2024-01-04", 3.415, 3.430, 3.380, 3.395, 82000000),
        ("2024-01-05", 3.400, 3.420, 3.350, 3.365, 95000000),
        ("2024-01-08", 3.360, 3.390, 3.310, 3.325, 100000000),
        ("2024-01-09", 3.330, 3.390, 3.320, 3.375, 88000000),
        ("2024-01-10", 3.380, 3.385, 3.310, 3.320, 70000000),
        ("2024-01-11", 3.325, 3.430, 3.320, 3.405, 100000000),
        ("2024-01-12", 3.410, 3.470, 3.400, 3.455, 94000000),
        ("2024-01-15", 3.455, 3.480, 3.420, 3.435, 85000000),
        ("2024-01-16", 3.435, 3.445, 3.360, 3.375, 90000000),
        ("2024-01-17", 3.370, 3.380, 3.260, 3.275, 110000000),
        ("2024-01-18", 3.280, 3.350, 3.270, 3.330, 100000000),
        ("2024-01-19", 3.335, 3.390, 3.300, 3.345, 82000000),
        ("2024-01-22", 3.350, 3.355, 3.220, 3.235, 115000000),
        ("2024-01-23", 3.240, 3.300, 3.230, 3.275, 95000000),
        ("2024-01-24", 3.280, 3.360, 3.270, 3.340, 105000000),
        ("2024-01-25", 3.345, 3.460, 3.335, 3.440, 120000000),
        ("2024-01-26", 3.445, 3.455, 3.350, 3.370, 100000000),
        ("2024-01-29", 3.375, 3.380, 3.250, 3.265, 110000000),
    ],
}
# fmt: on

_BUILTIN_INSTRUMENTS = [
    Instrument("600519.SH", "贵州茅台", "SH", "stock"),
    Instrument("000001.SZ", "平安银行", "SZ", "stock"),
    Instrument("510300.SH", "沪深300ETF", "SH", "fund"),
]


class LocalDataSource(MarketDataSource):
    """内置演示行情：离线可用，作为回测基准与降级兜底。"""

    name = "local"

    def fetch_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        raw = _BUILTIN_DAILY.get(symbol)
        if raw is None:
            return []
        bars: List[Bar] = []
        for date, o, h, l, c, vol in raw:
            if start <= date <= end:
                bars.append(
                    Bar(symbol=symbol, date=date, open=o, high=h, low=l, close=c, volume=float(vol))
                )
        return bars

    def symbols(self) -> List[Instrument]:
        return list(_BUILTIN_INSTRUMENTS)


# --------------------------------------------------------------------------- #
# tushare 数据源（商业源适配，Q-02 决策）
# --------------------------------------------------------------------------- #
class TushareDataSource(MarketDataSource):
    """tushare pro 数据源。

    - 通过 ``QF_TUSHARE_TOKEN`` 配置 token；未配置时抛 ``DataSourceError``，
      由服务层捕获并降级到本地源。
    - 注意：tushare 日线接口返回的单位与字段需按文档做归一化。
    """

    name = "tushare"

    def __init__(self, token: Optional[str] = None) -> None:
        self.token = token
        self._ts = None

    def _client(self):
        if self._ts is None:
            if not self.token:
                raise DataSourceError("未配置 QF_TUSHARE_TOKEN，tushare 数据源不可用")
            try:
                import tushare as ts  # 延迟导入：未安装时不阻塞其他源
            except ImportError as exc:  # pragma: no cover
                raise DataSourceError("未安装 tushare 依赖") from exc
            ts.set_token(self.token)
            self._ts = ts
        return self._ts

    def fetch_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        ts = self._client()
        code = symbol.split(".")[0]  # 600519.SH -> 600519
        df = ts.pro_bar(ts_code=symbol, adj="qfq", start_date=start.replace("-", ""), end_date=end.replace("-", ""))
        if df is None or df.empty:
            return []
        bars: List[Bar] = []
        for _, row in df.sort_values("trade_date").iterrows():
            bars.append(
                Bar(
                    symbol=symbol,
                    date=f"{row['trade_date'][:4]}-{row['trade_date'][4:6]}-{row['trade_date'][6:]}",
                    open=float(row["open"]),
                    high=float(row["high"]),
                    low=float(row["low"]),
                    close=float(row["close"]),
                    volume=float(row["vol"]),
                    amount=float(row["amount"]),
                )
            )
        return bars

    def symbols(self) -> List[Instrument]:
        raise DataSourceError("tushare 标的列表需按需求查询，请直接传入 ts_code")


# --------------------------------------------------------------------------- #
# 数据源注册与选择
# --------------------------------------------------------------------------- #
def default_data_source() -> MarketDataSource:
    """按配置返回首选数据源；未配置 tushare 时退回本地源。"""
    import os

    token = os.getenv("QF_TUSHARE_TOKEN", "")
    if token:
        return TushareDataSource(token=token)
    return LocalDataSource()


def cache_key(provider: str, symbol: str, start: str, end: str, interval: str) -> str:
    raw = f"{provider}:{symbol}:{interval}:{start}:{end}"
    return hashlib.sha1(raw.encode()).hexdigest()[:24]
