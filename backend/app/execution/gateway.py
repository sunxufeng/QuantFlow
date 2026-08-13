"""实盘前哨：执行网关抽象（V1.3 工程化收尾第二阶段）。

提供两套实现：

- ``PaperExecutionGateway``：进程内模拟盘，按最新价即时成交，套用 A 股/期货成本模型；
  用于前向测试（forward test）与演示，无需任何外部凭证。
- ``LiveExecutionGateway``：实盘桩，未配置 ``QF_BROKER_API_KEY`` 时所有下单抛
  ``GatewayNotConfigured``；配置后接口已定义，留待接入真实券商/柜台。

切换由环境变量 ``QF_EXECUTION_GATEWAY``（paper|live，默认 paper）控制，
``get_execution_gateway()`` 返回进程内单例。
"""

from __future__ import annotations

import os
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional

from ..backtest.costs import CostCalculator, CostRates


class OrderSide(str, Enum):
    BUY = "buy"
    SELL = "sell"


@dataclass
class Order:
    symbol: str
    side: OrderSide
    quantity: float  # 股票为股数；期货为手数
    market: str = "stock"  # stock / future
    price: Optional[float] = None  # 限价；None 表示市价（用 last_price 成交）


@dataclass
class Fill:
    symbol: str
    side: OrderSide
    quantity: float
    price: float
    cost: float
    timestamp: float
    market: str = "stock"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "side": self.side.value,
            "quantity": self.quantity,
            "price": self.price,
            "cost": round(self.cost, 4),
            "timestamp": self.timestamp,
            "market": self.market,
        }


@dataclass
class Position:
    symbol: str
    quantity: float  # 可负（期货空头）
    avg_cost: float
    market: str = "stock"

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "quantity": self.quantity,
            "avg_cost": self.avg_cost,
            "market": self.market,
        }


class GatewayNotConfigured(Exception):
    """实盘网关未配置凭证时抛出。"""


class BaseExecutionGateway(ABC):
    name: str = "base"
    mode: str = "base"

    @abstractmethod
    def submit_order(self, order: Order, last_price: Optional[float] = None) -> Fill:
        ...

    @abstractmethod
    def get_positions(self) -> List[Position]:
        ...

    @abstractmethod
    def get_account(self, prices: Optional[Dict[str, float]] = None) -> dict:
        ...

    @abstractmethod
    def reset(self, cash: float) -> None:
        ...


