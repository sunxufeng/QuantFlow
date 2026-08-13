"""事件驱动回测引擎（M2 回测引擎核心）。

对标开发计划 §4.2 事件循环骨架：
    initialize -> [before_trading -> handle_data -> after_trading] * 每个交易日 -> 报告

- 策略通过继承 :class:`Strategy` 实现生命周期钩子（initialize /
  before_trading / handle_data / after_trading）
- 引擎按交易日驱动：开盘前设置当日停牌/涨跌停状态，盘中撮合（
  Account + CostCalculator），收盘后 T+1 结算并记录净值曲线
- 数据输入为 ``{symbol: [Bar, ...]}``（日线，按日期升序）
- 基金支持（场外开放式基金）：通过 ``instruments`` 传入
  ``market="fund"`` 且 ``exchange=""`` 的标的，按 NAV 申购/赎回，
  T+1 确认；ETF/LOF（market="fund" 且带交易所）按股票机制撮合
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..market.models import Bar, Instrument, INTERVAL_DAILY, INTERVAL_MINUTE
from .account import Account, OrderRejected
from .costs import CostCalculator, CostRates, load_cost_rates
from .fund import FundAccount

TRADING_DAYS_PER_YEAR = 252


# --------------------------------------------------------------------------- #
# 异常
# --------------------------------------------------------------------------- #
class BacktestError(Exception):
    """回测配置/运行期错误。"""


# --------------------------------------------------------------------------- #
# 策略基类
# --------------------------------------------------------------------------- #
class Strategy:
    """策略基类：子类继承并实现所需钩子，其余默认空实现。"""

    def initialize(self, ctx: "BacktestContext") -> None:
        """回测开始前调用一次（初始化状态、参数）。"""

    def before_trading(self, ctx: "BacktestContext") -> None:
        """每个交易日开盘前调用（可查看当日数据、准备委托）。"""

    def handle_data(self, ctx: "BacktestContext") -> None:
        """每个交易日盘中调用（信号生成与下单主入口）。"""

    def after_trading(self, ctx: "BacktestContext") -> None:
        """每个交易日收盘后调用（日终清理）。"""


@dataclass
class BacktestContext:
    """策略运行上下文：暴露账户、当日 K 线、历史数据与下单入口。"""

    engine: "BacktestEngine"
    date: str
    account: Account
    bars: Dict[str, Bar]                      # 当日各标的 K 线
    calendar: List[str]                       # 全部交易日
    _history: Dict[str, List[Bar]] = field(default_factory=dict, repr=False)

    # ------------------------------------------------------------------ #
    # 数据访问
    # ------------------------------------------------------------------ #
    def bar(self, symbol: str) -> Optional[Bar]:
        """当日某标的 K 线；停牌/无数据返回 None。"""
        return self.bars.get(symbol)

    def history(self, symbol: str, n: int) -> List[Bar]:
        """截至当日（含）最近 n 根 K 线，升序。"""
        bars = self._history.get(symbol, [])
        return bars[-n:] if n > 0 else []

    def prev_close(self, symbol: str) -> Optional[float]:
        """该标的前一根 K 线收盘价（用于判断涨跌停；日线=前一日，分钟线=前一分钟）。"""
        bars = self._history.get(symbol, [])
        return bars[-2].close if len(bars) >= 2 else None

    def symbols(self) -> List[str]:
        return sorted(self.bars.keys())

    @property
    def fund_account(self) -> Optional[FundAccount]:
        """场外基金账户（无基金标的时为 None）。"""
        return self.engine.fund_account

    # ------------------------------------------------------------------ #
    # 下单
    # ------------------------------------------------------------------ #
    def order(
        self,
        symbol: str,
        shares: int,
        side: str,
        limit_price: Optional[float] = None,
    ) -> Optional[Any]:
        """委托下单（整手）；被拒绝（涨跌停/停牌/资金不足）时返回 None。"""
        if limit_price is None:
            bar = self.bar(symbol)
            if bar is None:
                return None
            limit_price = bar.close
        return self.account.order(symbol, side, shares, limit_price, date=self.date)

    # ------------------------------------------------------------------ #
    # 场外基金交易（按 NAV）
    # ------------------------------------------------------------------ #
    def _next_trading_day(self) -> str:
        """下一个交易日（用于 T+1 确认）；无则返回当日。"""
        try:
            i = self.calendar.index(self.date)
        except ValueError:
            return self.date
        return self.calendar[i + 1] if i + 1 < len(self.calendar) else self.date

    def subscribe(self, symbol: str, amount: float) -> Optional[Any]:
        """场外基金申购（按金额）；非基金标的/当日无净值时返回 None。"""
        if symbol not in self.engine._fund_symbols:
            return None
        bar = self.bar(symbol)
        if bar is None:
            return None
        return self.engine.fund_account.subscribe(
            symbol, amount, bar.close, self.date, confirm_date=self._next_trading_day()
        )

    def redeem(self, symbol: str, shares: float) -> Optional[Any]:
        """场外基金赎回（按份额）；非基金标的/当日无净值时返回 None。"""
        if symbol not in self.engine._fund_symbols:
            return None
        bar = self.bar(symbol)
        if bar is None:
            return None
        return self.engine.fund_account.redeem(
            symbol, shares, bar.close, self.date, confirm_date=self._next_trading_day()
        )


# --------------------------------------------------------------------------- #
# 净值曲线点
# --------------------------------------------------------------------------- #
@dataclass
class EquityPoint:
    """每个交易日的账户净值快照。"""

    date: str
    cash: float
    market_value: float
    total_value: float
    daily_return: float = 0.0  # 相对前一交易日的收益率

    def to_dict(self) -> dict:
        return {
            "date": self.date,
            "cash": round(self.cash, 4),
            "market_value": round(self.market_value, 4),
            "total_value": round(self.total_value, 4),
            "daily_return": round(self.daily_return, 6),
        }


# --------------------------------------------------------------------------- #
# 引擎
# --------------------------------------------------------------------------- #
class BacktestEngine:
    """日线事件驱动回测引擎。"""

    def __init__(
        self,
        strategy: Strategy,
        data: Dict[str, List[Bar]],
        *,
        initial_cash: float = 1_000_000.0,
        cost_rates: Optional[CostRates] = None,
        cost_config_path: Optional[str] = None,
        instruments: Optional[Dict[str, Instrument]] = None,
    ) -> None:
        self.strategy = strategy
        self.initial_cash = float(initial_cash)
        rates = cost_rates or load_cost_rates(cost_config_path)
        self.cost_calculator = CostCalculator(rates)

        if not data:
            raise BacktestError("回测数据为空")
        self.symbols = sorted(data.keys())
        self._validate(data)

        # 频率检测（V1.2）：日线 / 分钟线，要求数据同频
        intervals = {b.interval for bars in data.values() for b in bars}
        if len(intervals) > 1:
            raise BacktestError("回测数据混合了多种频率，请保持同一频率")
        self.is_minute = INTERVAL_MINUTE in intervals

        # 资产分类：market="fund" 且无交易所 -> 场外基金（NAV 计价）
        self._fund_symbols: set = set()
        if instruments:
            for sym, inst in instruments.items():
                if inst.market == "fund" and not inst.exchange:
                    self._fund_symbols.add(sym)
        self.fund_account: Optional[FundAccount] = None
        if self._fund_symbols:
            self.fund_account = FundAccount(
                self.initial_cash, cost_rates=rates, dividend_policy="cash"
            )

        # 时间轴索引：日线按 date、分钟线按 datetime 聚合为 step
        # {step: {symbol: Bar}}；同一频率下每个 step 至多一根同标的 K 线
        if self.is_minute and self._fund_symbols:
            raise BacktestError("V1.2 不支持场外基金的分钟级回测（基金按日 NAV 计价）")
        self.by_step: Dict[str, Dict[str, Bar]] = {}
        self._history: Dict[str, List[Bar]] = {s: [] for s in self.symbols}
        for symbol, bars in data.items():
            for b in sorted(bars, key=lambda x: (x.date, x.datetime or "")):
                step = b.datetime if self.is_minute else b.date
                self.by_step.setdefault(step, {})[symbol] = b
        if not self.by_step:
            raise BacktestError("回测数据为空")
        self.calendar = sorted(self.by_step.keys())

    @staticmethod
    def _validate(data: Dict[str, List[Bar]]) -> None:
        for symbol, bars in data.items():
            if not bars:
                raise BacktestError(f"标的 {symbol} 无 K 线数据")

    # ------------------------------------------------------------------ #
    # 运行
    # ------------------------------------------------------------------ #
    def run(self) -> "BacktestResult":
        account = Account(self.initial_cash, self.cost_calculator)
        ctx = BacktestContext(
            engine=self,
            date="",
            account=account,
            bars={},
            calendar=self.calendar,
            _history=self._history,
        )
        equity: List[EquityPoint] = []
        prev_total = self.initial_cash

        self.strategy.initialize(ctx)
        for step_key in self.calendar:
            today = self.by_step[step_key]

            # 历史序列：截至当日/当分钟（含）— 先追加，供涨跌停判定与策略历史读取
            for symbol, bar in today.items():
                self._history[symbol].append(bar)

            # 开盘前：基金 T+1 确认（昨日申购/赎回），重置限购计数
            if self.fund_account:
                self.fund_account.confirm_pending()
                self.fund_account.start_new_day()
                # 基金分红（除息日）：bar 携带 dividend>0 时按政策计入现金或红利再投
                for sym in self._fund_symbols:
                    bar = today.get(sym)
                    div = getattr(bar, "dividend", 0) if bar is not None else 0
                    if div and div > 0:
                        self.fund_account.apply_dividend(sym, div, bar.close, step_key)
            # 股票：当日停牌 / 涨停 / 跌停状态
            account.set_daily_states(*self._daily_states(step_key))
            ctx.date = step_key
            ctx.bars = today

            self.strategy.before_trading(ctx)
            self.strategy.handle_data(ctx)
            self.strategy.after_trading(ctx)

            # 收盘：股票 T+1 结算（当日买入下一交易日可卖）
            account.settle()

            prices = {s: b.close for s, b in today.items()}
            if self.fund_account:
                # 股票与基金两个账户各自持有 initial_cash，合并净值时
                # 扣除重复计入的一次初始资金（仅出现一次重复，减一次即可）
                navs = {s: b.close for s, b in today.items() if s in self._fund_symbols}
                cash = account.cash + self.fund_account.cash - self.initial_cash
                market_value = account.market_value(prices) + self.fund_account.market_value(navs)
                total = cash + market_value + self.fund_account.pending_value(navs)
            else:
                cash = account.cash
                market_value = account.market_value(prices)
                total = account.total_value(prices)
            equity.append(
                EquityPoint(
                    date=step_key,
                    cash=cash,
                    market_value=market_value,
                    total_value=total,
                    daily_return=total / prev_total - 1.0 if prev_total else 0.0,
                )
            )
            prev_total = total

        trades = account.trades
        if self.fund_account:
            trades = trades + self.fund_account.trades
        return BacktestResult(
            engine=self,
            account=account,
            equity_curve=equity,
            trades=trades,
            strategy=self.strategy,
            fund_account=self.fund_account,
        )

    # ------------------------------------------------------------------ #
    # 状态判定
    # ------------------------------------------------------------------ #
    def _prev_close(self, symbol: str) -> Optional[float]:
        """当前 step 之前最近一根 K 线的收盘价（日线=前一日，分钟线=前一分钟）。

        历史序列在 handle_data 前已追加当日/当分钟 K 线，故取 [-2]。
        """
        bars = self._history[symbol]
        return bars[-2].close if len(bars) >= 2 else None

    def _daily_states(self, step_key: str) -> tuple:
        suspended: set = set()
        limit_up: set = set()
        limit_down: set = set()
        step = self.by_step.get(step_key, {})
        for symbol in self.symbols:
            if symbol in self._fund_symbols:
                continue  # 场外基金按 NAV 计价，无涨跌停/停牌
            bar = step.get(symbol)
            if bar is None or bar.volume == 0:
                suspended.add(symbol)
                continue
            prev = self._prev_close(symbol)
            if prev is None or prev <= 0:
                continue
            from .account import LIMIT_PCT

            if bar.close >= prev * (1 + LIMIT_PCT) - 1e-9:
                limit_up.add(symbol)
            if bar.close <= prev * (1 - LIMIT_PCT) + 1e-9:
                limit_down.add(symbol)
        return suspended, limit_up, limit_down


# --------------------------------------------------------------------------- #
# 回测结果
# --------------------------------------------------------------------------- #
@dataclass
class BacktestResult:
    engine: BacktestEngine
    account: Account
    equity_curve: List[EquityPoint]
    trades: List[Any]
    strategy: Strategy
    fund_account: Optional[FundAccount] = None

    def to_dict(self, include_curve: bool = True) -> dict:
        """序列化结果（不含绩效指标，指标由 metrics 模块计算）。"""
        out = {
            "symbols": self.engine.symbols,
            "interval": INTERVAL_MINUTE if self.engine.is_minute else INTERVAL_DAILY,
            "calendar": self.engine.calendar,
            "initial_cash": self.engine.initial_cash,
            "account": self.account.to_dict(),
            "trades": [t.to_dict() for t in self.trades],
        }
        if self.fund_account is not None:
            out["fund_account"] = self.fund_account.to_dict()
        if include_curve:
            out["equity_curve"] = [p.to_dict() for p in self.equity_curve]
        return out
