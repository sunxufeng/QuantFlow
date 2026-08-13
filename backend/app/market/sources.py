"""行情数据源抽象（M2 数据层）。

设计目标（对齐开发计划 §4.2 数据层）：
- 多数据源适配：tushare 等商业源 + 明确标记的合成测试数据
- 统一返回 ``Bar`` 列表，服务层负责缓存与落库
- 生产数据源失败时显式报错，不把测试数据冒充真实行情
"""

from __future__ import annotations

import abc
import hashlib
import logging
import random
from typing import List, Optional, Tuple

from .models import Bar, Instrument, INTERVAL_MINUTE

logger = logging.getLogger("quantflow.market")


class DataSourceError(Exception):
    """数据源异常（授权缺失 / 网络失败 / 返回异常）。"""


class MarketDataSource(abc.ABC):
    """行情数据源接口。"""

    name: str = "base"
    adjustment: str = "none"

    @abc.abstractmethod
    def fetch_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        """拉取日线，区间闭区间 [start, end]（YYYY-MM-DD）。"""

    def fetch_minute(self, symbol: str, start: str, end: str) -> List[Bar]:
        """拉取分钟线（V1.2）。

        默认实现不支持；具体数据源按需覆盖。区间闭区间 [start, end]。
        """
        raise DataSourceError(f"数据源 {self.name} 不支持分钟级行情")

    @abc.abstractmethod
    def symbols(self) -> List[Instrument]:
        """返回该数据源可用的标的列表。"""


# --------------------------------------------------------------------------- #
# 合成测试数据源（仅用于离线演示与手工回测基准）
# --------------------------------------------------------------------------- #
# fmt: off
_FIXTURE_DAILY = {
    "TEST.STOCK": [
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
    "TEST.BANK": [
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
    "TEST.FUND": [  # 沪深300 ETF（基金回测 Q-01 用例）
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

_FIXTURE_INSTRUMENTS = [
    Instrument("TEST.STOCK", "Synthetic stock fixture", "TEST", "stock"),
    Instrument("TEST.BANK", "Synthetic bank fixture", "TEST", "stock"),
    Instrument("TEST.FUND", "Synthetic domestic ETF fixture", "TEST", "fund"),
]


class LocalDataSource(MarketDataSource):
    """Synthetic offline fixture source; never represents production market data."""

    name = "fixture"
    adjustment = "none"

    def fetch_daily(self, symbol: str, start: str, end: str) -> List[Bar]:
        raw = _FIXTURE_DAILY.get(symbol)
        if raw is None:
            return []
        bars: List[Bar] = []
        for date, o, h, l, c, vol in raw:
            if start <= date <= end:
                bars.append(
                    Bar(
                        symbol=symbol,
                        date=date,
                        open=o,
                        high=h,
                        low=l,
                        close=c,
                        volume=float(vol),
                        source=self.name,
                        adjustment=self.adjustment,
                    )
                )
        return bars

    # 日内交易时段（30 分钟一根，共 10 根/日）
    MINUTE_SESSION = [
        "09:30", "10:00", "10:30", "11:00", "11:30",
        "13:00", "13:30", "14:00", "14:30", "15:00",
    ]

    def fetch_minute(self, symbol: str, start: str, end: str) -> List[Bar]:
        """由日线合成确定性的分钟线（V1.2 离线演示用）。

        - 以日线 OHLC 为锚：首根开盘=日开盘，末根收盘=日收盘，高低包围路径；
        - 用 ``(symbol, date)`` 派生种子，保证可复现；
        - 仅对股票标的合成（基金按日 NAV，无分钟线）。
        """
        if symbol not in _FIXTURE_DAILY:
            return []
        bars: List[Bar] = []
        n = len(self.MINUTE_SESSION)
        for date, o, h, l, c, vol in _FIXTURE_DAILY[symbol]:
            if not (start <= date <= end):
                continue
            seed = int(hashlib.sha1(f"{symbol}:{date}".encode()).hexdigest(), 16) % (2 ** 31)
            rng = random.Random(seed)
            span = max(h - l, 1e-6)
            closes: List[float] = []
            for i in range(n):
                t = (i + 1) / n
                base = o + (c - o) * t
                noise = rng.uniform(-1, 1) * span * 0.15
                closes.append(base + noise)
            closes[-1] = c  # 末根收盘锁定为日线收盘
            opens = [o] + closes[:-1]
            for i, tm in enumerate(self.MINUTE_SESSION):
                dt = f"{date} {tm}:00"
                hi = max(opens[i], closes[i]) * (1 + rng.uniform(0, 0.004))
                lo = min(opens[i], closes[i]) * (1 - rng.uniform(0, 0.004))
                v = (vol / n) * rng.uniform(0.6, 1.4)
                bars.append(
                    Bar(
                        symbol=symbol,
                        date=date,
                        datetime=dt,
                        open=round(opens[i], 4),
                        high=round(hi, 4),
                        low=round(lo, 4),
                        close=round(closes[i], 4),
                        volume=round(v, 2),
                        interval=INTERVAL_MINUTE,
                        source=self.name,
                        adjustment=self.adjustment,
                    )
                )
        return bars

    def symbols(self) -> List[Instrument]:
        return list(_FIXTURE_INSTRUMENTS)


# --------------------------------------------------------------------------- #
# tushare 数据源（商业源适配，Q-02 决策）
# --------------------------------------------------------------------------- #
class TushareDataSource(MarketDataSource):
    """tushare pro 数据源。

    - 通过 ``QF_TUSHARE_TOKEN`` 配置 token；未配置时抛 ``DataSourceError``。
    - Tushare ``vol`` 单位为手、``amount`` 单位为千元；统一转成股和元。
    """

    name = "tushare"
    adjustment = "qfq"

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
        df = ts.pro_bar(
            ts_code=symbol,
            adj=self.adjustment,
            start_date=start.replace("-", ""),
            end_date=end.replace("-", ""),
        )
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
                    volume=float(row["vol"]) * 100.0,
                    amount=float(row["amount"]) * 1000.0,
                    source=self.name,
                    adjustment=self.adjustment,
                )
            )
        return bars

    def symbols(self) -> List[Instrument]:
        raise DataSourceError("tushare 标的列表需按需求查询，请直接传入 ts_code")


# --------------------------------------------------------------------------- #
# 数据源注册与选择
# --------------------------------------------------------------------------- #
def default_data_source() -> MarketDataSource:
    """Select the configured provider; fixture mode must be explicit."""
    import os

    provider = os.getenv("QF_MARKET_PROVIDER", "tushare").lower()
    if provider == "fixture":
        return LocalDataSource()
    if provider == "tushare":
        return TushareDataSource(token=os.getenv("QF_TUSHARE_TOKEN", ""))
    raise DataSourceError(f"Unsupported market data provider: {provider}")


def cache_key(provider: str, symbol: str, start: str, end: str, interval: str) -> str:
    raw = f"{provider}:{symbol}:{interval}:{start}:{end}"
    return hashlib.sha1(raw.encode()).hexdigest()[:24]
