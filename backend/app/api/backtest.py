"""回测交易 API（M2 核心引擎交付）。

对标开发计划 §4.2「交易 API」：
- ``POST /api/backtest/run``：按策略名称 + 参数 + 行情区间运行回测，
  返回完整回测报告（绩效/净值曲线/交易明细/账户终态），并落盘存储
- ``GET /api/backtest/strategies``：列出内置策略
- ``GET /api/backtest/reports``：历史回测报告列表
- ``GET /api/backtest/reports/{run_id}``：报告详情
"""

from __future__ import annotations

import csv
import io
import json
import logging
from typing import Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

from ..backtest import BacktestEngine, BacktestError, BacktestReportStore, build_report
from ..backtest.metrics import PerformanceMetrics
from ..backtest.montecarlo import monte_carlo
from ..backtest.analysis import (
    sensitivity_grid as _sensitivity_grid,
    walk_forward as _walk_forward,
    build_benchmark_values as _build_benchmark_values,
    factor_decay as _factor_decay,
    parameter_robustness as _parameter_robustness,
    weighted_benchmark_compare as _weighted_benchmark_compare,
)
from ..backtest.optimizer import OptimizeConfigError, optimize
from ..backtest.portfolio import PortfolioBacktest
from ..backtest.strategies import STRATEGY_REGISTRY, default_factors
from ..core.auth import get_current_user
from ..factors import research as factor_research
from ..factors.registry import list_factors
from ..market.models import Bar, Instrument
from ..market.service import market_service

logger = logging.getLogger("quantflow.api.backtest")

router = APIRouter(
    prefix="/backtest",
    tags=["backtest"],
    dependencies=[Depends(get_current_user)],
)

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
        description="标的资产类型覆盖（symbol -> stock/fund/future；market=fund 无交易所=场外基金，future=期货）",
    )
    multipliers: Dict[str, float] = Field(
        default_factory=dict,
        description="期货合约乘数覆盖（symbol -> 乘数；future 标的默认 10）",
    )
    interval: str = Field(
        default="daily",
        description="行情频率：daily（日线）或 minute（分钟线，V1.2）",
    )
    strategy_name: str = Field(default="", description="报告显示用策略名（默认取 strategy）")
    benchmark_symbol: Optional[str] = Field(default=None, description="基准标的（预留）")
    factors: Optional[List[str]] = Field(
        default=None,
        description="策略关联因子（用于报告 IC/IR 展示）；留空使用内置策略默认因子",
    )


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
        "futures_ma_cross": "期货均线金叉做多、死叉做空（多空净仓，V1.3）",
    }
    return docs.get(name, "")


def _build_benchmark_curve(
    symbol: str,
    start: str,
    end: str,
    interval: str,
    dates: List[str],
    initial_cash: float,
) -> "tuple[Optional[List[float]], Optional[List[Dict[str, Any]]]]":
    """构建基准买入持有净值曲线（与策略 equity_curve 日期对齐）。

    返回 (benchmark_values, benchmark_curve)：
    - benchmark_values：按 dates 对齐的基准总资产序列（供 PerformanceMetrics 算 alpha/beta/TE/IR）
    - benchmark_curve：[{date, value}] 供前端叠加展示
    行情缺失时返回 (None, None)，不影响主回测。
    """
    try:
        bars = market_service.bars(symbol, start, end, interval=interval)
    except Exception as exc:  # 基准行情失败不影响主回测
        logger.warning("benchmark fetch %s failed: %s", symbol, exc)
        return None, None
    if not bars:
        return None, None
    close_by_date = {b.date: float(b.close) for b in bars}
    base = bars[0].close or 1.0
    values: List[float] = []
    curve: List[Dict[str, Any]] = []
    last = None
    for d in dates:
        if d in close_by_date:
            last = close_by_date[d]
        # 非交易日沿用上一已知收盘价（净值不变）
        if last is None:
            continue
        nav = initial_cash * (last / base)
        values.append(nav)
        curve.append({"date": d, "value": round(nav, 2)})
    if len(values) < 2:
        return None, None
    return values, curve



