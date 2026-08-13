"""期货账户与撮合模型（V1.3 期货回测补全）。

对标开发计划 §4.2 期货账户/持仓 + 多空 + 保证金（主力合约）：
- 多空双向持仓（净仓模型：买入平空/开多，卖出平多/开空）
- 保证金占用（initial margin = 合约数 × 乘数 × 价格 × 保证金比例）
- 逐日盯市（mark-to-market）：每日收盘按市价核算浮动盈亏与权益
- 强平（forced liquidation）：权益 ≤ 维持保证金时平掉全部持仓
- 按手固定手续费（futures_commission_per_lot）

模型简化声明（与股票/基金一致，离线演示与策略研究口径）：
- 主力合约连续回测，不处理交割/换月；
- 无涨跌停与 T+1 限制（期货可当日开平），不做日内价格限制；
- 保证金为「锁定权益」，不另从现金扣除（权益 = 现金余额 + 浮动盈亏）。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .account import OrderRejected
from .costs import CostCalculator, CostRates


@dataclass
class FuturesPosition:
    """单一期货合约持仓（同方向合并，净仓）。"""

    symbol: str
    direction: str          # long / short
    contracts: int          # 持仓手数
    avg_entry: float        # 开仓均价（含成本摊薄）
    open_date: str = ""

    def to_dict(self, multiplier: float = 1.0, price: Optional[float] = None) -> dict:
        floating = 0.0
        if price is not None:
            sign = 1.0 if self.direction == "long" else -1.0
            floating = (price - self.avg_entry) * self.contracts * multiplier * sign
        return {
            "symbol": self.symbol,
            "direction": self.direction,
            "contracts": self.contracts,
            "avg_entry": round(self.avg_entry, 4),
            "open_date": self.open_date,
            "multiplier": multiplier,
            "floating_pnl": round(floating, 4),
        }


@dataclass
class FuturesTrade:
    """期货成交记录。"""

    symbol: str
    side: str               # buy / sell（订单方向）
    direction: str          # 受影响持仓方向 long / short
    contracts: int
    price: float            # 实际成交价（含滑点）
    costs: Dict[str, float]
    date: str
    pnl: Optional[float] = None  # 平仓时已实现盈亏
    forced: bool = False         # 是否强平触发

    def to_dict(self) -> dict:
        d = {
            "symbol": self.symbol,
            "side": self.side,
            "direction": self.direction,
            "contracts": self.contracts,
            "price": round(self.price, 4),
            "costs": {k: round(v, 4) for k, v in self.costs.items()},
            "date": self.date,
            "forced": self.forced,
        }
        if self.pnl is not None:
            d["pnl"] = round(self.pnl, 4)
        return d


class FuturesAccount:
    """期货账户：现金 + 多空净仓 + 保证金 + 逐日盯市 + 强平。"""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        cost_calculator: Optional[CostCalculator] = None,
        multipliers: Optional[Dict[str, float]] = None,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = self.initial_cash
        self.cost_calculator = cost_calculator or CostCalculator()
        self.rates: CostRates = self.cost_calculator.rates
        self.multipliers: Dict[str, float] = dict(multipliers or {})
        self.positions: Dict[str, FuturesPosition] = {}
        self.trades: List[FuturesTrade] = []
        self.realized_pnl: float = 0.0
        self.forced_liquidations: int = 0
        self._prices: Dict[str, float] = {}  # 当日各标的市价（由引擎每日更新）

    # ------------------------------------------------------------------ #
    # 价格维护（由引擎按交易日更新）
    # ------------------------------------------------------------------ #
    def update_prices(self, prices: Dict[str, float]) -> None:
        self._prices = dict(prices)

    def _price(self, symbol: str) -> Optional[float]:
        return self._prices.get(symbol)

    def _multiplier(self, symbol: str) -> float:
        return float(self.multipliers.get(symbol, 1.0))

    # ------------------------------------------------------------------ #
    # 保证金 / 盈亏 / 权益
    # ------------------------------------------------------------------ #
    def _commission(self, contracts: int) -> float:
        return contracts * self.rates.futures_commission_per_lot

    def margin_occupied(self, prices: Optional[Dict[str, float]] = None) -> float:
        prices = prices if prices is not None else self._prices
        total = 0.0
        for sym, pos in self.positions.items():
            p = prices.get(sym)
            if p is None:
                continue
            total += pos.contracts * self._multiplier(sym) * p * self.rates.futures_margin_rate
        return total

    def floating_pnl(self, prices: Optional[Dict[str, float]] = None) -> float:
        prices = prices if prices is not None else self._prices
        total = 0.0
        for sym, pos in self.positions.items():
            p = prices.get(sym)
            if p is None:
                continue
            sign = 1.0 if pos.direction == "long" else -1.0
            total += (p - pos.avg_entry) * pos.contracts * self._multiplier(sym) * sign
        return total

    def equity(self, prices: Optional[Dict[str, float]] = None) -> float:
        """账户权益 = 现金余额 + 浮动盈亏。"""
        return self.cash + self.floating_pnl(prices)

    def available(self, prices: Optional[Dict[str, float]] = None) -> float:
        """可用资金 = 权益 - 已占用保证金。"""
        return self.equity(prices) - self.margin_occupied(prices)

    def _max_openable(self, symbol: str, price: float) -> int:
        """按当前权益可新开的最大手数（含手续费约束）。"""
        m = self._multiplier(symbol)
        margin_per = m * price * self.rates.futures_margin_rate
        per_lot = self.rates.futures_commission_per_lot
        base_available = self.available()
        if margin_per + per_lot <= 0:
            return 0
        return int(base_available // (margin_per + per_lot))

    # ------------------------------------------------------------------ #
    # 下单（净仓模型）
    # ------------------------------------------------------------------ #
    def order_future(
        self,
        symbol: str,
        contracts: int,
        side: str,
        limit_price: Optional[float] = None,
        date: str = "",
    ) -> Optional[FuturesTrade]:
        """提交期货委托（净仓）：买入平空/开多，卖出平多/开空。

        返回成交 Trade；资金/保证金不足且无法开仓时返回 None；非法参数抛 OrderRejected。
        """
        if contracts is None or int(contracts) != contracts or contracts <= 0:
            raise OrderRejected(f"期货手数必须为正整数，收到 {contracts}")
        contracts = int(contracts)
        if side not in ("buy", "sell"):
            raise OrderRejected(f"期货方向必须为 buy/sell，收到 {side!r}")

        is_buy = side == "buy"
        if limit_price is None:
            limit_price = self._price(symbol)
        if limit_price is None or limit_price <= 0:
            return None
        exec_price = self.cost_calculator.execution_price(limit_price, is_buy)

        # 该标的以成交价计入当日市价，供保证金/权益计算
        prices = dict(self._prices)
        prices[symbol] = exec_price

        pos = self.positions.get(symbol)
        # 净仓：若与当前持仓方向相反，先平掉反向部分
        opposite = (side == "buy" and pos is not None and pos.direction == "short") or (
            side == "sell" and pos is not None and pos.direction == "long"
        )
        if opposite:
            close_qty = min(contracts, pos.contracts)
            self._close(symbol, close_qty, exec_price, date, forced=False)
            contracts -= close_qty
            pos = self.positions.get(symbol)

        if contracts <= 0:
            # 仅平仓，无新开仓
            return self.trades[-1] if self.trades else None

        return self._open(symbol, contracts, side, exec_price, date, prices)

    def _open(
        self,
        symbol: str,
        contracts: int,
        side: str,
        exec_price: float,
        date: str,
        prices: Dict[str, float],
    ) -> Optional[FuturesTrade]:
        direction = "long" if side == "buy" else "short"
        # 资金约束：可开手数不超过最大值
        max_c = self._max_openable(symbol, exec_price)
        if max_c <= 0:
            return None
        contracts = min(contracts, max_c)
        if contracts <= 0:
            return None
        commission = self._commission(contracts)
        self.cash -= commission

        multiplier = self._multiplier(symbol)
        pos = self.positions.get(symbol)
        if pos is not None and pos.direction == direction:
            total = pos.contracts + contracts
            pos.avg_entry = (pos.avg_entry * pos.contracts + exec_price * contracts) / total
            pos.contracts = total
        else:
            self.positions[symbol] = FuturesPosition(
                symbol=symbol,
                direction=direction,
                contracts=contracts,
                avg_entry=exec_price,
                open_date=date,
            )

        trade = FuturesTrade(
            symbol=symbol,
            side=side,
            direction=direction,
            contracts=contracts,
            price=exec_price,
            costs={"commission": round(commission, 4)},
            date=date,
        )
        self.trades.append(trade)
        return trade

    def _close(
        self,
        symbol: str,
        contracts: int,
        exec_price: float,
        date: str,
        forced: bool = False,
    ) -> Optional[FuturesTrade]:
        pos = self.positions.get(symbol)
        if pos is None or contracts <= 0:
            return None
        contracts = min(contracts, pos.contracts)
        multiplier = self._multiplier(symbol)
        sign = 1.0 if pos.direction == "long" else -1.0
        realized = (exec_price - pos.avg_entry) * contracts * multiplier * sign
        commission = self._commission(contracts)
        self.cash += realized
        self.cash -= commission
        self.realized_pnl += realized
        pos.contracts -= contracts
        if pos.contracts <= 0:
            self.positions.pop(symbol, None)

        # 平多 → 卖出；平空 → 买入
        close_side = "sell" if pos.direction == "long" else "buy"
        trade = FuturesTrade(
            symbol=symbol,
            side=close_side,
            direction=pos.direction,
            contracts=contracts,
            price=exec_price,
            costs={"commission": round(commission, 4)},
            date=date,
            pnl=realized,
            forced=forced,
        )
        self.trades.append(trade)
        return trade

    def close_all(self, prices: Dict[str, float], date: str = "", forced: bool = False) -> int:
        """平掉全部持仓（强平或策略主动清仓）。返回平仓手数。"""
        closed = 0
        for sym in list(self.positions.keys()):
            pos = self.positions[sym]
            p = prices.get(sym) or pos.avg_entry
            self._close(sym, pos.contracts, p, date, forced=forced)
            closed += pos.contracts
        return closed

    # ------------------------------------------------------------------ #
    # 日终盯市与强平
    # ------------------------------------------------------------------ #
    def settle(self, prices: Dict[str, float]) -> None:
        """逐日盯市：更新市价，若权益 ≤ 维持保证金则强平全部持仓。"""
        self.update_prices(prices)
        if not self.positions:
            return
        equity = self.equity(prices)
        margin = self.margin_occupied(prices)
        maintenance = margin * self.rates.futures_maintenance_ratio
        if margin > 0 and equity <= maintenance:
            self.close_all(prices, date="", forced=True)
            self.forced_liquidations += 1

    # ------------------------------------------------------------------ #
    # 序列化
    # ------------------------------------------------------------------ #
    def to_dict(self, prices: Optional[Dict[str, float]] = None) -> dict:
        prices = prices if prices is not None else self._prices
        positions = []
        for sym, pos in self.positions.items():
            positions.append(pos.to_dict(self._multiplier(sym), prices.get(sym)))
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 4),
            "equity": round(self.equity(prices), 4),
            "margin_occupied": round(self.margin_occupied(prices), 4),
            "floating_pnl": round(self.floating_pnl(prices), 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "forced_liquidations": self.forced_liquidations,
            "positions": positions,
        }
