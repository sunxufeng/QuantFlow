"""股票账户与撮合模型（M2 回测引擎）。

对标开发计划 §4.2：
- 现金 + 持仓（数量 / 可用数量，T+1 冻结）
- 撮合规则：T+1（当日买入不可卖）、涨停不可买入、跌停不可卖出、停牌不撮合
- 交易以整手（100 股）为单位（股票）
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

from .costs import CostCalculator

# 涨跌停幅度（A 股主板）
LIMIT_PCT = 0.10


@dataclass
class Position:
    symbol: str
    shares: int = 0          # 总持仓股数
    available: int = 0       # 可卖股数（T+1：当日买入被冻结）
    cost: float = 0.0        # 持仓成本（元/股，含成本摊薄）

    def avg_price(self) -> float:
        return self.cost if self.shares else 0.0

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "shares": self.shares,
            "available": self.available,
            "cost": round(self.cost, 4),
        }


@dataclass
class Order:
    symbol: str
    side: str                # buy / sell
    shares: int              # 委托股数（整数手）
    price: float             # 委托价（限价）
    def __post_init__(self) -> None:
        self.shares = round(self.shares)


@dataclass
class Trade:
    symbol: str
    side: str
    shares: int
    price: float             # 实际成交价（含滑点）
    costs: Dict[str, float]  # 成本明细
    date: str
    pnl: Optional[float] = None  # 卖出时已实现盈亏（扣交易成本）

    def to_dict(self) -> dict:
        d = {
            "symbol": self.symbol,
            "side": self.side,
            "shares": self.shares,
            "price": round(self.price, 4),
            "costs": {k: round(v, 4) for k, v in self.costs.items()},
            "date": self.date,
        }
        if self.pnl is not None:
            d["pnl"] = round(self.pnl, 4)
        return d


class OrderRejected(Exception):
    """委托被拒绝（资金/持仓不足、涨跌停、非交易状态等）。"""


class Account:
    """股票账户：现金 + 持仓 + T+1 撮合。"""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        cost_calculator: Optional[CostCalculator] = None,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = self.initial_cash
        self.positions: Dict[str, Position] = {}
        self.cost_calculator = cost_calculator or CostCalculator()
        self.trades: List[Trade] = []
        self.realized_pnl: float = 0.0  # 累计已实现盈亏
        self._daily_suspended: set = set()  # 当日停牌标的
        self._daily_limit_up: set = set()   # 当日涨停标的
        self._daily_limit_down: set = set() # 当日跌停标的

    # ------------------------------------------------------------------ #
    # 状态维护（由回测引擎按交易日更新）
    # ------------------------------------------------------------------ #
    def set_daily_states(
        self,
        suspended: set,
        limit_up: set,
        limit_down: set,
    ) -> None:
        self._daily_suspended = suspended
        self._daily_limit_up = limit_up
        self._daily_limit_down = limit_down

    def settle(self) -> None:
        """日终结算：T+1 解冻当日买入（下一交易日可卖）。"""
        for pos in self.positions.values():
            pos.available = pos.shares

    # ------------------------------------------------------------------ #
    # 查询
    # ------------------------------------------------------------------ #
    def market_value(self, prices: Dict[str, float]) -> float:
        return sum(pos.shares * prices.get(s, pos.avg_price()) for s, pos in self.positions.items())

    def total_value(self, prices: Dict[str, float]) -> float:
        return self.cash + self.market_value(prices)

    # ------------------------------------------------------------------ #
    # 下单（撮合）
    # ------------------------------------------------------------------ #
    def order(
        self,
        symbol: str,
        side: str,
        shares: int,
        limit_price: Optional[float] = None,
        date: str = "",
    ) -> Optional[Trade]:
        """提交市价/限价委托并撮合，返回成交 Trade；被拒绝返回 None。"""
        if shares <= 0 or shares % 100 != 0:
            raise OrderRejected(f"股数必须为正整数手（100 的倍数），收到 {shares}")

        if symbol in self._daily_suspended:
            return None  # 停牌不成交
        if side == "buy" and symbol in self._daily_limit_up:
            return None  # 涨停无法买入
        if side == "sell" and symbol in self._daily_limit_down:
            return None  # 跌停无法卖出

        ref_price = limit_price
        if ref_price is None:
            raise OrderRejected("市价单需要提供参考价（回测按当前价撮合）")

        is_buy = side == "buy"
        exec_price = self.cost_calculator.execution_price(ref_price, is_buy)
        realized: Optional[float] = None  # 卖出时记录已实现盈亏

        if side == "buy":
            # 先按预估成本校验现金，再计算实际可买股数
            cost_info = self.cost_calculator.transaction_costs(exec_price, shares, is_buy=True)
            total_cost = exec_price * shares + cost_info["total"]
            if total_cost > self.cash + 1e-6:
                # 资金不足：尝试按可用现金买入最大整手
                max_shares = self._max_buyable(exec_price)
                if max_shares <= 0:
                    return None
                shares = max_shares
                cost_info = self.cost_calculator.transaction_costs(exec_price, shares, is_buy=True)
                total_cost = exec_price * shares + cost_info["total"]
            if shares < 100:
                return None
            self.cash -= total_cost
            pos = self.positions.setdefault(
                symbol, Position(symbol=symbol, shares=0, available=0, cost=0.0)
            )
            # 成本摊薄含买入手续费，卖出时按持仓成本口径扣减
            new_cost_total = pos.cost * pos.shares + exec_price * shares + cost_info["total"]
            new_shares = pos.shares + shares
            pos.cost = new_cost_total / new_shares if new_shares else 0.0
            pos.shares = new_shares
            pos.available = pos.available  # 当日买入不计入可用（T+1）
        else:  # sell
            pos = self.positions.get(symbol)
            if pos is None or pos.shares == 0:
                return None
            if shares > pos.available:
                shares = pos.available  # 只能卖可用股数
            if shares < 100:
                return None
            proceeds = exec_price * shares
            cost_info = self.cost_calculator.transaction_costs(exec_price, shares, is_buy=False)
            # 卖出先记已实现盈亏（成交额 - 卖出成本 - 持仓成本），再扣减持仓
            realized = proceeds - cost_info["total"] - pos.cost * shares
            self.realized_pnl += realized
            self.cash += proceeds - cost_info["total"]
            # 平均持仓成本不因卖出而改变（剩余持仓仍按原摊薄成本计）
            pos.shares -= shares
            pos.available -= shares
            if pos.shares <= 0:
                self.positions.pop(symbol, None)

        trade = Trade(
            symbol=symbol,
            side=side,
            shares=shares,
            price=exec_price,
            costs=cost_info,
            date=date,
            pnl=realized if side == "sell" else None,
        )
        self.trades.append(trade)
        return trade

    def _max_buyable(self, exec_price: float) -> int:
        """按剩余现金可买入的最大整手股数。"""
        commission_rate = self.cost_calculator.rates.commission_rate
        transfer_rate = self.cost_calculator.rates.transfer_fee_rate
        fee_rate = commission_rate + transfer_rate
        per_hand_cost = exec_price * 100 * (1 + fee_rate)
        hands = int(self.cash // per_hand_cost) if per_hand_cost > 0 else 0
        return max(hands * 100, 0)

    def to_dict(self, prices: Optional[Dict[str, float]] = None) -> dict:
        prices = prices or {}
        positions = []
        for symbol, pos in self.positions.items():
            d = pos.to_dict()
            d["market_value"] = round(pos.shares * prices.get(symbol, pos.avg_price()), 4)
            d["unrealized_pnl"] = round(
                pos.shares * (prices.get(symbol, pos.avg_price()) - pos.avg_price()), 4
            )
            positions.append(d)
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 4),
            "market_value": round(self.market_value(prices), 4),
            "total_value": round(self.total_value(prices), 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "positions": positions,
        }