@router.post("/run", summary="运行回测并生成报告")
def run_backtest(payload: BacktestRunRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}",
        )
    if payload.interval not in ("daily", "minute"):
        raise HTTPException(
            status_code=422, detail=f"不支持的行情频率 {payload.interval!r}"
        )

    # 1. 拉取行情（data_source 无数据时抛 503/404）
    data: Dict[str, List[Bar]] = {}
    for symbol in payload.symbols:
        try:
            bars = market_service.bars(
                symbol, payload.start, payload.end, interval=payload.interval
            )
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
        if asset_type == "fund":
            exchange = ""
        elif asset_type == "future":
            exchange = "CFFEX"
        else:
            exchange = "SH"
        instruments[symbol] = Instrument(
            symbol=symbol,
            name="标的自定义",
            market=asset_type,
            exchange=exchange,
            contract_multiplier=float(payload.multipliers.get(symbol, 10.0))
            if asset_type == "future"
            else 1.0,
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
    strategy_display = payload.strategy_name or payload.strategy
    factors = list(payload.factors) if payload.factors else default_factors(payload.strategy)
    benchmark_values = None
    benchmark_curve = None
    if payload.benchmark_symbol:
        benchmark_values, benchmark_curve = _build_benchmark_curve(
            payload.benchmark_symbol, payload.start, payload.end,
            payload.interval, [p.date for p in result.equity_curve],
            payload.initial_cash,
        )
    report = build_report(
        result,
        strategy_name=strategy_display,
        strategy_config=payload.params,
        benchmark_symbol=payload.benchmark_symbol,
        benchmark_values=benchmark_values,
        benchmark_curve=benchmark_curve,
        factors=factors,
    )
    report_store.save(report)
    logger.info("backtest report %s generated (%s)", report["run_id"], payload.strategy)
    return report


# --------------------------------------------------------------------------- #
# 参数优化（V2.1）
# --------------------------------------------------------------------------- #
class OptimizeRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    fixed_params: Dict[str, object] = Field(
        default_factory=dict, description="固定参数（不参与网格，如 symbol 映射到标的）"
    )
    grid: Dict[str, List[object]] = Field(
        default_factory=dict,
        description="待搜索参数网格（param -> 候选值列表），将做笛卡尔积遍历",
    )
    symbols: List[str] = Field(..., min_length=1, description="回测标的（与 run 一致）")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(
        default_factory=dict, description="标的资产类型覆盖（symbol -> stock/fund/future）"
    )
    multipliers: Dict[str, float] = Field(
        default_factory=dict, description="期货合约乘数覆盖（future 默认 10）"
    )
    interval: str = Field(default="daily", description="行情频率：daily / minute")
    objective: str = Field(
        default="sharpe",
        description="排序目标：sharpe / total_return / annual_return / max_drawdown / win_rate",
    )
    top_n: int = Field(default=10, gt=0, le=100, description="返回 Top-N 组参数")
    max_combos: int = Field(
        default=200, gt=0, le=2000, description="网格组合上限（防止笛卡尔积爆炸）"
    )


@router.post("/optimize", summary="回测参数优化（网格搜索 + 排序）")
def optimize_backtest(payload: OptimizeRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.interval not in ("daily", "minute"):
        raise HTTPException(
            status_code=422, detail=f"不支持的行情频率 {payload.interval!r}"
        )
    try:
        result = optimize(
            strategy=payload.strategy,
            fixed_params=payload.fixed_params,
            grid=payload.grid,
            symbols=payload.symbols,
            start=payload.start,
            end=payload.end,
            initial_cash=payload.initial_cash,
            asset_types=payload.asset_types,
            multipliers=payload.multipliers,
            interval=payload.interval,
            objective=payload.objective,
            top_n=payload.top_n,
            max_combos=payload.max_combos,
        )
    except OptimizeConfigError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except BacktestError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return result


# --------------------------------------------------------------------------- #
# 参数敏感性分析（V14）
# --------------------------------------------------------------------------- #
class SensitivityRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(
        default_factory=dict, description="固定参数（不参与扫描的部分）"
    )
    param: str = Field(..., description="待扫描的参数名")
    values: List[object] = Field(
        ..., min_length=1, description="待扫描的参数取值列表（按此顺序逐次回测）"
    )
    symbols: List[str] = Field(..., min_length=1, description="回测标的")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(
        default_factory=dict, description="标的资产类型覆盖（symbol -> stock/fund/future）"
    )
    multipliers: Dict[str, float] = Field(
        default_factory=dict, description="期货合约乘数覆盖（future 默认 10）"
    )
    interval: str = Field(default="daily", description="行情频率：daily / minute")
    metric: str = Field(
        default="total_return",
        description="扫描指标：total_return / annual_return / sharpe / max_drawdown / win_rate",
    )


@router.post("/sensitivity", summary="参数敏感性分析（单参数扫描，V14）")
def sensitivity_analysis(payload: SensitivityRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.interval not in ("daily", "minute"):
        raise HTTPException(
            status_code=422, detail=f"不支持的行情频率 {payload.interval!r}"
        )
    if payload.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422,
            detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}",
        )
    if payload.metric not in (
        "total_return", "annual_return", "sharpe", "max_drawdown", "win_rate"
    ):
        raise HTTPException(status_code=422, detail=f"不支持的指标 {payload.metric!r}")

    # 1. 行情（对所有取值共享，只拉一次）
    data: Dict[str, List[Bar]] = {}
    for symbol in payload.symbols:
        try:
            bars = market_service.bars(symbol, payload.start, payload.end, interval=payload.interval)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"行情获取失败: {symbol}") from exc
        if not bars:
            raise HTTPException(
                status_code=422, detail=f"标的 {symbol} 在 {payload.start}~{payload.end} 无行情数据"
            )
        data[symbol] = bars

    instruments: Dict[str, Instrument] = {}
    for symbol in payload.symbols:
        asset_type = payload.asset_types.get(symbol, "stock")
        exchange = "CFFEX" if asset_type == "future" else ("SH" if asset_type == "stock" else "")
        instruments[symbol] = Instrument(
            symbol=symbol, name="标的自定义", market=asset_type, exchange=exchange,
            contract_multiplier=float(payload.multipliers.get(symbol, 10.0)) if asset_type == "future" else 1.0,
        )

    # 2. 逐个取值跑回测，收集指标
    results = []
    for v in payload.values:
        params = dict(payload.params)
        params[payload.param] = v
        try:
            strategy = STRATEGY_REGISTRY[payload.strategy](params)
            engine = BacktestEngine(
                strategy, data, initial_cash=payload.initial_cash, instruments=instruments
            )
            res = engine.run()
            m = PerformanceMetrics(res.equity_curve, payload.initial_cash, res.trades)
            value = getattr(m, payload.metric, None)
        except Exception as exc:
            value = None
            logger.warning("sensitivity value=%s failed: %s", v, exc)
        results.append({
            "param_value": v,
            "metric": payload.metric,
            "value": round(value, 6) if isinstance(value, (int, float)) else None,
        })

    return {
        "strategy": payload.strategy,
        "param": payload.param,
        "metric": payload.metric,
        "points": results,
    }