class PaperExecutionGateway(BaseExecutionGateway):
    name = "paper"
    mode = "paper"

    def __init__(self, initial_cash: float = 1_000_000.0) -> None:
        self._initial_cash = float(initial_cash)
        self._cash = float(initial_cash)
        self._positions: Dict[str, Position] = {}
        self._last_price: Dict[str, float] = {}
        self._calculator = CostCalculator(CostRates())
        self._fills: List[Fill] = []

    # --- 内部工具 ---
    def _cost(self, order: Order, price: float) -> float:
        if order.market == "future":
            return self._calculator.rates.futures_commission_per_lot * abs(order.quantity)
        return self._calculator.transaction_costs(
            price, int(order.quantity), order.side == OrderSide.BUY
        )["total"]

    def _apply_fill(self, order: Order, price: float, cost: float) -> Fill:
        is_buy = order.side == OrderSide.BUY
        signed_qty = order.quantity if is_buy else -order.quantity
        pos = self._positions.get(order.symbol)
        if pos is None:
            pos = Position(
                symbol=order.symbol, quantity=0.0, avg_cost=price, market=order.market
            )
            self._positions[order.symbol] = pos
        new_qty = pos.quantity + signed_qty
        if abs(new_qty) > 1e-9:
            # 买入按加权均价抬高成本基数；卖出不改变 avg_cost
            if is_buy:
                total_cost = pos.avg_cost * pos.quantity + price * order.quantity
                pos.avg_cost = total_cost / new_qty
            pos.quantity = new_qty
        else:
            pos.quantity = 0.0
            pos.avg_cost = price
        if is_buy:
            self._cash -= price * order.quantity + cost
        else:
            self._cash += price * order.quantity - cost
        self._last_price[order.symbol] = price
        fill = Fill(
            symbol=order.symbol,
            side=order.side,
            quantity=order.quantity,
            price=price,
            cost=cost,
            timestamp=time.time(),
            market=order.market,
        )
        self._fills.append(fill)
        return fill

    # --- 抽象实现 ---
    def submit_order(self, order: Order, last_price: Optional[float] = None) -> Fill:
        if order.quantity <= 0:
            raise ValueError("quantity 必须为正数")
        price = order.price if order.price is not None else last_price
        if price is None or price <= 0:
            raise ValueError("无可用成交价（需 order.price 或 last_price）")
        cost = self._cost(order, price)
        return self._apply_fill(order, price, cost)

    def get_positions(self) -> List[Position]:
        return [p for p in self._positions.values() if abs(p.quantity) > 1e-9]

    def get_account(self, prices: Optional[Dict[str, float]] = None) -> dict:
        prices = prices or {}
        market_value = 0.0
        positions = []
        for sym, pos in self._positions.items():
            if abs(pos.quantity) <= 1e-9:
                continue
            px = prices.get(sym, self._last_price.get(sym))
            mv = (px * pos.quantity) if px is not None else pos.avg_cost * pos.quantity
            market_value += mv
            d = pos.to_dict()
            d["market_value"] = round(mv, 4)
            d["last_price"] = px
            positions.append(d)
        return {
            "mode": self.mode,
            "cash": round(self._cash, 4),
            "market_value": round(market_value, 4),
            "equity": round(self._cash + market_value, 4),
            "initial_cash": self._initial_cash,
            "positions": positions,
            "fills": [f.to_dict() for f in self._fills],
        }

    def reset(self, cash: float) -> None:
        self._initial_cash = float(cash)
        self._cash = float(cash)
        self._positions.clear()
        self._last_price.clear()
        self._fills.clear()


class LiveExecutionGateway(BaseExecutionGateway):
    name = "live"
    mode = "live"

    def __init__(self) -> None:
        self._api_key = os.getenv("QF_BROKER_API_KEY", "")
        self._broker = os.getenv("QF_BROKER", "simulated-broker")

    def _ensure_configured(self) -> None:
        if not self._api_key:
            raise GatewayNotConfigured(
                "实盘网关未配置：设置 QF_BROKER_API_KEY 与 QF_BROKER 后方可启用 live 模式"
            )

    def submit_order(self, order: Order, last_price: Optional[float] = None) -> Fill:
        self._ensure_configured()
        raise NotImplementedError("LiveExecutionGateway 真实券商接入待实现（凭证就绪时补齐）")

    def get_positions(self) -> List[Position]:
        self._ensure_configured()
        raise NotImplementedError("LiveExecutionGateway 真实券商接入待实现（凭证就绪时补齐）")

    def get_account(self, prices: Optional[Dict[str, float]] = None) -> dict:
        self._ensure_configured()
        raise NotImplementedError("LiveExecutionGateway 真实券商接入待实现（凭证就绪时补齐）")

    def reset(self, cash: float) -> None:
        self._ensure_configured()
        raise NotImplementedError("LiveExecutionGateway 真实券商接入待实现（凭证就绪时补齐）")


_GATEWAY: Optional[BaseExecutionGateway] = None


def get_execution_gateway() -> BaseExecutionGateway:
    """返回进程内执行网关单例（按 QF_EXECUTION_GATEWAY 选择 paper/live）。"""
    global _GATEWAY
    if _GATEWAY is None:
        mode = os.getenv("QF_EXECUTION_GATEWAY", "paper").lower()
        if mode == "live":
            _GATEWAY = LiveExecutionGateway()
        else:
            cash = float(os.getenv("QF_PAPER_CASH", "1000000"))
            _GATEWAY = PaperExecutionGateway(initial_cash=cash)
    return _GATEWAY
