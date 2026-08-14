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
from ..backtest.optimizer import OptimizeConfigError, optimize
from ..backtest.portfolio import PortfolioBacktest
from ..backtest.strategies import STRATEGY_REGISTRY
from ..core.auth import get_current_user
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
    report = build_report(
        result,
        strategy_name=payload.strategy_name or payload.strategy,
        strategy_config=payload.params,
        benchmark_symbol=payload.benchmark_symbol,
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
    rebalance: str = Field(default="none", description="再平衡方式（当前仅支持 none）")


@router.post("/portfolio", summary="组合回测（多腿合并净值）")
def run_portfolio(payload: PortfolioRunRequest) -> dict:
    if payload.end < payload.start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    if payload.rebalance != "none":
        raise HTTPException(
            status_code=422, detail=f"暂不支持再平衡方式 {payload.rebalance!r}（当前仅 none）"
        )
    legs = [l.model_dump() for l in payload.legs]
    try:
        pb = PortfolioBacktest(
            legs=legs,
            initial_cash=payload.initial_cash,
            start=payload.start,
            end=payload.end,
            rebalance=payload.rebalance,
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
