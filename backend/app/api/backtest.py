"""回测交易 API（M2 核心引擎交付）。

对标开发计划 §4.2「交易 API」：
- ``POST /api/backtest/run``：按策略名称 + 参数 + 行情区间运行回测，
  返回完整回测报告（绩效/净值曲线/交易明细/账户终态），并落盘存储
- ``GET /api/backtest/strategies``：列出内置策略
- ``GET /api/backtest/reports``：历史回测报告列表
- ``GET /api/backtest/reports/{run_id}``：报告详情
"""

from __future__ import annotations

import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from ..backtest import BacktestEngine, BacktestReportStore, build_report
from ..backtest.strategies import STRATEGY_REGISTRY
from ..market.models import Bar, Instrument
from ..market.service import market_service

logger = logging.getLogger("quantflow.api.backtest")

router = APIRouter(prefix="/backtest", tags=["backtest"])

report_store = BacktestReportStore()


# --------------------------------------------------------------------------- #
# 请求模型
# --------------------------------------------------------------------------- #
class BacktestRunRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(default_factory=dict, description="策略参数")
    symbols: List[str] = Field(..., min_length=1, description="回测标的")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(
        default_factory=dict,
        description="标的资产类型覆盖（symbol -> stock/fund；market=fund 且无交易所视为场外基金）",
    )
    strategy_name: str = Field(default="", description="报告显示用策略名（默认取 strategy）")
    benchmark_symbol: Optional[str] = Field(default=None, description="基准标的（预留）")


# --------------------------------------------------------------------------- #
# 路由
# --------------------------------------------------------------------------- #
@router.get("/strategies", summary="内置策略列表")
def list_strategies() -> dict:
    return {
        "items": [
            {
                "name": name,
                "description": _strategy_description(name),
            }
            for name in STRATEGY_REGISTRY
        ]
    }


def _strategy_description(name: str) -> str:
    docs = {
        "buy_hold": "买入持有：首日买入、末日卖出（股票）",
        "ma_cross": "均线金叉/死叉：MA5 上穿 MA20 买入、下穿卖出（股票）",
        "fund_dingtou": "场外基金定投：每月首个交易日申购固定金额（基金）",
        "fund_value_avg": "价值平均定投：目标市值线性增长，每月补足/赎回差额（基金）",
    }
    return docs.get(name, "")


@router.post("/run", summary="运行回测并生成报告")
def run_backtest(payload: BacktestRunRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}",
        )

    # 1. 拉取行情（data_source 无数据时抛 503/404）
    data: Dict[str, List[Bar]] = {}
    for symbol in payload.symbols:
        try:
            bars = market_service.bars(symbol, payload.start, payload.end)
        except Exception as exc:  # 行情源失败统一转 503
            logger.warning("backtest fetch %s failed: %s", symbol, exc)
            raise HTTPException(status_code=503, detail=f"行情获取失败: {symbol}") from exc
        if not bars:
            raise HTTPException(
                status_code=422,
                detail=f"标的 {symbol} 在 {payload.start}~{payload.end} 无行情数据",
            )
        data[symbol] = bars

    # 2. 资产分类 -> Instrument 元信息
    instruments: Dict[str, Instrument] = {}
    for symbol in payload.symbols:
        asset_type = payload.asset_types.get(symbol, "stock")
        instruments[symbol] = Instrument(
            symbol=symbol,
            name=f"标的自定义",
            market=asset_type,
            exchange="" if asset_type == "fund" else "SH",
        )

    # 3. 构建策略并运行
    factory = STRATEGY_REGISTRY[payload.strategy]
    strategy = factory(payload.params)
    engine = BacktestEngine(
        strategy,
        data,
        initial_cash=payload.initial_cash,
        instruments=instruments,
    )
    result = engine.run()

    # 4. 生成报告并落盘
    report = build_report(
        result,
        strategy_name=payload.strategy_name or payload.strategy,
        strategy_config=payload.params,
        benchmark_symbol=payload.benchmark_symbol,
    )
    report_store.save(report)
    logger.info("backtest report %s generated (%s)", report["run_id"], payload.strategy)
    return report


@router.get("/reports", summary="回测报告列表")
def list_reports() -> dict:
    return {"items": report_store.list()}


@router.get("/reports/{run_id}", summary="回测报告详情")
def get_report(run_id: str) -> dict:
    try:
        return report_store.load(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
