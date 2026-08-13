"""场外基金账户与申购/赎回模型（M2 回测引擎 · 基金）。

对标开发计划 §4.2 与 V1.2「基金回测」：
- 场外基金按单位净值（NAV）计价：申购按金额、赎回按份额
- 申购费（前端，默认 0.15% 一折）按申购金额收取；赎回费（默认 0.5%）按赎回净值收取
- T 日下单按 T 日净值确认，T+1 确认（申购份额到账 / 赎回资金到账）
- 无涨跌停、无整手限制（份额可为小数）
- 支持单日单只基金限购（暂停大额申购），0 表示不限
- 赎回费按持有期分档（V1.2）：默认等效统一 0.5%，可配阶梯（如 7 日内 1.5%）
- 分笔成本（FIFO）：多次申购按批次记录成本与确认日，赎回按先进先出计算
- 基金分红（V1.2）：现金分红（入现金）/ 红利再投（按除息净值增份），默认现金

V1.0 只实现场外开放式基金；场内 ETF/LOF 与股票同机制（
CostCalculator + Account），仅费率配置不同。
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass
from typing import Dict, List, Optional

from .costs import CostRates, resolve_redemption_fee_rate


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
class _FundLot:
    """一只基金的一笔确认份额批次（FIFO 成本基础）。"""

    symbol: str
    shares: float
    cost_per_share: float  # 含申购费的单份成本（元/份）
    acquire_date: str      # 确认日（T+1）

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol,
            "shares": round(self.shares, 4),
            "cost_per_share": round(self.cost_per_share, 6),
            "acquire_date": self.acquire_date,
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
    pnl: Optional[float] = None      # 赎回时已实现盈亏（扣手续费）
    holding_days: Optional[int] = None   # 赎回时持有天数（首笔批次口径）
    fee_rate: Optional[float] = None     # 赎回时实际综合费率

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
        if self.holding_days is not None:
            d["holding_days"] = self.holding_days
        if self.fee_rate is not None:
            d["fee_rate"] = round(self.fee_rate, 6)
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
    confirm_date: str = ""


@dataclass
class _PendingRedemption:
    symbol: str
    shares: float
    proceeds: float  # 扣除赎回费后到账金额
    nav: float
    date: str


def _holding_days(a: Optional[str], b: Optional[str]) -> int:
    """两个日期字符串（YYYY-MM-DD）之间的自然日差；非 ISO 格式回退 0。"""
    if not a or not b:
        return 0
    try:
        da = dt.date.fromisoformat(a)
        db = dt.date.fromisoformat(b)
        return (db - da).days
    except (ValueError, TypeError):
        return 0


class FundAccount:
    """场外基金账户：现金 + 分笔份额持仓 + T+1 确认的申购/赎回队列。"""

    def __init__(
        self,
        initial_cash: float = 1_000_000.0,
        *,
        cost_rates: Optional[CostRates] = None,
        max_subscription_amount: float = 0.0,
        dividend_policy: str = "cash",
    ) -> None:
        self.initial_cash = float(initial_cash)
        self.cash = self.initial_cash
        rates = cost_rates or CostRates()
        self.subscription_fee_rate = rates.subscription_fee_rate
        self.redemption_fee_rate = rates.redemption_fee_rate
        self.redemption_fee_tiers = rates.redemption_fee_tiers
        self.dividend_policy = dividend_policy
        self.max_subscription_amount = float(max_subscription_amount)

        self._lots: Dict[str, List[_FundLot]] = {}  # 分笔持仓（FIFO）
        self.trades: List[FundTrade] = []
        self.realized_pnl: float = 0.0
        self._pending_subs: List[_PendingSubscription] = []
        self._pending_reds: List[_PendingRedemption] = []
        self._today_sub_amount: Dict[str, float] = {}  # 当日已申购金额（限购校验）

    # ------------------------------------------------------------------ #
    # 持仓视图（由分笔批次聚合，向后兼容 positions 接口）
    # ------------------------------------------------------------------ #
    @property
    def positions(self) -> Dict[str, FundPosition]:
        out: Dict[str, FundPosition] = {}
        for sym, lots in self._lots.items():
            total_shares = sum(l.shares for l in lots)
            if total_shares <= 1e-9:
                continue
            total_cost = sum(l.cost_per_share * l.shares for l in lots)
            out[sym] = FundPosition(
                symbol=sym,
                shares=total_shares,
                cost=total_cost / total_shares if total_shares else 0.0,
            )
        return out

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
                symbol=symbol, shares=shares, nav=nav, amount=amount, date=date,
                confirm_date=confirm_date or date,
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
        """按份额赎回（FIFO）。返回成交记录；被拒绝（无持仓/净值无效）返回 None。"""
        lots = self._lots.get(symbol)
        if not lots:
            return None
        if not nav or nav <= 0:
            return None

        available = sum(l.shares for l in lots)
        shares = min(shares, available)
        if shares <= 1e-9:
            return None

        remaining = shares
        realized_total = 0.0
        fee_total = 0.0
        redeemed_shares = 0.0
        first_acquire: Optional[str] = None
        for lot in lots:
            if remaining <= 1e-12:
                break
            take = min(lot.shares, remaining)
            if take <= 1e-12:
                continue
            gross = take * nav
            hd = _holding_days(lot.acquire_date, date)
            rate = resolve_redemption_fee_rate(self.redemption_fee_tiers, hd)
            fee = gross * rate
            proceeds = gross - fee
            realized = proceeds - lot.cost_per_share * take
            realized_total += realized
            fee_total += fee
            redeemed_shares += take
            lot.shares -= take
            remaining -= take
            if first_acquire is None:
                first_acquire = lot.acquire_date

        self._lots[symbol] = [l for l in lots if l.shares > 1e-9]
        if not self._lots[symbol]:
            self._lots.pop(symbol, None)

        self.realized_pnl += realized_total
        proceeds_total = shares * nav - fee_total
        self._pending_reds.append(
            _PendingRedemption(symbol=symbol, shares=redeemed_shares, proceeds=proceeds_total, nav=nav, date=date)
        )
        eff_rate = (fee_total / (shares * nav)) if shares * nav > 0 else 0.0
        trade = FundTrade(
            symbol=symbol,
            side="redeem",
            amount=0.0,
            shares=redeemed_shares,
            nav=nav,
            fee=fee_total,
            date=date,
            confirm_date=confirm_date or date,
            pnl=realized_total,
            holding_days=_holding_days(first_acquire, date) if first_acquire else 0,
            fee_rate=eff_rate,
        )
        self.trades.append(trade)
        return trade

    # ------------------------------------------------------------------ #
    # 分红（V1.2）
    # ------------------------------------------------------------------ #
    def apply_dividend(
        self,
        symbol: str,
        per_share: float,
        nav: float,
        date: str,
        policy: Optional[str] = None,
    ) -> float:
        """除息日分红处理。返回分红金额（元）。

        - cash（默认）：分红计入现金，份额不变（净值已除息，总资产不重复计）
        - reinvest：按除息净值增配份额，单份成本 = 除息净值
        """
        policy = policy or self.dividend_policy
        lots = self._lots.get(symbol)
        if not lots:
            return 0.0
        shares = sum(l.shares for l in lots)
        if shares <= 1e-9 or per_share <= 0:
            return 0.0
        amount = shares * per_share
        if policy == "reinvest" and nav > 0:
            new_shares = amount / nav
            self._lots[symbol].append(
                _FundLot(symbol=symbol, shares=new_shares, cost_per_share=nav, acquire_date=date)
            )
        else:
            self.cash += amount
        return amount

    # ------------------------------------------------------------------ #
    # 状态维护（由回测引擎按交易日驱动）
    # ------------------------------------------------------------------ #
    def confirm_pending(self) -> None:
        """T+1 确认：申购份额入账（分笔批次）、赎回资金到账。"""
        for p in self._pending_subs:
            lot = _FundLot(
                symbol=p.symbol,
                shares=p.shares,
                cost_per_share=(p.amount / p.shares) if p.shares else 0.0,
                acquire_date=p.confirm_date or p.date,
            )
            self._lots.setdefault(p.symbol, []).append(lot)
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
        lots = []
        for symbol, ls in self._lots.items():
            for l in ls:
                lots.append(l.to_dict())
        return {
            "initial_cash": self.initial_cash,
            "cash": round(self.cash, 4),
            "market_value": round(self.market_value(navs), 4),
            "pending_value": round(self.pending_value(navs), 4),
            "total_value": round(self.total_value(navs), 4),
            "realized_pnl": round(self.realized_pnl, 4),
            "subscription_fee_rate": self.subscription_fee_rate,
            "redemption_fee_rate": self.redemption_fee_rate,
            "redemption_fee_tiers": [list(t) for t in self.redemption_fee_tiers],
            "dividend_policy": self.dividend_policy,
            "positions": positions,
            "lots": lots,
        }
