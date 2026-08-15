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
from ..backtest.engine import BacktestEngine, BacktestResult, EquityPoint
from ..backtest.metrics import PerformanceMetrics
from ..backtest.strategies import STRATEGY_REGISTRY
from ..factors import research as factor_research

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


# --------------------------------------------------------------------------- #
# 4. 因子 IC 衰减 / 稳定性分析（V17）
# --------------------------------------------------------------------------- #
def factor_decay(
    symbols: Sequence[str],
    start: str = "2000-01-01",
    end: str = "2100-01-01",
    window: int = 10,
    forward: int = 1,
    roll_window: int = 10,
) -> Dict[str, Any]:
    """因子 IC 随时间的衰减 / 稳定性分析。

    对每个因子复用 ``ic_analysis`` 得到逐期 IC 序列，再做：
    - 滚动均值（roll_window 期）序列，观察 IC 随时间的趋势
    - 线性趋势斜率（OLS）与其 R²，斜率为负即衰减
    - 前半段 vs 后半段均值 IC（decay = 后 - 前）
    - 整体 mean_ic / std_ic / ir / ic_positive_ratio（来自 ic_analysis）

    返回 { factors:[...], roll_window, forward_days, symbols }
    """
    ic = factor_research.ic_analysis(
        symbols=list(symbols) if symbols else None, start=start, end=end, window=window, forward=forward
    )
    results = ic["results"]
    factors = ic["factors"]

    out = []
    for f in factors:
        r = results.get(f) or {}
        series = list(r.get("ic_series") or [])
        n = len(series)

        roll: List[float] = []
        for i in range(n):
            s = max(0, i - roll_window + 1)
            seg = series[s:i + 1]
            roll.append(round(sum(seg) / len(seg), 4))

        if n >= 2:
            xs = list(range(n))
            mx = sum(xs) / n
            my = sum(series) / n
            den = sum((x - mx) ** 2 for x in xs)
            num = sum((x - mx) * (y - my) for x, y in zip(xs, series))
            slope = num / den if den > 0 else 0.0
            ss_tot = sum((y - my) ** 2 for y in series)
            fit = [my + slope * (x - mx) for x in xs]
            ss_res = sum((y - f0) ** 2 for y, f0 in zip(series, fit))
            r2 = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        else:
            slope = 0.0
            r2 = 0.0

        half = n // 2
        fh = sum(series[:half]) / len(series[:half]) if half > 0 else None
        sh = sum(series[half:]) / len(series[half:]) if (n - half) > 0 else None
        decay = (sh - fh) if (fh is not None and sh is not None) else None

        out.append({
            "factor": f,
            "mean_ic": r.get("mean_ic"),
            "std_ic": r.get("std_ic"),
            "ir": r.get("ir"),
            "ic_positive_ratio": r.get("ic_positive_ratio"),
            "observations": r.get("observations"),
            "ic_series": series,
            "roll_means": roll,
            "trend_slope": round(slope, 5),
            "trend_r2": round(r2, 4),
            "first_half_mean_ic": round(fh, 4) if fh is not None else None,
            "second_half_mean_ic": round(sh, 4) if sh is not None else None,
            "decay": round(decay, 4) if decay is not None else None,
        })

    return {
        "factors": out,
        "roll_window": roll_window,
        "forward_days": forward,
        "symbols": ic["symbols"],
    }


