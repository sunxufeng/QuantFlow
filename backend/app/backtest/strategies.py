"""内置回测策略（M2 交易 API）。

对标开发计划 §4.2「交易 API」：策略注册表按名称构建可复用策略，
供 ``POST /api/backtest/run`` 使用。

内置策略：
- ``buy_hold``：首日按份额/全仓买入，末日卖出（股票）
- ``ma_cross``：MA5 上穿 MA20 买入、下穿卖出（股票）
- ``fund_dingtou``：场外基金定投（每月首个交易日申购固定金额）
- ``futures_ma_cross``：期货均线金叉做多、死叉做空（多空净仓，V1.3）
"""

from __future__ import annotations

from typing import Any, Callable, Dict

from .engine import BacktestContext, Strategy


def _lot_floor(cash: float) -> int:
    """全仓下单股数：向下取整到整手（100 的倍数），账户再按价格缩减。

    避免 int(cash) 非整手导致 OrderRejected（如现金 970202 元）。
    """
    return int(float(cash) // 100) * 100


class BuyHoldStrategy(Strategy):
    """买入持有：首日买入，末日全部卖出。"""

    def __init__(self, shares: int = 0, symbol: str = "") -> None:
        # shares=0 表示首日按全部可用现金买入最大整手
        self.shares = int(shares or 0)
        self.symbol = symbol

    def initialize(self, ctx: BacktestContext) -> None:
        self.bought = False

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        if not self.bought:
            pos = ctx.account.positions.get(sym)
            if self.shares > 0:
                ctx.order(sym, self.shares, "buy")
            else:
                # 全仓：先按现金试买超大整手，账户自动按可用资金缩减
                shares = _lot_floor(ctx.account.cash)
                if shares > 0:
                    ctx.order(sym, shares, "buy")
            self.bought = True
        elif ctx.date == ctx.calendar[-1]:
            pos = ctx.account.positions.get(sym)
            if pos:
                ctx.order(sym, pos.shares, "sell")


def _ma(bars, n: int) -> float:
    closes = [b.close for b in bars]
    if len(closes) < n:
        return float("nan")
    return sum(closes[-n:]) / n


class MaCrossStrategy(Strategy):
    """均线金叉/死叉：MA5 上穿 MA20 全仓买入，下穿全部卖出。"""

    def __init__(self, fast: int = 5, slow: int = 20, symbol: str = "") -> None:
        self.fast = int(fast)
        self.slow = int(slow)
        self.symbol = symbol

    def initialize(self, ctx: BacktestContext) -> None:
        self.prev_diff: float = 0.0
        self.have_prev = False

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        bars = ctx.history(sym, self.slow)
        if len(bars) < self.slow:
            return
        fast_ma = _ma(bars, self.fast)
        slow_ma = _ma(bars, self.slow)
        if fast_ma != fast_ma or slow_ma != slow_ma:  # NaN
            return
        diff = fast_ma - slow_ma
        if self.have_prev:
            if self.prev_diff <= 0 and diff > 0:
                # 金叉：全仓买入（整手）
                shares = _lot_floor(ctx.account.cash)
                if shares > 0:
                    ctx.order(sym, shares, "buy")
            elif self.prev_diff >= 0 and diff < 0:
                # 死叉：全部卖出
                pos = ctx.account.positions.get(sym)
                if pos:
                    ctx.order(sym, pos.shares, "sell")
        self.prev_diff = diff
        self.have_prev = True


class FundDingTouStrategy(Strategy):
    """场外基金定投：每月首个交易日申购固定金额；末日可全赎。"""

    def __init__(
        self,
        amount: float = 1000.0,
        symbol: str = "",
        redeem_on_last_day: bool = True,
    ) -> None:
        self.amount = float(amount)
        self.symbol = symbol
        self.redeem_on_last_day = bool(redeem_on_last_day)

    def initialize(self, ctx: BacktestContext) -> None:
        self.last_month = ""

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        month = ctx.date[:7]
        if month != self.last_month:
            # 当月首个交易日：申购
            ctx.subscribe(sym, self.amount)
            self.last_month = month
        if self.redeem_on_last_day and ctx.date == ctx.calendar[-1]:
            fa = ctx.fund_account
            if fa and sym in fa.positions:
                ctx.redeem(sym, fa.positions[sym].shares)


class FundValueAvgStrategy(Strategy):
    """价值平均定投（基金）：目标市值线性增长，每月首个交易日补足/赎回差额。

    与 ``fund_dingtou``（每期固定金额）不同，价值平均以「目标市值」为锚：
    目标 = amount * 期数；当期基金市值低于目标则申购差额（受现金约束），
    高于目标则赎回超出部分（受持仓约束）。现金作为蓄水池不被赎回。
    """

    def __init__(
        self,
        amount: float = 1000.0,
        symbol: str = "",
        redeem_on_last_day: bool = True,
    ) -> None:
        self.amount = float(amount)
        self.symbol = symbol
        self.redeem_on_last_day = bool(redeem_on_last_day)

    def initialize(self, ctx: BacktestContext) -> None:
        self.last_month = ""
        self.period = 0

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        month = ctx.date[:7]
        is_last = ctx.date == ctx.calendar[-1]

        # 月度调仓（仅跨月时执行一次）
        if month != self.last_month:
            self.last_month = month
            self.period += 1

            fa = ctx.fund_account
            if fa is None:
                return
            bar = ctx.bar(sym)
            nav = bar.close if bar else 0.0
            if nav <= 0:
                return

            # 已投入市值（不含现金蓄水池）
            invested = (fa.positions[sym].shares if sym in fa.positions else 0.0) * nav
            target = self.amount * self.period
            delta = target - invested
            if delta > 0:
                # 补足：申购差额（受可用现金约束）
                avail = fa.cash
                if avail > 0:
                    ctx.subscribe(sym, min(delta, avail))
            else:
                # 赎回超出部分（受可用份额约束）
                pos = fa.positions.get(sym)
                if pos and pos.shares > 0:
                    ctx.redeem(sym, min(-delta / nav, pos.shares))

        # 末日强制赎回（不受月度守卫影响，单月回测也能清仓）
        if self.redeem_on_last_day and is_last:
            fa2 = ctx.fund_account
            if fa2 and sym in fa2.positions:
                ctx.redeem(sym, fa2.positions[sym].shares)


def _buy_hold_factory(params: Dict[str, Any]) -> Strategy:
    return BuyHoldStrategy(
        shares=int(params.get("shares", 0)),
        symbol=str(params.get("symbol", "")),
    )


def _ma_cross_factory(params: Dict[str, Any]) -> Strategy:
    return MaCrossStrategy(
        fast=int(params.get("fast", 5)),
        slow=int(params.get("slow", 20)),
        symbol=str(params.get("symbol", "")),
    )


def _fund_dingtou_factory(params: Dict[str, Any]) -> Strategy:
    return FundDingTouStrategy(
        amount=float(params.get("amount", 1000.0)),
        symbol=str(params.get("symbol", "")),
        redeem_on_last_day=bool(params.get("redeem_on_last_day", True)),
    )


def _fund_value_avg_factory(params: Dict[str, Any]) -> Strategy:
    return FundValueAvgStrategy(
        amount=float(params.get("amount", 1000.0)),
        symbol=str(params.get("symbol", "")),
        redeem_on_last_day=bool(params.get("redeem_on_last_day", True)),
    )


class FuturesMaCrossStrategy(Strategy):
    """期货均线金叉/死叉：金叉做多、死叉做空（多空净仓切换）。

    与股票 ``MaCrossStrategy`` 不同：使用 ``ctx.order_future``（多空/保证金语义），
    金叉平空开多、死叉平多开空；权益与强平由 FuturesAccount 管理。
    """

    def __init__(
        self, fast: int = 5, slow: int = 20, symbol: str = "", contracts: int = 1
    ) -> None:
        self.fast = int(fast)
        self.slow = int(slow)
        self.symbol = symbol
        self.contracts = max(int(contracts or 1), 1)

    def initialize(self, ctx: BacktestContext) -> None:
        self.prev_diff: float = 0.0
        self.have_prev = False

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        bars = ctx.history(sym, self.slow)
        if len(bars) < self.slow:
            return
        fast_ma = _ma(bars, self.fast)
        slow_ma = _ma(bars, self.slow)
        if fast_ma != fast_ma or slow_ma != slow_ma:  # NaN
            return
        diff = fast_ma - slow_ma
        if self.have_prev:
            if self.prev_diff <= 0 and diff > 0:
                # 金叉：平空开多
                ctx.order_future(sym, self.contracts, "buy")
            elif self.prev_diff >= 0 and diff < 0:
                # 死叉：平多开空
                ctx.order_future(sym, self.contracts, "sell")
        self.prev_diff = diff
        self.have_prev = True


def _futures_ma_cross_factory(params: Dict[str, Any]) -> Strategy:
    return FuturesMaCrossStrategy(
        fast=int(params.get("fast", 5)),
        slow=int(params.get("slow", 20)),
        symbol=str(params.get("symbol", "")),
        contracts=int(params.get("contracts", 1)),
    )


# 策略注册表：名称 -> 工厂（由 params 构建策略实例）
STRATEGY_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Strategy]] = {
    "buy_hold": _buy_hold_factory,
    "ma_cross": _ma_cross_factory,
    "fund_dingtou": _fund_dingtou_factory,
    "fund_value_avg": _fund_value_avg_factory,
    "futures_ma_cross": _futures_ma_cross_factory,
}


def get_strategy(name: str) -> Callable[[Dict[str, Any]], Strategy]:
    """按名称查找策略工厂（KeyError 由 API 层转 404/422）。"""
    if name not in STRATEGY_REGISTRY:
        raise KeyError(f"未知策略: {name}")
    return STRATEGY_REGISTRY[name]