# --------------------------------------------------------------------------- #
# 蒙特卡洛鲁棒性模拟（V15）
# --------------------------------------------------------------------------- #
def _run_engine_for_mc(spec: dict) -> "BacktestResult":
    """复用 /run 的行情拉取 + 建仓 + 运行逻辑，返回引擎结果（供蒙特卡洛重采样）。

    与普通 /run 的不同：不生成/落盘报告，只返回引擎结果对象。
    """
    from ..backtest.engine import BacktestResult  # noqa: F811

    data: Dict[str, List[Bar]] = {}
    symbols = spec.get("symbols") or []
    start = spec.get("start")
    end = spec.get("end")
    interval = spec.get("interval", "daily")
    asset_types = spec.get("asset_types", {}) or {}
    multipliers = spec.get("multipliers", {}) or {}
    initial_cash = float(spec.get("initial_cash", 1_000_000.0))
    for symbol in symbols:
        try:
            bars = market_service.bars(symbol, start, end, interval=interval)
        except Exception as exc:
            raise HTTPException(status_code=503, detail=f"行情获取失败: {symbol}") from exc
        if not bars:
            raise HTTPException(
                status_code=422,
                detail=f"标的 {symbol} 在 {start}~{end} 无行情数据",
            )
        data[symbol] = bars

    instruments: Dict[str, Instrument] = {}
    for symbol in symbols:
        asset_type = asset_types.get(symbol, "stock")
        exchange = "CFFEX" if asset_type == "future" else ("SH" if asset_type == "stock" else "")
        instruments[symbol] = Instrument(
            symbol=symbol,
            name="标的自定义",
            market=asset_type,
            exchange=exchange,
            contract_multiplier=float(multipliers.get(symbol, 10.0)) if asset_type == "future" else 1.0,
        )

    factory = STRATEGY_REGISTRY[spec["strategy"]]
    strategy = factory(spec.get("params", {}) or {})
    engine = BacktestEngine(
        strategy, data, initial_cash=initial_cash, instruments=instruments
    )
    result: BacktestResult = engine.run()
    return result


