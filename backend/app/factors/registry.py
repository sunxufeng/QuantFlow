"""因子库注册表（V2.5）。

每个因子都是纯函数，输入一段日线 Bar 序列（按日期升序），
输出一个标量因子值；数据不足时返回 ``None``。

因子设计面向合成行情（仅 OHLCV），不依赖财务基本面数据，
因此离线即可运行。后续接入真实数据源（tushare 等）后无需改动因子本身。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional

from ..market.models import Bar


def _closes(bars: List[Bar]) -> List[float]:
    return [float(b.close) for b in bars]


def _daily_returns(bars: List[Bar]) -> List[float]:
    closes = _closes(bars)
    return [closes[i] / closes[i - 1] - 1.0 for i in range(1, len(closes))]


def momentum(bars: List[Bar], window: int = 20) -> Optional[float]:
    """区间动量：近 ``window`` 日收益率 close[-1]/close[-1-window] - 1。"""
    closes = _closes(bars)
    if len(closes) <= window:
        return None
    past = closes[-1 - window]
    if past <= 0:
        return None
    return closes[-1] / past - 1.0


def volatility(bars: List[Bar], window: int = 20) -> Optional[float]:
    """年化波动率：日收益率标准差 * sqrt(252)。"""
    rets = _daily_returns(bars)
    if len(rets) < 2 or len(rets) < window:
        return None
    window = min(window, len(rets))
    seg = rets[-window:]
    mean = sum(seg) / len(seg)
    var = sum((r - mean) ** 2 for r in seg) / (len(seg) - 1)
    return math.sqrt(var) * math.sqrt(252)


def rsi(bars: List[Bar], window: int = 14) -> Optional[float]:
    """相对强弱指标 RSI（Wilder 平滑），取值 0~100。"""
    closes = _closes(bars)
    if len(closes) <= window:
        return None
    gains, losses = [], []
    for i in range(1, len(closes)):
        d = closes[i] - closes[i - 1]
        gains.append(max(d, 0.0))
        losses.append(max(-d, 0.0))
    seg = list(zip(gains[-window:], losses[-window:]))
    avg_gain = sum(g for g, _ in seg) / window
    avg_loss = sum(l for _, l in seg) / window
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def mean_reversion(bars: List[Bar], window: int = 20) -> Optional[float]:
    """均值回归偏离度：close / SMA(window) - 1，越大越偏离（超买）。"""
    closes = _closes(bars)
    if len(closes) < window:
        return None
    seg = closes[-window:]
    sma = sum(seg) / len(seg)
    if sma <= 0:
        return None
    return closes[-1] / sma - 1.0


def volume_trend(bars: List[Bar], window: int = 20) -> Optional[float]:
    """量能趋势：近 ``window`` 日均量 / 前 ``window`` 日均量 - 1。"""
    vols = [float(b.volume) for b in bars]
    if len(vols) < 2 * window:
        return None
    recent = sum(vols[-window:]) / window
    prior = sum(vols[-2 * window : -window]) / window
    if prior <= 0:
        return None
    return recent / prior - 1.0


def drawdown(bars: List[Bar], window: int = 20) -> Optional[float]:
    """近期最大回撤（负值）：(close - max_close_in_window) / max_close_in_window。"""
    closes = _closes(bars)
    if len(closes) < window:
        return None
    seg = closes[-window:]
    peak = max(seg)
    if peak <= 0:
        return None
    return closes[-1] / peak - 1.0


def sharpe(bars: List[Bar], window: int = 20) -> Optional[float]:
    """区间夏普：日收益率均值 / 标准差 * sqrt(252)。"""
    rets = _daily_returns(bars)
    if len(rets) < 2 or len(rets) < window:
        return None
    window = min(window, len(rets))
    seg = rets[-window:]
    mean = sum(seg) / len(seg)
    var = sum((r - mean) ** 2 for r in seg) / (len(seg) - 1)
    if var == 0:
        return 0.0
    return (mean / math.sqrt(var)) * math.sqrt(252)


# 因子元数据目录：name -> {fn, window, direction, description}
# direction: 1 = 越大越好（高配）；-1 = 越小越好（低配）
_FACTOR_DEFS: Dict[str, dict] = {
    "momentum": {
        "fn": momentum,
        "window": 10,
        "direction": 1,
        "description": "区间动量：近 N 日收益率，衡量价格趋势强度。",
    },
    "volatility": {
        "fn": volatility,
        "window": 10,
        "direction": -1,
        "description": "年化波动率：越低代表风险越小。",
    },
    "rsi": {
        "fn": rsi,
        "window": 10,
        "direction": 1,
        "description": "相对强弱指标（0~100），衡量相对强弱。",
    },
    "mean_reversion": {
        "fn": mean_reversion,
        "window": 10,
        "direction": -1,
        "description": "均值偏离度：偏离均线越大（超买）越低配。",
    },
    "volume_trend": {
        "fn": volume_trend,
        "window": 10,
        "direction": 1,
        "description": "量能趋势：放量代表资金关注度上升。",
    },
    "drawdown": {
        "fn": drawdown,
        "window": 10,
        "direction": 1,
        "description": "近期回撤：越接近 0 代表回撤越小（高配）。",
    },
    "sharpe": {
        "fn": sharpe,
        "window": 10,
        "direction": 1,
        "description": "区间夏普比率：风险调整后收益越高越好。",
    },
}


def list_factors() -> List[dict]:
    """返回全部可用因子的元数据（用于前端选择）。"""
    return [
        {
            "name": name,
            "window": meta["window"],
            "direction": meta["direction"],
            "description": meta["description"],
        }
        for name, meta in _FACTOR_DEFS.items()
    ]


def get_factor(name: str) -> dict:
    if name not in _FACTOR_DEFS:
        raise FactorNotFoundError(name)
    return _FACTOR_DEFS[name]


def compute_factor(name: str, bars: List[Bar], window: Optional[int] = None) -> Optional[float]:
    meta = get_factor(name)
    return meta["fn"](bars, window if window is not None else meta["window"])


class FactorNotFoundError(Exception):
    def __init__(self, name: str) -> None:
        super().__init__(f"未知因子：{name}")
        self.name = name
