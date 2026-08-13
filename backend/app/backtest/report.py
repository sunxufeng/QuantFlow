"""回测报告生成与存储（M2 回测引擎）。

对标开发计划 §4.2：回测报告生成与存储（曲线数据、交易明细）。

- :func:`build_report` 汇总策略/参数/绩效/净值曲线/交易明细为完整报告 dict
- :class:`BacktestReportStore` 将报告序列化到本地 JSON（默认
  ``backend/data/backtests/<run_id>.json``）
"""

from __future__ import annotations

import json
import os
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from .engine import BacktestResult
from .metrics import PerformanceMetrics
from ..market.models import INTERVAL_DAILY, INTERVAL_MINUTE

# 默认报告存储目录（相对 backend 根目录）
DEFAULT_REPORT_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "backtests"
)


def build_report(
    result: BacktestResult,
    *,
    strategy_name: str = "",
    strategy_config: Optional[Dict[str, Any]] = None,
    run_id: Optional[str] = None,
    benchmark_symbol: Optional[str] = None,
) -> Dict[str, Any]:
    """汇总回测结果为结构化报告 dict。

    包含：
    - run_id / 时间戳 / 策略与参数
    - 绩效指标（净值/回撤/夏普/胜率/换手）
    - 净值曲线（日期/总资产/收益率）
    - 交易明细（买卖/股数/价格/成本/盈亏）
    - 账户终态
    """
    metrics = PerformanceMetrics(
        result.equity_curve, result.engine.initial_cash, result.trades
    )
    report = {
        "run_id": run_id or uuid.uuid4().hex[:12],
        "type": "backtest_report",
        "strategy": strategy_name or type(result.strategy).__name__,
        "strategy_config": strategy_config or {},
        "benchmark_symbol": benchmark_symbol,
        "symbols": result.engine.symbols,
        "interval": INTERVAL_MINUTE if result.engine.is_minute else INTERVAL_DAILY,
        "start_date": result.engine.calendar[0] if result.engine.calendar else "",
        "end_date": result.engine.calendar[-1] if result.engine.calendar else "",
        "metrics": metrics.to_dict(),
        "equity_curve": [p.to_dict() for p in result.equity_curve],
        "trades": [t.to_dict() for t in result.trades],
        "account": result.account.to_dict(),
        "initial_cash": result.engine.initial_cash,
    }
    if result.fund_account is not None:
        report["fund_account"] = result.fund_account.to_dict()
    return report


@dataclass
class BacktestReportStore:
    """回测报告本地存储（V1.0 落盘 JSON，M3 迁移到 Mongo/云存储）。"""

    report_dir: str = DEFAULT_REPORT_DIR

    def save(self, report: Dict[str, Any]) -> str:
        """保存报告，返回写入的完整路径。"""
        os.makedirs(self.report_dir, exist_ok=True)
        run_id = report.get("run_id") or uuid.uuid4().hex[:12]
        path = os.path.join(self.report_dir, f"{run_id}.json")
        with open(path, "w", encoding="utf-8") as f:
            json.dump(report, f, ensure_ascii=False, indent=2)
        return path

    def load(self, run_id: str) -> Dict[str, Any]:
        path = os.path.join(self.report_dir, f"{run_id}.json")
        if not os.path.exists(path):
            raise FileNotFoundError(f"回测报告不存在: {run_id}")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def list(self) -> List[str]:
        """已保存报告 run_id 列表（按修改时间倒序）。"""
        if not os.path.isdir(self.report_dir):
            return []
        files = [f for f in os.listdir(self.report_dir) if f.endswith(".json")]
        files.sort(
            key=lambda f: os.path.getmtime(os.path.join(self.report_dir, f)), reverse=True
        )
        return [os.path.splitext(f)[0] for f in files]