class MonteCarloRequest(BaseModel):
    run_id: Optional[str] = Field(
        default=None, description="已存报告 run_id（优先）：基于其净值曲线做模拟"
    )
    # 运行参数（run_id 为空时必填，等价于 /run 的运行部分）
    strategy: Optional[str] = Field(default=None, description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(default_factory=dict, description="策略参数")
    symbols: List[str] = Field(default_factory=list, description="回测标的")
    start: Optional[str] = Field(default=None, description="起始日期 YYYY-MM-DD")
    end: Optional[str] = Field(default=None, description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(default_factory=dict, description="标的资产类型覆盖")
    multipliers: Dict[str, float] = Field(default_factory=dict, description="期货合约乘数覆盖")
    interval: str = Field(default="daily", description="行情频率：daily / minute")
    n_sims: int = Field(default=200, gt=0, le=2000, description="模拟路径条数")
    seed: Optional[int] = Field(default=42, description="随机种子（固定可复现）")
    confidence: float = Field(default=0.9, gt=0.0, lt=1.0, description="置信带水平（0.9 -> P5~P95）")
    block_size: int = Field(default=1, ge=1, le=60, description="块自助块大小（1=普通自助）")


@router.post("/montecarlo", summary="蒙特卡洛鲁棒性模拟（V15）")
def montecarlo_analysis(payload: MonteCarloRequest) -> dict:
    if payload.run_id:
        try:
            report = report_store.load(payload.run_id)
        except FileNotFoundError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        report = _normalize_report(report)
        curve = report.get("equity_curve") or []
        if not curve:
            raise HTTPException(status_code=422, detail="该报告无净值曲线，无法模拟")
        initial = curve[0].get("total_value") or payload.initial_cash
        strat = report.get("strategy") or report.get("strategy_name") or "已存报告"
        run_id = payload.run_id
    else:
        if not payload.strategy or payload.strategy not in STRATEGY_REGISTRY:
            raise HTTPException(
                status_code=422,
                detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}",
            )
        if not payload.symbols:
            raise HTTPException(status_code=422, detail="symbols 不能为空")
        if not payload.start or not payload.end:
            raise HTTPException(status_code=422, detail="start / end 必填")
        if payload.end < payload.start:
            raise HTTPException(status_code=422, detail="end 不得早于 start")
        if payload.interval not in ("daily", "minute"):
            raise HTTPException(status_code=422, detail=f"不支持的行情频率 {payload.interval!r}")
        result = _run_engine_for_mc(payload.model_dump())
        curve = [p.to_dict() for p in result.equity_curve]
        initial = payload.initial_cash
        strat = payload.strategy
        run_id = None

    try:
        mc = monte_carlo(
            curve,
            initial,
            n_sims=payload.n_sims,
            seed=payload.seed,
            confidence=payload.confidence,
            block_size=payload.block_size,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    mc["strategy"] = strat
    mc["run_id"] = run_id
    return mc


# --------------------------------------------------------------------------- #
# 多参数敏感性网格（V16）
# --------------------------------------------------------------------------- #
class SensitivityGridRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(default_factory=dict, description="固定参数（不参与扫描的部分）")
    grid: Dict[str, List[object]] = Field(
        ..., min_length=1, description="待扫描的两个参数的取值网格 {param_a: [...], param_b: [...]}"
    )
    symbols: List[str] = Field(..., min_length=1, description="回测标的")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(default_factory=dict, description="标的资产类型覆盖")
    multipliers: Dict[str, float] = Field(default_factory=dict, description="期货合约乘数覆盖")
    interval: str = Field(default="daily", description="行情频率：daily / minute")
    metric: str = Field(
        default="total_return",
        description="扫描指标：total_return / annual_return / sharpe / max_drawdown / win_rate / final_value",
    )


@router.post("/sensitivity-grid", summary="多参数敏感性网格（双参数扫描热力图，V16）")
def sensitivity_grid_analysis(payload: SensitivityGridRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.interval not in ("daily", "minute"):
        raise HTTPException(status_code=422, detail=f"不支持的行情频率 {payload.interval!r}")
    if payload.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422, detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}"
        )
    if payload.metric not in ("total_return", "annual_return", "sharpe", "max_drawdown", "win_rate", "final_value"):
        raise HTTPException(status_code=422, detail=f"不支持的指标 {payload.metric!r}")
    try:
        return _sensitivity_grid(
            strategy=payload.strategy,
            params=dict(payload.params),
            grid={k: list(v) for k, v in payload.grid.items()},
            symbols=payload.symbols,
            start=payload.start,
            end=payload.end,
            initial_cash=payload.initial_cash,
            asset_types=payload.asset_types,
            multipliers=payload.multipliers,
            interval=payload.interval,
            metric=payload.metric,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# Walk-forward 样本外验证（V16）
# --------------------------------------------------------------------------- #
class WalkForwardRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(default_factory=dict, description="固定参数")
    symbols: List[str] = Field(..., min_length=1, description="回测标的")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(default_factory=dict, description="标的资产类型覆盖")
    multipliers: Dict[str, float] = Field(default_factory=dict, description="期货合约乘数覆盖")
    interval: str = Field(default="daily", description="行情频率：daily / minute")
    n_folds: int = Field(default=5, ge=2, le=20, description="折数（扩张窗口：训练从起点增长，测试为第 k 折）")


@router.post("/walkforward", summary="Walk-forward 样本外验证（V16）")
def walkforward_analysis(payload: WalkForwardRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.interval not in ("daily", "minute"):
        raise HTTPException(status_code=422, detail=f"不支持的行情频率 {payload.interval!r}")
    if payload.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422, detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}"
        )
    try:
        return _walk_forward(
            strategy=payload.strategy,
            params=dict(payload.params),
            symbols=payload.symbols,
            start=payload.start,
            end=payload.end,
            initial_cash=payload.initial_cash,
            asset_types=payload.asset_types,
            multipliers=payload.multipliers,
            interval=payload.interval,
            n_folds=payload.n_folds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


# --------------------------------------------------------------------------- #
# 自定义基准对比（V16）
# --------------------------------------------------------------------------- #
class BenchmarkDef(BaseModel):
    name: str = Field(..., description="基准名称（用于展示）")
    symbols: Optional[List[str]] = Field(
        default=None, description="基准篮子标的（与 weights 配合，加权买入持有）"
    )
    weights: Optional[List[float]] = Field(
        default=None, description="篮子权重（默认等权）；长度需与 symbols 一致"
    )
    values: Optional[List[float]] = Field(
        default=None, description="显式基准序列（按策略净值曲线逐日对齐，长度需一致）"
    )


class BenchmarkCompareRequest(BaseModel):
    run_id: str = Field(..., description="已存回测报告 run_id（策略曲线来源）")
    benchmarks: List[BenchmarkDef] = Field(
        ..., min_length=1, description="自定义基准列表（篮子或显式序列）"
    )


@router.post("/benchmark-compare", summary="自定义基准对比（篮子/显式序列 vs 已存报告，V16）")
def benchmark_compare(payload: BenchmarkCompareRequest) -> dict:
    try:
        report = report_store.load(payload.run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    report = _normalize_report(report)
    curve = report.get("equity_curve") or []
    if not curve:
        raise HTTPException(status_code=422, detail="该报告无净值曲线，无法对比")
    dates = [p.get("date") for p in curve]
    initial = curve[0].get("total_value") or payload.initial_cash or 1_000_000.0
    trades = report.get("trades") or []
    strat_values = [p.get("total_value") for p in curve]

    results = []
    for b in payload.benchmarks:
        bd = b.model_dump()
        try:
            bv = _build_benchmark_values(bd, dates, initial, report.get("interval", "daily"))
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=f"基准「{b.name}」: {exc}") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=f"基准「{b.name}」: {exc}") from exc
        # 相对绩效：复用 PerformanceMetrics 的基准归因（beta/alpha/TE/IR/超额）
        from ..backtest.engine import EquityPoint  # noqa: F401
        eq_points = [
            EquityPoint(
                date=p.get("date"),
                cash=p.get("cash", 0.0),
                market_value=p.get("market_value", 0.0),
                total_value=p.get("total_value", 0.0),
                daily_return=p.get("daily_return", 0.0) or 0.0,
            )
            for p in curve
        ]
        m = PerformanceMetrics(eq_points, initial, trades, benchmark_values=bv)
        rel = dict(m._attribution.get("benchmark", {}))
        results.append({
            "name": b.name,
            "relative": rel,
            "curve": [{"date": d, "value": round(v, 2)} for d, v in zip(dates, bv)],
        })

    return {
        "run_id": payload.run_id,
        "strategy": report.get("strategy") or report.get("strategy_name"),
        "symbols": report.get("symbols"),
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "interval": report.get("interval", "daily"),
        "strategy_curve": [{"date": d, "value": round(v, 2)} for d, v in zip(dates, strat_values)],
        "benchmarks": results,
    }


# --------------------------------------------------------------------------- #
# V17 高级分析三件套（因子衰减 / 参数稳健性 / 多基准加权）
# --------------------------------------------------------------------------- #
class FactorDecayRequest(BaseModel):
    symbols: List[str] = Field(
        default_factory=list, description="研究标的池（默认内置合成标的池）"
    )
    start: str = Field(default="2000-01-01", description="起始日期 YYYY-MM-DD")
    end: str = Field(default="2100-01-01", description="结束日期 YYYY-MM-DD")
    window: int = Field(default=10, ge=2, description="因子计算回看窗口")
    forward: int = Field(default=1, ge=1, description="收益前瞻天数")
    roll_window: int = Field(default=10, ge=2, description="滚动均值窗口（期数）")


@router.post("/factor-decay", summary="因子 IC 衰减/稳定性分析（滚动 IC 趋势，V17）")
def factor_decay_analysis(payload: FactorDecayRequest) -> dict:
    try:
        return _factor_decay(
            symbols=payload.symbols or None,
            start=payload.start,
            end=payload.end,
            window=payload.window,
            forward=payload.forward,
            roll_window=payload.roll_window,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class RobustnessRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(default_factory=dict, description="固定参数（不参与扫描的部分）")
    grid: Dict[str, List[object]] = Field(
        ..., min_length=1, description="待扫描的两个参数的取值网格 {param_a: [...], param_b: [...]}"
    )
    symbols: List[str] = Field(..., min_length=1, description="回测标的")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="初始资金")
    asset_types: Dict[str, str] = Field(default_factory=dict, description="标的资产类型覆盖")
    multipliers: Dict[str, float] = Field(default_factory=dict, description="期货合约乘数覆盖")
    interval: str = Field(default="daily", description="行情频率：daily / minute")
    n_folds: int = Field(default=5, ge=2, le=20, description="walk-forward 折数")
    metric: str = Field(
        default="total_return",
        description="扫描指标：total_return / annual_return / sharpe / max_drawdown / win_rate / final_value",
    )


@router.post("/robustness", summary="参数最优区间稳健性（grid×walk-forward 联动，V17）")
def robustness_analysis(payload: RobustnessRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.interval not in ("daily", "minute"):
        raise HTTPException(status_code=422, detail=f"不支持的行情频率 {payload.interval!r}")
    if payload.strategy not in STRATEGY_REGISTRY:
        raise HTTPException(
            status_code=422, detail=f"未知策略 {payload.strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}"
        )
    if payload.metric not in ("total_return", "annual_return", "sharpe", "max_drawdown", "win_rate", "final_value"):
        raise HTTPException(status_code=422, detail=f"不支持的指标 {payload.metric!r}")
    try:
        return _parameter_robustness(
            strategy=payload.strategy,
            params=dict(payload.params),
            grid={k: list(v) for k, v in payload.grid.items()},
            symbols=payload.symbols,
            start=payload.start,
            end=payload.end,
            initial_cash=payload.initial_cash,
            asset_types=payload.asset_types,
            multipliers=payload.multipliers,
            interval=payload.interval,
            n_folds=payload.n_folds,
            metric=payload.metric,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


class WeightedBenchmarkDef(BaseModel):
    name: str = Field(..., description="基准名称")
    weight: float = Field(default=1.0, gt=0, description="在复合基准中的权重")
    symbols: Optional[List[str]] = Field(default=None, description="基准篮子标的")
    weights: Optional[List[float]] = Field(default=None, description="篮子内权重（默认等权）")
    values: Optional[List[float]] = Field(default=None, description="显式基准序列（长度需与策略曲线一致）")


class WeightedBenchmarkRequest(BaseModel):
    run_id: str = Field(..., description="已存回测报告 run_id（策略曲线来源）")
    benchmarks: List[WeightedBenchmarkDef] = Field(
        ..., min_length=1, description="多个基准（各自带 weight），组成加权复合基准"
    )
    initial_cash: float = Field(default=0.0, gt=0, description="初始资金（默认取报告首点净值）")


@router.post("/benchmark-weighted", summary="多基准加权对比（复合加权基准 vs 已存报告，V17）")
def benchmark_weighted(payload: WeightedBenchmarkRequest) -> dict:
    try:
        report = report_store.load(payload.run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    report = _normalize_report(report)
    curve = report.get("equity_curve") or []
    if not curve:
        raise HTTPException(status_code=422, detail="该报告无净值曲线，无法对比")
    initial = payload.initial_cash or curve[0].get("total_value") or 1_000_000.0
    try:
        cmp = _weighted_benchmark_compare(
            run_equity_curve=curve,
            benchmarks=[b.model_dump() for b in payload.benchmarks],
            initial_cash=initial,
            interval=report.get("interval", "daily"),
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    dates = [p.get("date") for p in curve]
    strat_values = [p.get("total_value") for p in curve]
    return {
        "run_id": payload.run_id,
        "strategy": report.get("strategy") or report.get("strategy_name"),
        "symbols": report.get("symbols"),
        "start_date": dates[0] if dates else None,
        "end_date": dates[-1] if dates else None,
        "interval": report.get("interval", "daily"),
        "strategy_curve": [{"date": d, "value": round(v, 2)} for d, v in zip(dates, strat_values)],
        "composite_relative": cmp["composite_relative"],
        "composite_curve": cmp["composite_curve"],
        "benchmarks": cmp["benchmarks"],
    }


def _normalize_report(r: dict) -> dict:
    """补齐组合回测报告缺失的顶层展示字段，使其与单标的报告 schema 一致。

    仅做向后兼容的回填（不写回磁盘），让历史报告也能在报告中心正确展示。
    """
    if r.get("type") == "portfolio":
        r.setdefault("strategy", r.get("strategy_name") or "组合回测")
        if not r.get("symbols"):
            syms = []
            for leg in r.get("legs", []):
                for s in leg.get("symbols", []) or []:
                    if s not in syms:
                        syms.append(s)
            if syms:
                r["symbols"] = syms
        curve = r.get("equity_curve") or []
        if curve:
            r.setdefault("start_date", curve[0].get("date"))
            r.setdefault("end_date", curve[-1].get("date"))
    return r


@router.get("/reports", summary="回测报告列表")
def list_reports() -> dict:
    ids = report_store.list()
    summaries = []
    for rid in ids:
        try:
            r = report_store.load(rid)
        except Exception:
            continue
        r = _normalize_report(r)
        m = r.get("metrics", {}) or {}
        summaries.append(
            {
                "run_id": rid,
                "strategy": r.get("strategy"),
                "symbols": r.get("symbols"),
                "start_date": r.get("start_date"),
                "end_date": r.get("end_date"),
                "tags": r.get("tags") or [],
                "notes": r.get("notes") or "",
                "total_return": m.get("total_return"),
                "annual_return": m.get("annual_return"),
                "sharpe": m.get("sharpe"),
                "max_drawdown": m.get("max_drawdown"),
                "win_rate": m.get("win_rate"),
                "factors": r.get("factors") or [],
                "factor_count": len(r.get("factors") or []),
            }
        )
    return {"items": ids, "summaries": summaries}


@router.get("/reports/{run_id}", summary="回测报告详情")
def get_report(run_id: str) -> dict:
    try:
        r = report_store.load(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return _normalize_report(r)


@router.get("/reports/{run_id}/factors", summary="报告关联因子的 IC/IR（V3.2 策略排行榜）")
def report_factors(run_id: str) -> dict:
    """按报告记录的 symbols / 日期区间 / factors，计算并返回各因子 IC/IR。

    - 若报告无 factors，按 strategy 取内置策略默认因子；
    - 若因子不在因子库，自动过滤并提示；
    - 窗口使用默认值 10，forward=1。
    """
    try:
        r = report_store.load(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    r = _normalize_report(r)
    factors = list(r.get("factors") or default_factors(r.get("strategy") or ""))
    symbols = r.get("symbols") or []
    if not factors:
        return {"factors": [], "items": [], "symbols": symbols, "notice": "未配置关联因子"}
    if not symbols:
        return {"factors": factors, "items": [], "symbols": [], "notice": "报告无标的"}

    valid_factors = {f["name"] for f in list_factors()}
    unknown = [f for f in factors if f not in valid_factors]
    factors = [f for f in factors if f in valid_factors]

    start = r.get("start_date") or "2000-01-01"
    end = r.get("end_date") or "2100-01-01"
    try:
        ic = factor_research.ic_analysis(symbols=symbols, start=start, end=end, window=10, forward=1)
    except Exception as exc:
        logger.warning("report %s factor ic failed: %s", run_id, exc)
        raise HTTPException(status_code=503, detail=f"因子 IC 计算失败: {exc}") from exc

    items = []
    for f in factors:
        res = ic["results"].get(f, {})
        items.append(
            {
                "factor": f,
                "mean_ic": res.get("mean_ic"),
                "std_ic": res.get("std_ic"),
                "ir": res.get("ir"),
                "ic_positive_ratio": res.get("ic_positive_ratio"),
                "observations": res.get("observations", 0),
            }
        )
    return {
        "factors": factors,
        "items": items,
        "symbols": symbols,
        "start_date": start,
        "end_date": end,
        "forward_days": 1,
        "unknown": unknown,
    }


class ReportPatchRequest(BaseModel):
    tags: Optional[List[str]] = Field(None, description="实验标签（如 基线/参数组A）")
    notes: Optional[str] = Field(None, description="实验备注")


@router.patch("/reports/{run_id}", summary="更新报告标签/备注（V9.0 实验追踪）")
def patch_report(run_id: str, body: ReportPatchRequest) -> dict:
    try:
        return report_store.patch(run_id, tags=body.tags, notes=body.notes)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.get("/tags", summary="回测实验标签全集（V9.0）")
def list_tags() -> dict:
    """聚合所有报告的标签，供前端筛选。"""
    ids = report_store.list()
    tag_set: Dict[str, int] = {}
    for rid in ids:
        try:
            r = report_store.load(rid)
        except Exception:
            continue
        for t in (r.get("tags") or []):
            tag_set[t] = tag_set.get(t, 0) + 1
    return {"items": sorted(tag_set.items(), key=lambda kv: (-kv[1], kv[0]))}


# --------------------------------------------------------------------------- #
# 回测对比与排行榜（V2.8）
# --------------------------------------------------------------------------- #
_LEADERBOARD_METRICS = {
    "sharpe": "夏普比率",
    "total_return": "总收益率",
    "annual_return": "年化收益",
    "max_drawdown": "最大回撤",
    "win_rate": "胜率",
}


def _curve_to_pct(curve: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """把净值曲线归一化为累计收益率（%），便于不同初始资金横向对比。"""
    if not curve:
        return []
    base = curve[0].get("total_value") or 0.0
    out = []
    for p in curve:
        tv = p.get("total_value") or 0.0
        pct = (tv / base - 1.0) * 100.0 if base else 0.0
        out.append({"date": p.get("date"), "pct": round(pct, 4)})
    return out


@router.get("/compare", summary="回测对比：多任务指标 + 归一化净值曲线")
def compare_reports(ids: str = "") -> dict:
    """传入逗号分隔的 run_id 列表，返回可用于并排对比的结构化数据。

    - ``ids`` 为空时返回空列表（前端据此提示先选择）。
    - 每条返回：run_id / strategy / symbols / 区间 / metrics / curve_pct（累计收益率%）。
    """
    run_ids = [x.strip() for x in ids.split(",") if x.strip()]
    items = []
    for rid in run_ids:
        try:
            r = report_store.load(rid)
        except FileNotFoundError:
            continue
        r = _normalize_report(r)
        m = r.get("metrics", {}) or {}
        items.append(
            {
                "run_id": rid,
                "strategy": r.get("strategy"),
                "symbols": r.get("symbols"),
                "start_date": r.get("start_date"),
                "end_date": r.get("end_date"),
                "interval": r.get("interval"),
                "metrics": m,
                "curve_pct": _curve_to_pct(r.get("equity_curve", []) or []),
            }
        )
    return {"items": items}


@router.get("/leaderboard", summary="回测排行榜：按指标排序")
def leaderboard(
    metric: str = "sharpe",
    order: str = "desc",
    limit: int = 20,
) -> dict:
    """对所有已保存回测报告按指定指标排序，形成策略排行榜。

    - ``metric``：sharpe / total_return / annual_return / max_drawdown / win_rate
    - ``order``：desc（默认）或 asc；注意 max_drawdown 越小越好，前端可据此反转展示。
    """
    if metric not in _LEADERBOARD_METRICS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的指标 {metric!r}，可选: {sorted(_LEADERBOARD_METRICS)}",
        )
    order = order if order in ("asc", "desc") else "desc"

    ids = report_store.list()
    rows = []
    for rid in ids:
        try:
            r = report_store.load(rid)
        except Exception:
            continue
        r = _normalize_report(r)
        m = r.get("metrics", {}) or {}
        val = m.get(metric)
        if val is None:
            continue
        rows.append(
            {
                "run_id": rid,
                "strategy": r.get("strategy"),
                "symbols": r.get("symbols"),
                "start_date": r.get("start_date"),
                "end_date": r.get("end_date"),
                "metric": metric,
                "metric_label": _LEADERBOARD_METRICS[metric],
                "value": val,
                "metrics": {
                    "total_return": m.get("total_return"),
                    "annual_return": m.get("annual_return"),
                    "sharpe": m.get("sharpe"),
                    "max_drawdown": m.get("max_drawdown"),
                    "win_rate": m.get("win_rate"),
                },
            }
        )

    reverse = order == "desc"
    rows.sort(key=lambda x: (x["value"] is None, x["value"]), reverse=reverse)
    return {
        "items": rows[: max(1, min(limit, 200))],
        "metric": metric,
        "metric_label": _LEADERBOARD_METRICS[metric],
        "order": order,
    }


# --------------------------------------------------------------------------- #
# 报告导出（V2.2）
# --------------------------------------------------------------------------- #
@router.get("/reports/{run_id}/export", summary="回测报告导出（csv / json）")
def export_report(run_id: str, format: str = "csv") -> Response:
    if format not in ("csv", "json"):
        raise HTTPException(status_code=422, detail="format 仅支持 csv / json")
    try:
        report = report_store.load(run_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    report = _normalize_report(report)

    if format == "json":
        content = json.dumps(report, ensure_ascii=False, indent=2)
        return Response(
            content,
            media_type="application/json",
            headers={
                "Content-Disposition": f'attachment; filename="backtest_{run_id}.json"'
            },
        )

    # CSV：指标 + 净值曲线 + 交易明细，三段式便于 Excel 直接打开
    buf = io.StringIO()
    writer = csv.writer(buf)
    meta = report.get("metrics", {}) or {}
    writer.writerow(["# 绩效指标"])
    for k, v in meta.items():
        writer.writerow([k, v])
    writer.writerow([])
    curve = report.get("equity_curve", []) or []
    writer.writerow(["# 净值曲线"])
    if curve:
        cols = list(curve[0].keys())
        writer.writerow(cols)
        for row in curve:
            writer.writerow([row.get(c) for c in cols])
    writer.writerow([])
    trades = report.get("trades", []) or []
    writer.writerow(["# 交易明细"])
    if trades:
        tcols = list(trades[0].keys())
        writer.writerow(tcols)
        for t in trades:
            writer.writerow([t.get(c) for c in tcols])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="backtest_{run_id}.csv"'
        },
    )


# --------------------------------------------------------------------------- #
# 组合回测（V1.2）
# --------------------------------------------------------------------------- #
class PortfolioLegRequest(BaseModel):
    strategy: str = Field(..., description="策略名称（见 /strategies）")
    params: Dict[str, object] = Field(default_factory=dict, description="策略参数")
    symbols: List[str] = Field(..., min_length=1, description="回测标的")
    asset_types: Dict[str, str] = Field(
        default_factory=dict, description="标的资产类型覆盖（symbol -> stock/fund/future）"
    )
    multipliers: Dict[str, float] = Field(
        default_factory=dict, description="期货合约乘数覆盖（symbol -> 乘数；future 默认 10）"
    )
    interval: str = Field(
        default="daily", description="行情频率：daily 或 minute（V1.2）"
    )
    weight: float = Field(default=1.0, gt=0, description="组合权重（自动归一化）")


class PortfolioRunRequest(BaseModel):
    legs: List[PortfolioLegRequest] = Field(..., min_length=1, description="组合各腿")
    initial_cash: float = Field(default=1_000_000.0, gt=0, description="总初始资金")
    start: str = Field(..., description="起始日期 YYYY-MM-DD")
    end: str = Field(..., description="结束日期 YYYY-MM-DD")
    rebalance: str = Field(
        default="none",
        description="再平衡频率：none(买入持有) / D(日) / W(周) / M(月) / Q(季) / Y(年)",
    )
    benchmark_symbol: Optional[str] = Field(
        default=None, description="组合基准标的（equal-weight 买入持有，可选）"
    )


@router.post("/portfolio", summary="组合回测（多腿合并净值，支持再平衡）")
def run_portfolio(payload: PortfolioRunRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.rebalance not in ("none", "D", "W", "M", "Q", "Y"):
        raise HTTPException(
            status_code=422,
            detail=f"不支持的再平衡频率 {payload.rebalance!r}（可选 none/D/W/M/Q/Y）",
        )
    legs = [l.model_dump() for l in payload.legs]
    try:
        pb = PortfolioBacktest(
            legs=legs,
            initial_cash=payload.initial_cash,
            start=payload.start,
            end=payload.end,
            rebalance=payload.rebalance,
            benchmark_symbol=payload.benchmark_symbol,
        )
        report = pb.run()
    except BacktestError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except Exception as exc:  # 行情源失败统一转 503
        logger.warning("portfolio backtest failed: %s", exc)
        raise HTTPException(status_code=503, detail=f"组合回测失败: {exc}") from exc
    report_store.save(report)
    logger.info("portfolio backtest %s generated (%d legs)", report["run_id"], len(legs))
    return report
