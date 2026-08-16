"""交易时段 / 开市判断工具（移植自 panda_quantflow 的 TradeTimeManager）。

panda 在 ``trade_time_manager.py`` 里用 ``is_stock_trade`` / ``is_future_trade``
判断当前是否处于可交易时段，并依赖 ``DateUtil.get_next_trade_date`` 求下一交易日。
这里把这部分**纯逻辑**独立出来，去掉对 Redis / Mongo / 事件总线的依赖，
供下单合规预检（V104）等业务复用。

时段定义（A 股 / 国内期货常见窗口，可按需扩展）：
- 股票：09:30-11:30、13:00-15:00
- 期货日盘：09:00-11:30、13:00-15:00
- 期货夜盘：21:00-次日 02:30（部分品种到 23:00，这里取通用上限）
"""

from __future__ import annotations

import datetime
from typing import List, Optional, Tuple

# (开始时分, 结束时分) ；跨午夜的夜盘用 next_day 标记
SessionWindow = Tuple[int, int, bool]  # (h*100+m start, h*100+m end, crosses_midnight)

STOCK_SESSIONS: List[SessionWindow] = [
    (930, 1130, False),
    (1300, 1500, False),
]

FUTURE_DAY_SESSIONS: List[SessionWindow] = [
    (900, 1130, False),
    (1300, 1500, False),
]

# 夜盘：21:00 -> 次日 02:30（跨午夜，表示为单个连续窗口）
FUTURE_NIGHT_SESSIONS: List[SessionWindow] = [
    (2100, 230, True),
]

# 常见节假日（公历，月和日）；可按交易所公告补充
_CN_HOLIDAYS: set = set()  # e.g. {(1, 1), (10, 1), (5, 1), (4, 5), (5, 5)}


def _now_hm(now: Optional[datetime.datetime] = None) -> int:
    now = now or datetime.datetime.now()
    return now.hour * 100 + now.minute


def _in_windows(hm: int, windows: List[SessionWindow]) -> bool:
    for start, end, crosses in windows:
        if crosses:
            # 跨午夜：start(如 2100) 到次日 end(如 230) 的连续区间
            if hm >= start or hm <= end:
                return True
        else:
            if start <= hm <= end:
                return True
    return False


def is_market_open(asset_type: str = "stock", now: Optional[datetime.datetime] = None) -> bool:
    """判断当前是否处于可交易时段。

    asset_type: ``stock`` | ``future`` | ``future_day`` | ``future_night``
    周末（周六/周日）一律视为休市。
    """
    now = now or datetime.datetime.now()
    if now.weekday() >= 5:  # 5=Sat, 6=Sun
        return False
    if (now.month, now.day) in _CN_HOLIDAYS:
        return False
    hm = _now_hm(now)
    if asset_type == "stock":
        return _in_windows(hm, STOCK_SESSIONS)
    if asset_type == "future_day":
        return _in_windows(hm, FUTURE_DAY_SESSIONS)
    if asset_type == "future_night":
        return _in_windows(hm, FUTURE_NIGHT_SESSIONS)
    # future 默认日盘+夜盘
    return _in_windows(hm, FUTURE_DAY_SESSIONS) or _in_windows(hm, FUTURE_NIGHT_SESSIONS)


def session_label(asset_type: str = "stock", now: Optional[datetime.datetime] = None) -> str:
    """返回人类可读的开市状态标签。"""
    if is_market_open(asset_type, now):
        return "交易中"
    now = now or datetime.datetime.now()
    if now.weekday() >= 5 or (now.month, now.day) in _CN_HOLIDAYS:
        return "休市（非交易日）"
    return "已收盘（非交易时段）"


def next_trade_date(now: Optional[datetime.datetime] = None) -> str:
    """返回下一个交易日（YYYY-MM-DD）。跳过周末与法定假日。"""
    now = now or datetime.datetime.now()
    d = now.date() + datetime.timedelta(days=1)
    while d.weekday() >= 5 or (d.month, d.day) in _CN_HOLIDAYS:
        d += datetime.timedelta(days=1)
    return d.isoformat()