# --------------------------------------------------------------------------- #
# 5. 参数最优区间稳健性（grid × walk-forward 联动，V17）
# --------------------------------------------------------------------------- #
def parameter_robustness(
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
    n_folds: int = 5,
    metric: str = "total_return",
) -> Dict[str, Any]:
    """参数最优区间稳健性：grid × walk-forward 联动。

    逐折（扩张窗口）在训练区间上重算敏感性网格，得到该折的「样本内最优参数」，
    并在测试（样本外）区间上评估该最优参数的表现。最后汇总：
    - 各折最优参数及其样本外 metric
    - 最优参数组合的出现频次（稳定度）：consensus = 出现最多的 (pa, pb)
    - 全局单点最优参数（全区间）在每折测试区间的样本外 metric
    - 一致性：consensus 是否与全局最优一致 / 样本外胜率
    """
    keys = list(grid.keys())
    if len(keys) != 2:
        raise ValueError("parameter_robustness 的 grid 必须恰好包含两个参数")
    pa, pb = keys

    try:
        bars = market_service.bars(symbols[0], start, end, interval=interval)
    except Exception as exc:
        raise RuntimeError(f"行情获取失败: {symbols[0]}") from exc
    if not bars:
        raise ValueError(f"标的 {symbols[0]} 在 {start}~{end} 无行情数据")
    dates = [b.date for b in bars]
    folds = split_walkforward(dates, n_folds)
    if not folds:
        raise ValueError("样本区间过短，无法做稳健性分析（至少需要 4 个交易日且 n_folds>=2）")

    global_grid = sensitivity_grid(
        strategy, params, grid, symbols, start, end,
        initial_cash, asset_types, multipliers, interval, metric,
    )
    global_best = global_grid["best"]

    fold_rows: List[Dict[str, Any]] = []
    best_counts: Dict[Tuple[Any, Any], int] = {}
    oos_of_fold_best: List[float] = []
    oos_of_global_best: List[float] = []

    for train_s, train_e, test_s, test_e in folds:
        g = sensitivity_grid(
            strategy, params, grid, symbols, train_s, train_e,
            initial_cash, asset_types, multipliers, interval, metric,
        )
        fb = g["best"]
        key = (fb.get("param_a"), fb.get("param_b"))
        if fb.get("value") is not None and key[0] is not None and key[1] is not None:
            best_counts[key] = best_counts.get(key, 0) + 1

        p_fb = dict(params)
        p_fb[pa] = fb.get("param_a")
        p_fb[pb] = fb.get("param_b")
        oos_fb = None
        try:
            res = run_engine(symbols, strategy, p_fb, test_s, test_e, initial_cash,
                             asset_types, multipliers, interval)
            oos_fb = metrics_of(res, initial_cash, metric)
        except Exception:
            oos_fb = None
        if isinstance(oos_fb, (int, float)):
            oos_of_fold_best.append(oos_fb)

        p_gb = dict(params)
        p_gb[pa] = global_best.get("param_a")
        p_gb[pb] = global_best.get("param_b")
        oos_gb = None
        try:
            res = run_engine(symbols, strategy, p_gb, test_s, test_e, initial_cash,
                             asset_types, multipliers, interval)
            oos_gb = metrics_of(res, initial_cash, metric)
        except Exception:
            oos_gb = None
        if isinstance(oos_gb, (int, float)):
            oos_of_global_best.append(oos_gb)

        fold_rows.append({
            "test_period": {"start": test_s, "end": test_e},
            "best_param_a": fb.get("param_a"),
            "best_param_b": fb.get("param_b"),
            "best_value_in_sample": fb.get("value"),
            "oos_metric": round(oos_fb, 6) if isinstance(oos_fb, (int, float)) else None,
        })

    consensus = None
    if best_counts:
        consensus_key = max(best_counts, key=lambda k: best_counts[k])
        consensus = {
            "param_a": consensus_key[0],
            "param_b": consensus_key[1],
            "folds_chosen": best_counts[consensus_key],
            "total_oos_folds": len(folds),
            "stability_ratio": round(best_counts[consensus_key] / len(folds), 4),
        }

    consistent = (
        consensus is not None
        and consensus["param_a"] == global_best.get("param_a")
        and consensus["param_b"] == global_best.get("param_b")
    )

    summary = {
        "n_oos_folds": len(folds),
        "consensus_optimal": consensus,
        "global_optimal": {k: global_best.get(k) for k in ("param_a", "param_b", "value")},
        "consistent_with_global": bool(consistent),
        "mean_oos_fold_best": round(sum(oos_of_fold_best) / len(oos_of_fold_best), 6) if oos_of_fold_best else None,
        "mean_oos_global_best": round(sum(oos_of_global_best) / len(oos_of_global_best), 6) if oos_of_global_best else None,
        "oos_fold_best_positive_rate": round(sum(1 for x in oos_of_fold_best if x > 0) / len(oos_of_fold_best), 4) if oos_of_fold_best else None,
        "param_frequency": [
            {"param_a": k[0], "param_b": k[1], "count": v}
            for k, v in sorted(best_counts.items(), key=lambda kv: -kv[1])
        ],
    }

    return {
        "strategy": strategy,
        "metric": metric,
        "param_a": pa,
        "param_b": pb,
        "param_a_values": list(grid[pa]),
        "param_b_values": list(grid[pb]),
        "folds": fold_rows,
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# 6. 多基准加权对比（V17）
# --------------------------------------------------------------------------- #
def weighted_benchmark_compare(
    run_equity_curve: List[Dict[str, Any]],
    benchmarks: List[Dict[str, Any]],
    initial_cash: float,
    interval: str = "daily",
) -> Dict[str, Any]:
    """多基准加权对比：把多个基准按权重组合成复合基准，与策略曲线对比。

    ``benchmarks`` 每项：{ name, weight, symbols/values, weights(篮子内权重，可选) }
    复合基准曲线 = initial * Σ_i w_i * (curve_i / curve_i[0])（各基准先 rebased 到
    initial 再加权）。

    返回 composite 的相对绩效（beta/alpha/TE/IR/超额/基准收益）+ 复合曲线 + 各基准曲线。
    """
    if not run_equity_curve:
        raise ValueError("策略净值曲线为空，无法对比")
    dates = [p.get("date") for p in run_equity_curve]
    eq_points = [
        EquityPoint(
            date=p.get("date"),
            cash=p.get("cash", 0.0),
            market_value=p.get("market_value", 0.0),
            total_value=p.get("total_value", 0.0),
            daily_return=p.get("daily_return", 0.0) or 0.0,
        )
        for p in run_equity_curve
    ]

    if not benchmarks:
        raise ValueError("至少需要一个基准")
    weights = [float(b.get("weight", 1.0)) for b in benchmarks]
    total_w = sum(weights)
    if total_w <= 0:
        raise ValueError("基准权重之和需为正")
    w_norm = [w / total_w for w in weights]

    per_bench_curves: List[List[float]] = []
    for b in benchmarks:
        bd = dict(b)
        bd.pop("weight", None)  # build_benchmark_values 不应收到顶层 weight
        bv = build_benchmark_values(bd, dates, initial_cash, interval)
        per_bench_curves.append(bv)

    composite: List[float] = []
    for i in range(len(dates)):
        s = 0.0
        for j, bv in enumerate(per_bench_curves):
            base = bv[0] or 1.0
            s += w_norm[j] * (bv[i] / base)
        composite.append(initial_cash * s)

    m = PerformanceMetrics(eq_points, initial_cash, [], benchmark_values=composite)
    rel = dict(m._attribution.get("benchmark", {}))

    return {
        "composite_relative": rel,
        "composite_curve": [{"date": d, "value": round(v, 2)} for d, v in zip(dates, composite)],
        "benchmarks": [
            {
                "name": b.get("name", f"基准{j + 1}"),
                "weight": round(w_norm[j], 4),
                "curve": [{"date": d, "value": round(v, 2)} for d, v in zip(dates, per_bench_curves[j])],
            }
            for j, b in enumerate(benchmarks)
        ],
    }
