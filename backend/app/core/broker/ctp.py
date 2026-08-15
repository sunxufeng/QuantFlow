"""CTP 实盘连接器（V31）。

对接综合交易平台 CTP（期货/期权柜台）。真实下单/查询需：
- 安装 CTP Python 封装（如 ``pyctp`` / ``vnpy`` 的 CtpTdApi）；
- 配置：``QF_CTP_USER``（交易账号）、``QF_CTP_PASSWORD``、``QF_CTP_BROKER_ID``（经纪商代码）、
  ``QF_CTP_TD_FRONT``（交易前置地址）；券商设置里 broker=ctp。

未就绪时所有方法抛 ``GatewayNotConfigured``，不影响应用启动与模拟盘。
CTP 为异步回调式 API，本连接器给出「连接-认证-查询」的结构骨架，
实际回报通过回调写入内部缓存；未配置时直接短路为未配置异常。
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


def ctp_available() -> bool:
    """CTP SDK 是否可用（已安装且配置了核心凭证）。"""
    if not (os.getenv("QF_CTP_USER") and os.getenv("QF_CTP_BROKER_ID") and os.getenv("QF_CTP_TD_FRONT")):
        return False
    try:
        import pyctp  # noqa: F401
        return True
    except Exception:
        return False


class CtpConnector:
    """CTP 柜台连接器（期货/期权）。"""

    name = "ctp"
    mode = "live"

    def __init__(self) -> None:
        self._user = os.getenv("QF_CTP_USER", "")
        self._password = os.getenv("QF_CTP_PASSWORD", "")
        self._broker_id = os.getenv("QF_CTP_BROKER_ID", "")
        self._td_front = os.getenv("QF_CTP_TD_FRONT", "")
        self._connected = False

    def is_configured(self) -> bool:
        return ctp_available()

    def _require(self) -> None:
        if not (self._user and self._broker_id and self._td_front):
            raise GatewayNotConfigured(
                "CTP 未配置：设置 QF_CTP_USER / QF_CTP_BROKER_ID / QF_CTP_TD_FRONT"
            )
        if not ctp_available():
            raise GatewayNotConfigured("CTP SDK(pyctp) 不可用：请安装 CTP Python 封装")
        if not self._connected:
            try:
                from pyctp import CtpTdApi
                self._api = CtpTdApi()
                self._api.connect(self._td_front)
                self._api.authenticate(self._broker_id, self._user, self._password)
                self._connected = True
            except Exception as exc:
                raise GatewayNotConfigured(f"CTP 连接/认证失败：{exc}") from exc

    def submit_order(self, order: Order, last_price: Optional[float] = None) -> Fill:
        self._require()
        try:
            px = order.price if order.price is not None else (last_price or 0.0)
            # 真实 CTP 通过 ReqOrderInsert 报单；此处占位组装成交回报
            self._api.req_order_insert(
                symbol=order.symbol,
                exchange="",  # 由上层/合约映射补充
                direction="0" if order.side == OrderSide.BUY else "1",
                offset_flag="0",
                volume=int(order.quantity),
                price=px,
                price_type="1" if order.price is None else "0",
            )
            return Fill(
                symbol=order.symbol, side=order.side, quantity=order.quantity,
                price=px or (last_price or 0.0), cost=0.0, timestamp=__import__("time").time(),
                market=order.market,
            )
        except GatewayNotConfigured:
            raise
        except Exception as exc:
            raise GatewayNotConfigured(f"CTP 下单失败：{exc}") from exc

    def get_positions(self) -> List[Position]:
        self._require()
        try:
            raw = self._api.query_investor_position()
            out = []
            for p in (raw or []):
                out.append(Position(symbol=p["instrument_id"], quantity=float(p["position"]), avg_cost=float(p["open_price"]), market="future"))
            return out
        except Exception as exc:
            raise GatewayNotConfigured(f"CTP 持仓查询失败：{exc}") from exc

    def get_account(self, prices: Optional[dict] = None) -> dict:
        self._require()
        try:
            acc = self._api.query_trading_account()
            return {
                "mode": self.mode, "cash": float(acc.get("available", 0.0)),
                "market_value": float(acc.get("position_profit", 0.0)),
                "equity": float(acc.get("balance", 0.0)),
                "positions": [p.to_dict() for p in self.get_positions()],
            }
        except Exception as exc:
            raise GatewayNotConfigured(f"CTP 账户查询失败：{exc}") from exc

    def get_fills(self) -> List[dict]:
        self._require()
        try:
            raw = self._api.query_trade()
            return [
                {"symbol": t["instrument_id"], "side": ("buy" if t["direction"] == "0" else "sell"),
                 "quantity": float(t["volume"]), "price": float(t["price"]), "timestamp": float(t.get("trade_time", 0.0))}
                for t in (raw or [])
            ]
        except Exception as exc:
            raise GatewayNotConfigured(f"CTP 成交查询失败：{exc}") from exc

    def reset(self, cash: float) -> None:
        self._connected = False
