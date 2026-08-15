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
        benchmark_values: Optional[List[float]] = None,
    ) -> None:
        self.equity = equity_curve
        self.initial_cash = float(initial_cash) if initial_cash else 1.0
        self.trades = trades or []
        self.benchmark_values = benchmark_values
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

        # 绩效归因（V1.5）：交易层面 + 曲线层面 + 基准对比
        self._attribution = self._compute_attribution()

    # ------------------------------------------------------------------ #
    def _compute_attribution(self) -> Dict[str, Any]:
        """交易层面与曲线层面的归因指标。

        返回结构（均为可选/可空）：
        - trade: profit_factor / avg_win / avg_loss / payoff_ratio / max_win_streak / max_loss_streak
        - curve: monthly_returns / drawdown_periods / max_drawdown_days / exposure_ratio
        - benchmark: benchmark_return / excess_return / alpha / beta
        """
        attr: Dict[str, Any] = {"trade": {}, "curve": {}, "benchmark": {}}

        # ---- 交易层面 ----
        closed = [
            t for t in self.trades
            if getattr(t, "side", None) in ("sell", "redeem")
            and (getattr(t, "pnl", None) is not None)
        ]
        if closed:
            wins = [float(getattr(t, "pnl", 0) or 0) for t in closed if (getattr(t, "pnl", 0) or 0) > 0]
            losses = [float(getattr(t, "pnl", 0) or 0) for t in closed if (getattr(t, "pnl", 0) or 0) <= 0]
            gross_win = sum(wins)
            gross_loss = abs(sum(losses))
            trade_attr = {
                "closed_trades": len(closed),
                "profit_factor": (gross_win / gross_loss) if gross_loss > 0 else None,
                "avg_win": (gross_win / len(wins)) if wins else 0.0,
                "avg_loss": (gross_loss / len(losses)) if losses else 0.0,
                "payoff_ratio": (
                    (gross_win / len(wins)) / (gross_loss / len(losses))
                    if wins and losses and gross_loss > 0 else None
                ),
            }
            # 连胜 / 连亏（按平仓顺序）
            cur_win = cur_loss = best_win = best_loss = 0
            for t in closed:
                pnl = float(getattr(t, "pnl", 0) or 0)
                if pnl > 0:
                    cur_win += 1
                    cur_loss = 0
                    best_win = max(best_win, cur_win)
                else:
                    cur_loss += 1
                    cur_win = 0
                    best_loss = max(best_loss, cur_loss)
            trade_attr["max_win_streak"] = best_win
            trade_attr["max_loss_streak"] = best_loss
            trade_attr["win_pnl"] = round(gross_win, 2)
            trade_attr["loss_pnl"] = round(-gross_loss, 2)
            attr["trade"] = trade_attr

        # ---- 风险层面：年化波动 / 下行波动 / 索提诺 ----
        rets = self.daily_returns
        risk: Dict[str, Any] = {}
        if len(rets) >= 2:
            mean_r = sum(rets) / len(rets)
            var = sum((r - mean_r) ** 2 for r in rets) / (len(rets) - 1)
            std = math.sqrt(var)
            volatility = std * math.sqrt(TRADING_DAYS_PER_YEAR)
            # 下行偏差（目标收益 0）
            downside = [min(0.0, r) for r in rets]
            dd_var = sum(d * d for d in downside) / (len(rets) - 1)
            downside_dev = math.sqrt(dd_var) * math.sqrt(TRADING_DAYS_PER_YEAR)
            sortino = (mean_r * TRADING_DAYS_PER_YEAR) / downside_dev if downside_dev > 1e-12 else 0.0
            risk = {
                "volatility": round(volatility, 6),
                "downside_deviation": round(downside_dev, 6),
                "sortino": round(sortino, 6),
            }
        attr["risk"] = risk

        # ---- 曲线层面：月度收益 / 回撤区间 / 持仓暴露 ----
        if self.days >= 2:
            # 月度收益
            by_month: Dict[str, List[float]] = {}
            for p in self.equity:
                month = p.date[:7]
                by_month.setdefault(month, []).append(p.total_value)
            monthly = []
            for month in sorted(by_month):
                vals = by_month[month]
                ret = vals[-1] / vals[0] - 1.0 if vals[0] else 0.0
                monthly.append({"month": month, "return": round(ret, 6)})
            attr["curve"]["monthly_returns"] = monthly

            # 回撤区间（峰→谷）
            peak = self.equity[0].total_value
            peak_date = self.equity[0].date
            in_dd = False
            dd_start = None
            dd_peak = peak
            min_v = peak
            dd_len = 0
            periods = []
            for p in self.equity:
                v = p.total_value
                if v >= peak:
                    if in_dd:
                        # 结束一段回撤
                        periods.append({
                            "start": dd_start,
                            "end": p.date,
                            "depth": round(min_v / dd_peak - 1.0, 6),
                            "days": dd_len,
                        })
                        in_dd = False
                    peak = v
                    peak_date = p.date
                else:
                    if not in_dd:
                        in_dd = True
                        dd_start = peak_date
                        dd_peak = peak
                        min_v = v
                        dd_len = 1
                    else:
                        dd_len += 1
                        min_v = min(min_v, v)
            if in_dd:
                periods.append({
                    "start": dd_start,
                    "end": self.equity[-1].date,
                    "depth": round(min_v / dd_peak - 1.0, 6),
                    "days": dd_len,
                })
            attr["curve"]["drawdown_periods"] = periods
            attr["curve"]["max_drawdown_days"] = max((p["days"] for p in periods), default=0)
            # 持仓暴露（有市值的交易日占比）
            exposed = sum(1 for p in self.equity if (p.market_value or 0) > 0)
            attr["curve"]["exposure_ratio"] = round(exposed / self.days, 4)

        # ---- 基准对比（买入持有） ----
        if self.benchmark_values and len(self.benchmark_values) >= 2 and self.days >= 2:
            bv = self.benchmark_values
            bench_ret = bv[-1] / bv[0] - 1.0 if bv[0] else 0.0
            strat_ret = self.total_return
            # 日收益序列（与净值对齐）
            s_ret = [p.daily_return for p in self.equity if p.daily_return != 0.0] or self.daily_returns
            b_ret = []
            for i in range(1, len(bv)):
                b_ret.append(bv[i] / bv[i - 1] - 1.0 if bv[i - 1] else 0.0)
            n = min(len(s_ret), len(b_ret))
            if n >= 2:
                import statistics
                mean_s = sum(s_ret[:n]) / n
                mean_b = sum(b_ret[:n]) / n
                cov = sum((s_ret[i] - mean_s) * (b_ret[i] - mean_b) for i in range(n)) / (n - 1)
                var_b = sum((b_ret[i] - mean_b) ** 2 for i in range(n)) / (n - 1)
                beta = cov / var_b if var_b > 1e-12 else 0.0
                # 年化
                ann_s = (1 + strat_ret) ** (TRADING_DAYS_PER_YEAR / self.days) - 1 if self.days >= 2 else 0.0
                ann_b = (1 + bench_ret) ** (TRADING_DAYS_PER_YEAR / self.days) - 1 if self.days >= 2 else 0.0
                alpha = ann_s - beta * ann_b
                # 跟踪误差（年化）与信息比率（V14 基准对比增强）
                excess = [s_ret[i] - b_ret[i] for i in range(n)]
                mean_ex = sum(excess) / n
                te_daily = math.sqrt(
                    sum((e - mean_ex) ** 2 for e in excess) / (n - 1)
                )
                tracking_error = te_daily * math.sqrt(TRADING_DAYS_PER_YEAR)
                information_ratio = (ann_s - ann_b) / tracking_error if tracking_error > 1e-12 else 0.0
                attr["benchmark"] = {
                    "benchmark_return": round(bench_ret, 6),
                    "excess_return": round(strat_ret - bench_ret, 6),
                    "alpha": round(alpha, 6),
                    "beta": round(beta, 6),
                    "tracking_error": round(tracking_error, 6),
                    "information_ratio": round(information_ratio, 4),
                }

        return attr

    # ------------------------------------------------------------------ #
    def to_dict(self) -> Dict[str, Any]:
        def _fmt(v: Optional[float], nd: int = 4) -> Any:
            if v is None:
                return None
            return round(v, nd)

        return {
            "total_return": _fmt(self.total_return, 6),
            "annual_return": _fmt(self.annual_return),
            "max_drawdown": _fmt(self.max_drawdown),
            "sharpe": _fmt(self.sharpe),
            "win_rate": _fmt(self.win_rate, 4) if self.win_rate is not None else None,
            "turnover": _fmt(self.turnover),
            "days": self.days,
            "final_value": _fmt(self.equity[-1].total_value) if self.equity else None,
            "attribution": self._attribution,
        }

    def __repr__(self) -> str:
        return f"PerformanceMetrics(total_return={self.total_return:.4f}, " \
               f"max_drawdown={self.max_drawdown:.4f}, sharpe={self.sharpe:.4f})"
