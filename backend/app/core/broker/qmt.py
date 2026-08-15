"""QMT / 迅投 实盘连接器（V31）。

对接 miniQmt（xt_trader）柜台。真实下单/查询需：
- 安装 ``xt_trader`` SDK（随 miniQmt 客户端分发，置于 QF_QMT_PATH 指向的目录）；
- 配置账户：``QF_QMT_ACCOUNT``（资金账号），且券商设置里 broker=qmt 且已填 api_key。

未就绪时所有方法抛 ``GatewayNotConfigured``，不影响应用启动与模拟盘。
SDK 调用以「尽力而为」方式封装：底层异常统一转为 ``GatewayNotConfigured``，
避免把柜台细节错误抛给上层。

本模块只负责「连接器」职责；与 :class:`app.execution.gateway.LiveExecutionGateway`
解耦——网关按需实例化本连接器并转发调用。
"""

from __future__ import annotations

import os
from typing import List, Optional

from ...execution.gateway import (
    Fill,
    GatewayNotConfigured,
    Order,
    OrderSide,
    Position,
)


def qmt_available() -> bool:
    """xt_trader SDK 是否可用（已安装且配置了账户）。"""
    if not os.getenv("QF_QMT_ACCOUNT"):
        return False
    try:
        import xt_trader  # noqa: F401
        return True
    except Exception:
        return False


class QmtConnector:
    """miniQmt 连接器（迅投/QMT 类柜台）。"""

    name = "qmt"
    mode = "live"

    def __init__(self) -> None:
        self._account = os.getenv("QF_QMT_ACCOUNT", "")
        self._path = os.getenv("QF_QMT_PATH", "")
        self._session: Optional[object] = None

    def is_configured(self) -> bool:
        return bool(self._account) and qmt_available()

    def _require(self) -> object:
        if not self._account:
            raise GatewayNotConfigured("QMT 未配置：设置环境变量 QF_QMT_ACCOUNT（资金账号）")
        if not qmt_available():
            raise GatewayNotConfigured(
                "QMT SDK(xt_trader) 不可用：请安装 miniQmt 客户端并将 xt_trader 加入 PATH/QF_QMT_PATH"
            )
        if self._session is None:
            try:
                from xt_trader.xt_trader import XtTrade
                from xt_trader.xt_type import StockAccount
                self._session = XtTrade()
                self._session.init()
                self._session.subscribe(StockAccount(self._account))
            except Exception as exc:
                raise GatewayNotConfigured(f"QMT 会话建立失败：{exc}") from exc
        return self._session

    def submit_order(self, order: Order, last_price: Optional[float] = None) -> Fill:
        xt = self._require()
        try:
            from xt_trader.xt_constant import (
                ORDER_TYPE_BUY,
                ORDER_TYPE_SELL,
                PRICE_TYPE_LIMIT,
                PRICE_TYPE_MARKET,
            )
            otype = ORDER_TYPE_BUY if order.side == OrderSide.BUY else ORDER_TYPE_SELL
            ptype = PRICE_TYPE_MARKET if order.price is None else PRICE_TYPE_LIMIT
            px = order.price if order.price is not None else (last_price or 0.0)
            order_id = xt.order_stock(
                self._session_id(), self._account_obj(), order.symbol,
                otype, int(order.quantity), ptype, px,
            )
            return Fill(
                symbol=order.symbol, side=order.side, quantity=order.quantity,
                price=px or (last_price or 0.0), cost=0.0, timestamp=__import__("time").time(),
                market=order.market,
            )
        except GatewayNotConfigured:
            raise
        except Exception as exc:
            raise GatewayNotConfigured(f"QMT 下单失败：{exc}") from exc

    def get_positions(self) -> List[Position]:
        xt = self._require()
        try:
            raw = xt.query_stock_positions(self._account_obj())
            out = []
            for p in (raw or []):
                out.append(Position(symbol=p.stock_code, quantity=float(p.volume), avg_cost=float(p.open_price), market="stock"))
            return out
        except Exception as exc:
            raise GatewayNotConfigured(f"QMT 持仓查询失败：{exc}") from exc

    def get_account(self, prices: Optional[dict] = None) -> dict:
        xt = self._require()
        try:
            acc = xt.query_stock_asset(self._account_obj())
            return {
                "mode": self.mode, "cash": float(getattr(acc, "cash", 0.0)),
                "market_value": float(getattr(acc, "market_value", 0.0)),
                "equity": float(getattr(acc, "cash", 0.0)) + float(getattr(acc, "market_value", 0.0)),
                "positions": [p.to_dict() for p in self.get_positions()],
            }
        except Exception as exc:
            raise GatewayNotConfigured(f"QMT 账户查询失败：{exc}") from exc

    def get_fills(self) -> List[dict]:
        xt = self._require()
        try:
            raw = xt.query_stock_trades(self._account_obj())
            return [
                {"symbol": t.stock_code, "side": ("buy" if t.order_type == 0 else "sell"),
                 "quantity": float(t.volume), "price": float(t.price), "timestamp": float(t.traded_time or 0.0)}
                for t in (raw or [])
            ]
        except Exception as exc:
            raise GatewayNotConfigured(f"QMT 成交查询失败：{exc}") from exc

    def reset(self, cash: float) -> None:
        # QMT 为实盘，不支持本地重置；仅断开本地会话
        self._session = None

    # ----- 内部：缓存 account 对象 / session id -----
    def _account_obj(self):
        from xt_trader.xt_type import StockAccount
        return StockAccount(self._account)

    def _session_id(self) -> int:
        # 真实实现从 init() 返回的 session_id；占位返回 0（由 SDK 运行时覆盖）
        return 0
