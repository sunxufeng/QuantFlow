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

import math
from typing import Any, Callable, Dict, List

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


def _std(bars, n: int) -> float:
    closes = [b.close for b in bars]
    if len(closes) < n:
        return float("nan")
    window = closes[-n:]
    mean = sum(window) / n
    var = sum((x - mean) ** 2 for x in window) / n
    return math.sqrt(var)


def _rsi(bars, n: int) -> float:
    closes = [b.close for b in bars]
    if len(closes) < n + 1:
        return float("nan")
    window = closes[-(n + 1):]
    gains = 0.0
    losses = 0.0
    for i in range(1, len(window)):
        ch = window[i] - window[i - 1]
        if ch >= 0:
            gains += ch
        else:
            losses += -ch
    avg_gain = gains / n
    avg_loss = losses / n
    if avg_loss == 0:
        return 100.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


class MomentumStrategy(Strategy):
    """动量：过去 lookback 日收益率 > 阈值则持有/买入，否则空仓（股票）。"""

    def __init__(self, lookback: int = 20, threshold: float = 0.0, symbol: str = "") -> None:
        self.lookback = int(lookback)
        self.threshold = float(threshold)
        self.symbol = symbol

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        bars = ctx.history(sym, self.lookback + 1)
        if len(bars) < self.lookback + 1:
            return
        mom = bars[-1].close / bars[0].close - 1.0
        pos = ctx.account.positions.get(sym)
        if mom > self.threshold and not pos:
            shares = _lot_floor(ctx.account.cash)
            if shares > 0:
                ctx.order(sym, shares, "buy")
        elif mom <= self.threshold and pos:
            ctx.order(sym, pos.shares, "sell")


class MeanReversionStrategy(Strategy):
    """均值回归：价格低于 rolling_mean - k*std 买入，高于 rolling_mean + k*std 卖出（股票）。"""

    def __init__(self, window: int = 20, k: float = 2.0, symbol: str = "") -> None:
        self.window = int(window)
        self.k = float(k)
        self.symbol = symbol

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        bars = ctx.history(sym, self.window)
        if len(bars) < self.window:
            return
        mean = _ma(bars, self.window)
        sd = _std(bars, self.window)
        if mean != mean or sd != sd or sd <= 1e-9:
            return
        price = bars[-1].close
        lower = mean - self.k * sd
        upper = mean + self.k * sd
        pos = ctx.account.positions.get(sym)
        if price <= lower and not pos:
            shares = _lot_floor(ctx.account.cash)
            if shares > 0:
                ctx.order(sym, shares, "buy")
        elif price >= upper and pos:
            ctx.order(sym, pos.shares, "sell")


class RsiStrategy(Strategy):
    """RSI：RSI < oversold 买入，RSI > overbought 卖出（股票）。"""

    def __init__(self, period: int = 14, oversold: float = 30.0, overbought: float = 70.0, symbol: str = "") -> None:
        self.period = int(period)
        self.oversold = float(oversold)
        self.overbought = float(overbought)
        self.symbol = symbol

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        bars = ctx.history(sym, self.period + 1)
        if len(bars) < self.period + 1:
            return
        rsi = _rsi(bars, self.period)
        if rsi != rsi:
            return
        pos = ctx.account.positions.get(sym)
        if rsi < self.oversold and not pos:
            shares = _lot_floor(ctx.account.cash)
            if shares > 0:
                ctx.order(sym, shares, "buy")
        elif rsi > self.overbought and pos:
            ctx.order(sym, pos.shares, "sell")


class BollingerStrategy(Strategy):
    """布林带：收盘价跌破下轨买入，突破上轨卖出（股票）。"""

    def __init__(self, window: int = 20, num_std: float = 2.0, symbol: str = "") -> None:
        self.window = int(window)
        self.num_std = float(num_std)
        self.symbol = symbol

    def handle_data(self, ctx: BacktestContext) -> None:
        sym = self.symbol or ctx.symbols()[0]
        bars = ctx.history(sym, self.window)
        if len(bars) < self.window:
            return
        mean = _ma(bars, self.window)
        sd = _std(bars, self.window)
        if mean != mean or sd != sd or sd <= 1e-9:
            return
        price = bars[-1].close
        lower = mean - self.num_std * sd
        upper = mean + self.num_std * sd
        pos = ctx.account.positions.get(sym)
        if price <= lower and not pos:
            shares = _lot_floor(ctx.account.cash)
            if shares > 0:
                ctx.order(sym, shares, "buy")
        elif price >= upper and pos:
            ctx.order(sym, pos.shares, "sell")


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


def _momentum_factory(params: Dict[str, Any]) -> Strategy:
    return MomentumStrategy(
        lookback=int(params.get("lookback", 20)),
        threshold=float(params.get("threshold", 0.0)),
        symbol=str(params.get("symbol", "")),
    )


def _mean_reversion_factory(params: Dict[str, Any]) -> Strategy:
    return MeanReversionStrategy(
        window=int(params.get("window", 20)),
        k=float(params.get("k", 2.0)),
        symbol=str(params.get("symbol", "")),
    )


def _rsi_factory(params: Dict[str, Any]) -> Strategy:
    return RsiStrategy(
        period=int(params.get("period", 14)),
        oversold=float(params.get("oversold", 30.0)),
        overbought=float(params.get("overbought", 70.0)),
        symbol=str(params.get("symbol", "")),
    )


def _bollinger_factory(params: Dict[str, Any]) -> Strategy:
    return BollingerStrategy(
        window=int(params.get("window", 20)),
        num_std=float(params.get("num_std", 2.0)),
        symbol=str(params.get("symbol", "")),
    )


# 策略注册表：名称 -> 工厂（由 params 构建策略实例）
STRATEGY_REGISTRY: Dict[str, Callable[[Dict[str, Any]], Strategy]] = {
    "buy_hold": _buy_hold_factory,
    "ma_cross": _ma_cross_factory,
    "fund_dingtou": _fund_dingtou_factory,
    "fund_value_avg": _fund_value_avg_factory,
    "futures_ma_cross": _futures_ma_cross_factory,
    "momentum": _momentum_factory,
    "mean_reversion": _mean_reversion_factory,
    "rsi": _rsi_factory,
    "bollinger": _bollinger_factory,
}


def get_strategy(name: str) -> Callable[[Dict[str, Any]], Strategy]:
    """按名称查找策略工厂（KeyError 由 API 层转 404/422）。"""
    if name not in STRATEGY_REGISTRY:
        raise KeyError(f"未知策略: {name}")
    return STRATEGY_REGISTRY[name]


# V3.2 因子 IC/IR 进策略排行榜：内置策略与因子库的默认映射。
# 用户可在 POST /backtest/run 时通过 factors 字段覆盖。
FACTOR_MAP: Dict[str, List[str]] = {
    "buy_hold": ["sharpe", "volatility"],
    "ma_cross": ["momentum", "mean_reversion"],
    "fund_dingtou": ["sharpe", "volatility"],
    "fund_value_avg": ["sharpe", "volatility"],
    "futures_ma_cross": ["momentum", "mean_reversion"],
    "momentum": ["momentum", "volatility"],
    "mean_reversion": ["mean_reversion", "volatility"],
    "rsi": ["mean_reversion", "volatility"],
    "bollinger": ["volatility", "mean_reversion"],
}


def default_factors(strategy_name: str) -> List[str]:
    """返回策略默认关联的因子名列表（用于报告展示 IC/IR）。"""
    return FACTOR_MAP.get(strategy_name, [])
