"""虚拟券商连接器（V107，B 类实盘功能化）。

解决「真实券商（CTP/QMT/通用 REST）需要柜台 SDK + 凭证，沙箱无法直连」的阻断：
提供一套**接口完全等价**的虚拟连接器，内部复用 :class:`app.execution.gateway.PaperExecutionGateway`
的本地撮合账本，但**以进程级单例账本**承载，使跨请求的下单/持仓/成交状态得以持久。

- 不需要任何外部凭证或 SDK；``is_configured()`` 恒为 True；
- 与 CTP/QMT 连接器共用 ``Order / Fill / Position`` 协议，未来接真实柜台时只需替换连接器；
- 手续费/成本模型与模拟盘一致，适合前向测试（forward test）与演示。

仅当 ``broker`` 配置为 ``virtual``（或 ``simulated`` / ``simulated-broker``）时启用。
"""

from __future__ import annotations

import threading
from typing import Dict, List, Optional

from ...execution.gateway import (
    Fill,
    Order,
    OrderSide,
    PaperExecutionGateway,
    Position,
)


# 进程级共享账本：引擎每次 ``LiveExecutionGateway()`` 都会新建实例，
# 但所有虚拟连接器都指向同一本账，保证下单/持仓/成交跨请求持久。
_VIRTUAL_BOOK: Optional[PaperExecutionGateway] = None
_BOOK_LOCK = threading.Lock()


def _book() -> PaperExecutionGateway:
    global _VIRTUAL_BOOK
    if _VIRTUAL_BOOK is None:
        with _BOOK_LOCK:
            if _VIRTUAL_BOOK is None:
                _VIRTUAL_BOOK = PaperExecutionGateway(initial_cash=1_000_000.0)
    return _VIRTUAL_BOOK


class VirtualBrokerConnector:
    """虚拟券商连接器：等价 CTP/QMT 接口，本地账本撮合，无需凭证。"""

    name = "virtual"
    mode = "virtual"

    def __init__(self) -> None:
        # 共享同一本账；实例本身无状态
        self._book = _book()

    # --- 配置/就绪 ---
    def is_configured(self) -> bool:
        # 虚拟券商永远就绪：无需 SDK、无需凭证
        return True

    def _require_configured(self) -> None:
        # 保持与真实连接器一致的调用约定；虚拟券商始终通过
        return

    # --- 撮合 ---
    def submit_order(self, order: Order, last_price: Optional[float] = None) -> Fill:
        return self._book.submit_order(order, last_price)

    def get_positions(self) -> List[Position]:
        return self._book.get_positions()

    def get_account(self, prices: Optional[Dict[str, float]] = None) -> dict:
        acc = self._book.get_account(prices)
        acc["mode"] = self.mode  # 标记为虚拟券商来源
        return acc

    def get_fills(self) -> List[dict]:
        return [f.to_dict() for f in self._book._fills]

    def reset(self, cash: float) -> None:
        with _BOOK_LOCK:
            self._book.reset(cash)
