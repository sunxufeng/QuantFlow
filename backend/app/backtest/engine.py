"""事件驱动回测引擎（M2 回测引擎核心）。

对标开发计划 §4.2 事件循环骨架：
    initialize -> [before_trading -> handle_data -> after_trading] * 每个交易日 -> 报告

- 策略通过继承 :class:`Strategy` 实现生命周期钩子（initialize /
  before_trading / handle_data / after_trading）
- 引擎按交易日驱动：开盘前设置当日停牌/涨跌停状态，盘中撮合（
  Account + CostCalculator），收盘后 T+1 结算并记录净值曲线
- 数据输入为 ``{symbol: [Bar, ...]}``（日线，按日期升序）
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from ..market.models import Bar
from .account import Account, OrderRejected
from .costs import CostCalculator, CostRates, load_cost_rates

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
        """该标的前一交易日收盘价（用于判断涨跌停）。"""
        bars = self._history.get(symbol, [])
        if len(bars) < 2:
            return None
        return bars[-2].close

    def symbols(self) -> List[str]:
        return sorted(self.bars.keys())

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
    ) -> None:
        self.strategy = strategy
        self.initial_cash = float(initial_cash)
        rates = cost_rates or load_cost_rates(cost_config_path)
        self.cost_calculator = CostCalculator(rates)

        if not data:
            raise BacktestError("回测数据为空")
        self.symbols = sorted(data.keys())
        self._validate(data)

        # 按日期索引：{date: {symbol: Bar}}
        self.by_date: Dict[str, Dict[str, Bar]] = {}
        self._history: Dict[str, List[Bar]] = {s: [] for s in self.symbols}
        for symbol, bars in data.items():
            for b in sorted(bars, key=lambda x: x.date):
                self.by_date.setdefault(b.date, {})[symbol] = b
        if not self.by_date:
            raise BacktestError("回测数据为空")
        self.calendar = sorted(self.by_date.keys())

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
        for date in self.calendar:
            today = self.by_date[date]

            # 开盘前：更新当日状态（停牌 / 涨停 / 跌停）
            account.set_daily_states(*self._daily_states(date))
            ctx.date = date
            ctx.bars = today
            # 历史序列：截至当日（含）
            for symbol, bar in today.items():
                self._history[symbol].append(bar)

            self.strategy.before_trading(ctx)
            self.strategy.handle_data(ctx)
            self.strategy.after_trading(ctx)

            # 收盘：T+1 结算（当日买入下一交易日可卖）
            account.settle()

            prices = {s: b.close for s, b in today.items()}
            total = account.total_value(prices)
            equity.append(
                EquityPoint(
                    date=date,
                    cash=account.cash,
                    market_value=account.market_value(prices),
                    total_value=total,
                    daily_return=total / prev_total - 1.0 if prev_total else 0.0,
                )
            )
            prev_total = total

        return BacktestResult(
            engine=self,
            account=account,
            equity_curve=equity,
            trades=account.trades,
            strategy=self.strategy,
        )

    # ------------------------------------------------------------------ #
    # 状态判定
    # ------------------------------------------------------------------ #
    def _prev_close(self, symbol: str, date: str) -> Optional[float]:
        """date 之前最近一个交易日的收盘价。"""
        bars = self._history[symbol]
        for b in reversed(bars):
            if b.date < date:
                return b.close
        return None

    def _daily_states(self, date: str) -> tuple:
        suspended: set = set()
        limit_up: set = set()
        limit_down: set = set()
        for symbol in self.symbols:
            bar = self.by_date.get(date, {}).get(symbol)
            if bar is None or bar.volume == 0:
                suspended.add(symbol)
                continue
            prev = self._prev_close(symbol, date)
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

    def to_dict(self, include_curve: bool = True) -> dict:
        """序列化结果（不含绩效指标，指标由 metrics 模块计算）。"""
        out = {
            "symbols": self.engine.symbols,
            "calendar": self.engine.calendar,
            "initial_cash": self.engine.initial_cash,
            "account": self.account.to_dict(),
            "trades": [t.to_dict() for t in self.trades],
        }
        if include_curve:
            out["equity_curve"] = [p.to_dict() for p in self.equity_curve]
        return out
