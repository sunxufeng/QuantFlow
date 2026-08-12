"""M2 回测引擎（后端C）。

对标开发计划 §4.2：
- 事件循环骨架（initialize / before_trading / handle_data / after_trading）
- 股票账户/持仓模型 + 撮合（T+1、涨跌停、停牌）
- 交易成本模型（手续费/印花税/过户费/滑点）
- 绩效指标（净值/回撤/夏普/胜率/换手）
- 回测报告生成与存储

V1.3 预留：期货账户（多空/保证金）、分钟级数据。
"""

from .account import Account, CostCalculator, Order, OrderRejected, Position, Trade
from .costs import CostRates, load_cost_rates
from .engine import (
    BacktestContext,
    BacktestEngine,
    BacktestError,
    BacktestResult,
    EquityPoint,
    Strategy,
)
from .fund import FundAccount, FundOrderRejected, FundPosition, FundTrade
from .metrics import PerformanceMetrics
from .report import BacktestReportStore, build_report

__all__ = [
    "Account",
    "BacktestContext",
    "BacktestEngine",
    "BacktestError",
    "BacktestReportStore",
    "BacktestResult",
    "CostCalculator",
    "CostRates",
    "EquityPoint",
    "FundAccount",
    "FundOrderRejected",
    "FundPosition",
    "FundTrade",
    "Order",
    "OrderRejected",
    "PerformanceMetrics",
    "Position",
    "Strategy",
    "Trade",
    "build_report",
    "load_cost_rates",
]
