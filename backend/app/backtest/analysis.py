"""高级回测分析（V16 无凭证功能集合）。

包含三类分析，均复用现有事件驱动引擎，无需任何外部凭证：

1. 多参数敏感性网格（``sensitivity_grid``）：固定其余参数，扫描两个参数的笛卡尔积，
   逐格回测并产出指标矩阵（供前端热力图）。
2. Walk-forward 样本外验证（``walk_forward``）：将区间切分为 N 折，做「扩张窗口」
   训练（样本内）/ 测试（样本外）验证，评估策略在 unseen 数据上的稳定性与衰减。
3. 自定义基准构建（``build_benchmark_values``）：由多标的加权篮子或显式序列构建与
   策略净值曲线对齐的基准，供相对绩效（beta/alpha/TE/IR）计算。

行情通过 ``market_service`` 拉取；测试中以 monkeypatch 替换。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence, Tuple

from ..market.models import Instrument
from ..market.service import market_service
from ..backtest.engine import BacktestEngine, BacktestResult
from ..backtest.metrics import PerformanceMetrics
from ..backtest.strategies import STRATEGY_REGISTRY

_METRICS = ("total_return", "annual_return", "sharpe", "max_drawdown", "win_rate", "final_value")


def _build_instruments(
    symbols: Sequence[str],
    asset_types: Optional[Dict[str, str]] = None,
    multipliers: Optional[Dict[str, float]] = None,
) -> Dict[str, Instrument]:
    asset_types = asset_types or {}
    multipliers = multipliers or {}
    instruments: Dict[str, Instrument] = {}
    for sym in symbols:
        at = asset_types.get(sym, "stock")
        exchange = "CFFEX" if at == "future" else ("SH" if at == "stock" else "")
        instruments[sym] = Instrument(
            symbol=sym,
            name="标的自定义",
            market=at,
            exchange=exchange,
            contract_multiplier=float(multipliers.get(sym, 10.0)) if at == "future" else 1.0,
        )
    return instruments


def run_engine(
    symbols: Sequence[str],
    strategy: str,
    params: Dict[str, Any],
    start: str,
    end: str,
    initial_cash: float = 1_000_000.0,
    asset_types: Optional[Dict[str, str]] = None,
    multipliers: Optional[Dict[str, float]] = None,
    interval: str = "daily",
) -> BacktestResult:
    """拉取 [start, end] 行情并运行引擎，返回结果对象。

    与 ``/run`` 逻辑一致但不落盘报告；``start``/``end`` 可覆盖 spec 区间，
    便于 walk-forward 在子窗口上重跑。
    """
    data: Dict[str, List[Any]] = {}
    for sym in symbols:
        try:
            bars = market_service.bars(sym, start, end, interval=interval)
        except Exception as exc:  # 统一转 503 语义错误由调用方捕获
            raise RuntimeError(f"行情获取失败: {sym}") from exc
        if not bars:
            raise ValueError(f"标的 {sym} 在 {start}~{end} 无行情数据")
        data[sym] = bars
    instruments = _build_instruments(symbols, asset_types, multipliers)
    factory = STRATEGY_REGISTRY[strategy]
    engine = BacktestEngine(
        factory(params), data, initial_cash=initial_cash, instruments=instruments
    )
    return engine.run()


def metrics_of(
    result: BacktestResult,
    initial_cash: float,
    metric: str,
) -> Optional[float]:
    """从一次引擎结果取指定指标值。"""
    if metric not in _METRICS:
        raise ValueError(f"不支持的指标 {metric!r}，可选: {_METRICS}")
    m = PerformanceMetrics(result.equity_curve, initial_cash, result.trades)
    val = getattr(m, metric, None)
    return val


def _all_metrics(result: BacktestResult, initial_cash: float) -> Dict[str, Optional[float]]:
    m = PerformanceMetrics(result.equity_curve, initial_cash, result.trades)
    return {
        "total_return": m.total_return,
        "annual_return": m.annual_return,
        "sharpe": m.sharpe,
        "max_drawdown": m.max_drawdown,
        "win_rate": m.win_rate,
        "final_value": m.equity[-1].total_value if m.equity else None,
        "days": m.days,
    }


# --------------------------------------------------------------------------- #
# 1. 多参数敏感性网格
# --------------------------------------------------------------------------- #
def sensitivity_grid(
    strategy: str,
    params: Dict[str, Any],
    grid: Dict[str, List[Any]],
    symbols: Sequence[str],
    start: str,
    end: str,
    initial_cash: float = 1_000_000.0,
    asset_types: Optional[Dict[str, str]] = None,
    multipliers: Optional[Dict[str, float]] = None,
    interval: str = "daily",
    metric: str = "total_return",
) -> Dict[str, Any]:
    """扫描两个参数的笛卡尔积，产出指标矩阵。

    ``grid`` 需恰好含两个键（param_a / param_b）。返回：
    { param_a, param_a_values, param_b, param_b_values, metric,
      grid: [[value_i_j]], best: {param_a, param_b, value} }
    """
    keys = list(grid.keys())
    if len(keys) != 2:
        raise ValueError("sensitivity_grid 的 grid 必须恰好包含两个参数")
    pa, pb = keys
    va_list = list(grid[pa])
    vb_list = list(grid[pb])
    if not va_list or not vb_list:
        raise ValueError("grid 两个参数都至少需要一个取值")

    matrix: List[List[Optional[float]]] = []
    best: Dict[str, Any] = {"param_a": None, "param_b": None, "value": None}
    for va in va_list:
        row: List[Optional[float]] = []
        for vb in vb_list:
            p = dict(params)
            p[pa] = va
            p[pb] = vb
            try:
                res = run_engine(
                    symbols, strategy, p, start, end, initial_cash,
                    asset_types, multipliers, interval,
                )
                val = metrics_of(res, initial_cash, metric)
            except Exception:
                val = None
            row.append(round(val, 6) if isinstance(val, (int, float)) else None)
            if isinstance(val, (int, float)) and (
                best["value"] is None or val > best["value"]
            ):
                best = {"param_a": va, "param_b": vb, "value": round(val, 6)}
        matrix.append(row)

    return {
        "strategy": strategy,
        "metric": metric,
        "param_a": pa,
        "param_a_values": va_list,
        "param_b": pb,
        "param_b_values": vb_list,
        "grid": matrix,
        "best": best,
    }


# --------------------------------------------------------------------------- #
# 2. Walk-forward 样本外验证
# --------------------------------------------------------------------------- #
def split_walkforward(dates: Sequence[str], n_folds: int) -> List[Tuple[str, str, str, str]]:
    """把日期序列切成 N 折的扩张窗口训练/测试区间。

    返回 N-1 个 (train_start, train_end, test_start, test_end)。
    训练区间固定从 dates[0] 起（扩张），测试区间依次为第 k 折。
    """
    n = len(dates)
    if n < 4 or n_folds < 2:
        return []
    n_folds = min(n_folds, max(2, n // 2))  # 保证每折至少有 1~2 天
    seg = max(1, n // n_folds)
    boundaries = [0]
    for k in range(1, n_folds):
        boundaries.append(min(k * seg, n - 1))
    boundaries.append(n - 1)
    folds: List[Tuple[str, str, str, str]] = []
    for k in range(1, n_folds):
        train_start = dates[0]
        train_end = dates[boundaries[k] - 1]
        test_start = dates[boundaries[k]]
        test_end = dates[boundaries[k + 1]]
        if test_end < test_start:
            continue
        folds.append((train_start, train_end, test_start, test_end))
    return folds


def walk_forward(
    strategy: str,
    params: Dict[str, Any],
    symbols: Sequence[str],
    start: str,
    end: str,
    initial_cash: float = 1_000_000.0,
    asset_types: Optional[Dict[str, str]] = None,
    multipliers: Optional[Dict[str, float]] = None,
    interval: str = "daily",
    n_folds: int = 5,
) -> Dict[str, Any]:
    """扩张窗口 walk-forward：逐折在训练/测试窗口上回测，报告样本外表现。

    返回：
    { strategy, n_folds, folds:[{train_period, test_period, is_metrics, oos_metrics,
      degradation_total_return, degradation_sharpe}],
      summary:{mean_is_return, mean_oos_return, mean_is_sharpe, mean_oos_sharpe,
      oos_positive_rate, oos_beats_is_rate} }
    """
    # 取首个标的的日期作为时间轴划分依据
    try:
        bars = market_service.bars(symbols[0], start, end, interval=interval)
    except Exception as exc:
        raise RuntimeError(f"行情获取失败: {symbols[0]}") from exc
    if not bars:
        raise ValueError(f"标的 {symbols[0]} 在 {start}~{end} 无行情数据")
    dates = [b.date for b in bars]
    folds = split_walkforward(dates, n_folds)
    if not folds:
        raise ValueError("样本区间过短，无法做 walk-forward（至少需要 4 个交易日且 n_folds>=2）")

    records: List[Dict[str, Any]] = []
    is_returns: List[float] = []
    oos_returns: List[float] = []
    is_sharpes: List[float] = []
    oos_sharpes: List[float] = []
    oos_positive = 0
    oos_beats_is = 0

    for train_s, train_e, test_s, test_e in folds:
        try:
            res_is = run_engine(symbols, strategy, params, train_s, train_e, initial_cash,
                                asset_types, multipliers, interval)
            is_m = _all_metrics(res_is, initial_cash)
        except Exception:
            is_m = {k: None for k in ("total_return", "sharpe")}
        try:
            res_oos = run_engine(symbols, strategy, params, test_s, test_e, initial_cash,
                                 asset_types, multipliers, interval)
            oos_m = _all_metrics(res_oos, initial_cash)
        except Exception:
            oos_m = {k: None for k in ("total_return", "sharpe")}

        is_ret = is_m.get("total_return")
        oos_ret = oos_m.get("total_return")
        is_sh = is_m.get("sharpe")
        oos_sh = oos_m.get("sharpe")
        deg_ret = (oos_ret - is_ret) if (is_ret is not None and oos_ret is not None) else None
        deg_sh = (oos_sh - is_sh) if (is_sh is not None and oos_sh is not None) else None

        records.append({
            "train_period": {"start": train_s, "end": train_e},
            "test_period": {"start": test_s, "end": test_e},
            "is_metrics": is_m,
            "oos_metrics": oos_m,
            "degradation_total_return": round(deg_ret, 6) if deg_ret is not None else None,
            "degradation_sharpe": round(deg_sh, 6) if deg_sh is not None else None,
        })
        if is_ret is not None:
            is_returns.append(is_ret)
        if oos_ret is not None:
            oos_returns.append(oos_ret)
            if oos_ret > 0:
                oos_positive += 1
            if is_ret is not None and oos_ret >= is_ret:
                oos_beats_is += 1
        if is_sh is not None:
            is_sharpes.append(is_sh)
        if oos_sh is not None:
            oos_sharpes.append(oos_sh)

    n = len(oos_returns)
    summary = {
        "n_oos_folds": n,
        "mean_is_return": round(sum(is_returns) / len(is_returns), 6) if is_returns else None,
        "mean_oos_return": round(sum(oos_returns) / len(oos_returns), 6) if oos_returns else None,
        "mean_is_sharpe": round(sum(is_sharpes) / len(is_sharpes), 4) if is_sharpes else None,
        "mean_oos_sharpe": round(sum(oos_sharpes) / len(oos_sharpes), 4) if oos_sharpes else None,
        "oos_positive_rate": round(oos_positive / n, 4) if n else None,
        "oos_beats_is_rate": round(oos_beats_is / n, 4) if n else None,
    }

    return {
        "strategy": strategy,
        "n_folds": n_folds,
        "folds": records,
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# 3. 自定义基准构建
# --------------------------------------------------------------------------- #
def build_benchmark_values(
    benchmark_def: Dict[str, Any],
    strategy_dates: Sequence[str],
    initial_cash: float,
    interval: str = "daily",
) -> List[float]:
    """构建与策略净值曲线（strategy_dates）对齐的基准净值序列。

    ``benchmark_def`` 二选一：
    - ``values``：显式序列，长度须等于 len(strategy_dates)
    - ``symbols``：标的列表 + ``weights``（可选，默认等权）；按加权买入持有构建，
      非交易日沿用上一已知收盘价（向前填充），再按 initial_cash 缩放。

    返回对齐到 strategy_dates 的基准总资产序列。
    """
    if not strategy_dates:
        raise ValueError("策略净值曲线为空，无法构建基准")

    explicit = benchmark_def.get("values")
    if explicit is not None:
        vals = [float(v) for v in explicit]
        if len(vals) != len(strategy_dates):
            raise ValueError(
                f"基准显式序列长度 {len(vals)} 与策略净值曲线长度 {len(strategy_dates)} 不一致"
            )
        return vals

    syms = benchmark_def.get("symbols") or []
    if not syms:
        raise ValueError("基准定义需提供 symbols 或 values")
    weights = benchmark_def.get("weights") or [1.0] * len(syms)
    if len(weights) != len(syms):
        raise ValueError("基准 weights 长度需与 symbols 一致")
    total_w = sum(weights)
    if total_w <= 0:
        raise ValueError("基准 weights 之和需为正")
    w_norm = [w / total_w for w in weights]

    per_symbol: Dict[str, List[Optional[float]]] = {}
    for sym in syms:
        try:
            bars = market_service.bars(sym, strategy_dates[0], strategy_dates[-1], interval=interval)
        except Exception as exc:
            raise RuntimeError(f"基准行情获取失败: {sym}") from exc
        close_by_date = {b.date: float(b.close) for b in bars}
        last: Optional[float] = None
        series: List[Optional[float]] = []
        for d in strategy_dates:
            if d in close_by_date:
                last = close_by_date[d]
            series.append(last)
        per_symbol[sym] = series

    out: List[float] = []
    for i in range(len(strategy_dates)):
        s = 0.0
        ok = True
        for j, sym in enumerate(syms):
            v = per_symbol[sym][i]
            if v is None:
                ok = False
                break
            s += w_norm[j] * v
        if ok:
            out.append(s)
        else:
            out.append(out[-1] if out else 1.0)

    base = out[0] or 1.0
    return [initial_cash * (o / base) for o in out]
