"""场外基金账户与申购/赎回模型（M2 回测引擎 · 基金）。

对标开发计划 §4.2 与 V1.2「基金回测」：
- 场外基金按单位净值（NAV）计价：申购按金额、赎回按份额
- 申购费（前端，默认 0.15% 一折）按申购金额收取；赎回费（默认 0.5%）按赎回净值收取
- T 日下单按 T 日净值确认，T+1 确认（申购份额到账 / 赎回资金到账）
- 无涨跌停、无整手限制（份额可为小数）
- 支持单日单只基金限购（暂停大额申购），0 表示不限
- 赎回费率按持有期限分档为 V1.3 预留，当前按统一费率简化

V1.0 只实现场外开放式基金；场内 ETF/LOF 与股票同机制（
CostCalculator + Account），仅费率配置不同。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .costs import CostRates


@dataclass
class FundPosition:
    """场外基金持仓（份额可小数）。"""

    symbol: str
    shares: float = 0.0
    cost: float = 0.0  # 持仓成本（元/份，含申购费摊薄）

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "shares": round(self.shares, 4),
            "cost": round(self.cost, 4),
        }


@dataclass
class FundTrade:
    """一笔基金申购/赎回成交记录。"""

    symbol: str
    side: str           # subscribe / redeem
    amount: float       # 申购金额（元）；赎回时为 0
    shares: float       # 份额（申购=确认份额，赎回=赎回份额）
    nav: float          # 确认净值
    fee: float          # 手续费
    date: str           # 下单日（T 日）
    confirm_date: str   # 确认日（T+1）
    pnl: Optional[float] = None  # 赎回时已实现盈亏（扣手续费）

    def to_dict(self) -> dict:
        d = {
            "symbol": self.symbol,
            "side": self.side,
            "amount": round(self.amount, 2),
            "shares": round(self.shares, 4),
            "nav": round(self.nav, 4),
            "fee": round(self.fee, 4),
            "date": self.date,
            "confirm_date": self.confirm_date,
        }
        if self.pnl is not None:
            d["pnl"] = round(self.pnl, 4)
        return d


class FundOrderRejected(Exception):
    """基金委托被拒绝（金额非法、净值无效、限购等）。"""


@dataclass
class _PendingSubscription:
    symbol: str
    shares: float
    nav: float
    amount: float  # 申购总金额（含手续费，用于成本摊薄）
    date: str


@dataclass
class _PendingRedemption:
    symbol: str
    shares: float
    proceeds: float  # 扣除赎回费后到账金额
    nav: float
    date: str


class FundAccount:
    """场外基金账户：现金 + 份额持仓 + T+1 确认的申购/赎回队列。"""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        *,
        cost_rates: Optional[CostRates] = None,
        max_subscription_amount: float = 0.0,
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = self.initial_cash
        rates = cost_rates or CostRates()
        self.subscription_fee_rate = rates.subscription_fee_rate
        self.redemption_fee_rate = rates.redemption_fee_rate
        self.max_subscription_amount = float(max_subscription_amount)

        self.positions: Dict[str, FundPosition] = {}
        self.trades: List[FundTrade] = []
        self.realized_pnl: float = 0.0
        self._pending_subs: List[_PendingSubscription] = []
        self._pending_reds: List[_PendingRedemption] = []
        self._today_sub_amount: Dict[str, float] = {}  # 当日已申购金额（限购校验）

    # ------------------------------------------------------------------ #
    # 交易
    # ------------------------------------------------------------------ #
    def subscribe(
        self,
        symbol: str,
        amount: float,
        nav: float,
        date: str,
        confirm_date: str = "",
    ) -> Optional[FundTrade]:
        """按金额申购。返回成交记录；被拒绝（金额非法/净值无效/限购/现金不足）返回 None。"""
        if amount <= 0:
            raise FundOrderRejected(f"申购金额必须为正，收到 {amount}")
        if not nav or nav <= 0:
            return None

        # 限购：单日单只基金申购金额上限
        if self.max_subscription_amount > 0:
            used = self._today_sub_amount.get(symbol, 0.0)
            amount = min(amount, max(self.max_subscription_amount - used, 0.0))
        # 现金不足：按可用现金部分成交
        amount = min(amount, self.cash)
        if amount <= 0:
            return None

        fee = amount * self.subscription_fee_rate
        shares = (amount - fee) / nav
        if shares <= 1e-9:
            return None

        self.cash -= amount
        self._today_sub_amount[symbol] = self._today_sub_amount.get(symbol, 0.0) + amount
        self._pending_subs.append(
            _PendingSubscription(
                symbol=symbol, shares=shares, nav=nav, amount=amount, date=date
            )
        )
        trade = FundTrade(
            symbol=symbol,
            side="subscribe",
            amount=amount,
            shares=shares,
            nav=nav,
            fee=fee,
            date=date,
            confirm_date=confirm_date or date,
        )
        self.trades.append(trade)
        return trade

    def redeem(
        self,
        symbol: str,
        shares: float,
        nav: float,
        date: str,
        confirm_date: str = "",
    ) -> Optional[FundTrade]:
        """按份额赎回。返回成交记录；被拒绝（无持仓/净值无效）返回 None。"""
        pos = self.positions.get(symbol)
        if pos is None or pos.shares <= 0:
            return None
        if not nav or nav <= 0:
            return None

        shares = min(shares, pos.shares)
        if shares <= 1e-9:
            return None

        proceeds_gross = shares * nav
        fee = proceeds_gross * self.redemption_fee_rate
        proceeds = proceeds_gross - fee
        # 已实现盈亏 = 到账金额 - 持仓成本（含申购费摊薄）
        realized = proceeds - pos.cost * shares
        self.realized_pnl += realized

        pos.shares -= shares  # 当日锁定，T+1 资金到账
        self._pending_reds.append(
            _PendingRedemption(symbol=symbol, shares=shares, proceeds=proceeds, nav=nav, date=date)
        )
        if pos.shares <= 1e-9:
            self.positions.pop(symbol, None)

        trade = FundTrade(
            symbol=symbol,
            side="redeem",
            amount=0.0,
            shares=shares,
            nav=nav,
            fee=fee,
            date=date,
            confirm_date=confirm_date or date,
            pnl=realized,
        )
        self.trades.append(trade)
        return trade

    # ------------------------------------------------------------------ #
    # 状态维护（由回测引擎按交易日驱动）
    # ------------------------------------------------------------------ #
    def confirm_pending(self) -> None:
        """T+1 确认：申购份额入账、赎回资金到账。"""
        for p in self._pending_subs:
            pos = self.positions.setdefault(p.symbol, FundPosition(symbol=p.symbol))
            # 成本摊薄：按申购总金额（含申购费），与股票账户口径一致
            new_cost_total = pos.cost * pos.shares + p.amount
            pos.shares += p.shares
            pos.cost = new_cost_total / pos.shares if pos.shares else 0.0
        self._pending_subs.clear()

        for p in self._pending_reds:
            self.cash += p.proceeds
        self._pending_reds.clear()

    def start_new_day(self) -> None:
        """新交易日：重置当日限购计数。"""
        self._today_sub_amount.clear()

    # ------------------------------------------------------------------ #
    # 估值
    # ------------------------------------------------------------------ #
    def market_value(self, navs: Dict[str, float]) -> float:
        return sum(pos.shares * navs.get(s, pos.cost) for s, pos in self.positions.items())

    def pending_value(self, navs: Dict[str, float]) -> float:
        """待确认资产估值：申购按确认净值、赎回按到账金额。"""
        sub_val = sum(p.shares * navs.get(p.symbol, p.nav) for p in self._pending_subs)
        red_val = sum(p.proceeds for p in self._pending_reds)
        return sub_val + red_val

    def total_value(self, navs: Dict[str, float]) -> float:
        return self.cash + self.market_value(navs) + self.pending_value(navs)

    # ------------------------------------------------------------------ #
    def to_dict(self, navs: Optional[Dict[str, float]] = None) -> dict:
        navs = navs or {}
        positions = []
        for symbol, pos in self.positions.items():
            d = pos.to_dict()
            nav = navs.get(symbol, pos.cost)
            d["market_value"] = round(pos.shares * nav, 4)
            d["unrealized_pnl"] = round(pos.shares * (nav - pos.cost), 4)
            positions.append(d)
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 4),
            "market_value": round(self.market_value(navs), 4),
            "pending_value": round(self.pending_value(navs), 4),
            "total_value": round(self.total_value(navs), 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "subscription_fee_rate": self.subscription_fee_rate,
            "redemption_fee_rate": self.redemption_fee_rate,
            "positions": positions,
        }
