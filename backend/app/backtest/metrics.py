"""绩效指标计算（M2 回测引擎）。

对标开发计划 §4.2：净值 / 最大回撤 / 夏普比率 / 胜率 / 换手率。

- 净值曲线：total_value / initial_cash
- 年化收益：按 252 个交易日复利年化
- 最大回撤：曲线相对历史峰值的最大跌幅
- 夏普比率：日收益超额均值 / 日收益标准差 * sqrt(252)
- 胜率：卖出（平仓）笔数中已实现盈亏为正的比例
- 换手率：累计成交额（买+卖）/ 初始资金
"""

from __future__ import annotations

import math
from typing import Any, Dict, List, Optional

from .engine import EquityPoint, TRADING_DAYS_PER_YEAR


class PerformanceMetrics:
    """从净值曲线与成交记录计算绩效指标。"""

    def __init__(
        self,
        equity_curve: List[EquityPoint],
        initial_cash: float,
        trades: Optional[List[Any]] = None,
    ) -> None:
        self.equity = equity_curve
        self.initial_cash = float(initial_cash) if initial_cash else 1.0
        self.trades = trades or []
        self._compute()

    # ------------------------------------------------------------------ #
    def _compute(self) -> None:
        self.total_return = 0.0
        self.annual_return = 0.0
        self.max_drawdown = 0.0
        self.sharpe = 0.0
        self.win_rate = None
        self.turnover = 0.0
        self.daily_returns: List[float] = []
        self.days = len(self.equity)

        if self.days == 0:
            return

        # 净值 / 收益
        values = [p.total_value for p in self.equity]
        final = values[-1]
        self.total_return = final / self.initial_cash - 1.0
        self.daily_returns = [p.daily_return for p in self.equity]
        if self.days > 1 and self.daily_returns[0] == 0.0 and values[0] == self.initial_cash:
            # 去掉首日零收益点，避免稀释波动统计
            self.daily_returns = self.daily_returns[1:]

        # 年化收益
        if self.total_return > -1.0 and self.days >= 2:
            periods = self.days / TRADING_DAYS_PER_YEAR
            self.annual_return = math.pow(1 + self.total_return, 1.0 / periods) - 1.0

        # 最大回撤
        peak = values[0]
        for v in values:
            peak = max(peak, v)
            drawdown = v / peak - 1.0 if peak else 0.0
            self.max_drawdown = min(self.max_drawdown, drawdown)

        # 夏普比率（rf=0）
        if len(self.daily_returns) >= 2:
            mean_r = sum(self.daily_returns) / len(self.daily_returns)
            var = sum((r - mean_r) ** 2 for r in self.daily_returns) / (len(self.daily_returns) - 1)
            std = math.sqrt(var)
            if std > 1e-12:
                self.sharpe = mean_r / std * math.sqrt(TRADING_DAYS_PER_YEAR)

        # 胜率：平仓（卖出/赎回）笔数中 pnl > 0 的占比
        closed = [t for t in self.trades if getattr(t, "side", None) in ("sell", "redeem")]
        if closed:
            wins = sum(1 for t in closed if (getattr(t, "pnl", 0) or 0) > 0)
            self.win_rate = wins / len(closed)

        # 换手率：累计成交额 / 初始资金（股票=价格×股数；基金申购=金额、赎回=净值×份额）
        turnover_value = 0.0
        for t in self.trades:
            side = getattr(t, "side", None)
            if side == "subscribe":
                turnover_value += getattr(t, "amount", 0) or 0
            elif side == "redeem":
                turnover_value += (getattr(t, "nav", 0) or 0) * (getattr(t, "shares", 0) or 0)
            else:
                turnover_value += (getattr(t, "price", 0) or 0) * (getattr(t, "shares", 0) or 0)
        self.turnover = turnover_value / self.initial_cash if self.initial_cash else 0.0

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        def _fmt(v: Optional[float], nd: int = 4) -> Any:
            if v is None:
                return None
            return round(v, nd)

        return {
            "total_return": _fmt(self.total_return),
            "annual_return": _fmt(self.annual_return),
            "max_drawdown": _fmt(self.max_drawdown),
            "sharpe": _fmt(self.sharpe),
            "win_rate": _fmt(self.win_rate, 4) if self.win_rate is not None else None,
            "turnover": _fmt(self.turnover),
            "days": self.days,
            "final_value": _fmt(self.equity[-1].total_value) if self.equity else None,
        }

    def __repr__(self) -> str:
        return f"PerformanceMetrics(total_return={self.total_return:.4f}, " \
               f"max_drawdown={self.max_drawdown:.4f}, sharpe={self.sharpe:.4f})"
