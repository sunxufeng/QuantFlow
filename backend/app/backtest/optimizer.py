"""回测参数优化器（V2.1）。

在给定参数网格上做笛卡尔积遍历，对每组参数运行回测并计算绩效，
按目标指标（夏普 / 收益 / 回撤等）排序返回 Top-N，辅助策略参数寻优。

设计要点：
- 纯离线：复用现有 BacktestEngine + PerformanceMetrics，无需券商凭证
- 网格爆炸保护：combo 数超过 ``max_combos`` 时拒绝（422）
- 单组失败隔离：某组参数出错仅记为 failed，不影响整体结果
"""

from __future__ import annotations

import itertools
import logging
import random
from typing import Any, Dict, List, Optional

from .engine import BacktestEngine, BacktestError
from .metrics import PerformanceMetrics
from .strategies import STRATEGY_REGISTRY
from ..market.models import Bar, Instrument
from ..market.service import market_service

logger = logging.getLogger("quantflow.backtest.optimizer")

# 允许作为排序目标的指标（均为「越大越好」：max_drawdown 取负值更小=更差）
OBJECTIVE_METRICS = ("sharpe", "total_return", "annual_return", "max_drawdown", "win_rate")

# 默认网格规模上限（防止笛卡尔积爆炸）
DEFAULT_MAX_COMBOS = 200


class OptimizeConfigError(Exception):
    """参数优化配置错误（网格非法 / 超出上限）。"""


def _load_market_data(
    symbols: List[str], start: str, end: str, interval: str
) -> Dict[str, List[Bar]]:
    data: Dict[str, List[Bar]] = {}
    for symbol in symbols:
        try:
            bars = market_service.bars(symbol, start, end, interval=interval)
        except Exception as exc:  # 统一包装为 BacktestError 让调用层转 503
            raise BacktestError(f"行情获取失败: {symbol} ({exc})") from exc
        if not bars:
            raise BacktestError(f"标的 {symbol} 在 {start}~{end} 无行情数据")
        data[symbol] = bars
    return data


def _build_instruments(
    symbols: List[str],
    asset_types: Dict[str, str],
    multipliers: Dict[str, float],
) -> Dict[str, Instrument]:
    instruments: Dict[str, Instrument] = {}
    for symbol in symbols:
        asset_type = asset_types.get(symbol, "stock")
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
            contract_multiplier=float(multipliers.get(symbol, 10.0))
            if asset_type == "future"
            else 1.0,
        )
    return instruments


def optimize(
    *,
    strategy: str,
    fixed_params: Optional[Dict[str, Any]] = None,
    grid: Optional[Dict[str, List[Any]]] = None,
    distributions: Optional[Dict[str, Dict[str, Any]]] = None,
    method: str = "grid",
    n_samples: int = 30,
    seed: Optional[int] = None,
    symbols: List[str],
    start: str,
    end: str,
    initial_cash: float = 1_000_000.0,
    asset_types: Optional[Dict[str, str]] = None,
    multipliers: Optional[Dict[str, float]] = None,
    interval: str = "daily",
    objective: str = "sharpe",
    top_n: int = 10,
    max_combos: int = DEFAULT_MAX_COMBOS,
) -> Dict[str, Any]:
    """对策略参数做网格搜索并返回按目标排序的 Top-N 结果。

    返回结构：:
        {
          "strategy": str,
          "objective": str,
          "objective_direction": "higher",
          "symbols": [...],
          "start": str, "end": str,
          "total_combos": int,
          "completed": int,
          "failed": int,
          "top": [
            {"rank": 1, "params": {...}, "metrics": {...}},
            ...
          ],
          "failures": [{"params": {...}, "error": str}, ...]
        }
    """
    if strategy not in STRATEGY_REGISTRY:
        raise OptimizeConfigError(
            f"未知策略 {strategy!r}，可选: {sorted(STRATEGY_REGISTRY)}"
        )
    if objective not in OBJECTIVE_METRICS:
        raise OptimizeConfigError(
            f"不支持的优化目标 {objective!r}，可选: {OBJECTIVE_METRICS}"
        )
    if method not in ("grid", "random"):
        raise OptimizeConfigError(f"不支持的搜索方式 {method!r}，可选: grid / random")

    fixed_params = fixed_params or {}
    grid = grid or {}
    distributions = distributions or {}
    asset_types = asset_types or {}
    multipliers = multipliers or {}

    # 展开参数组合：grid=笛卡尔积；random=按分布随机抽样（去重）
    if method == "random":
        combos = _sample_random_combos(
            distributions, n_samples, seed, max_combos
        )
    else:
        grid_items = list(grid.items())
        if grid_items:
            keys = [k for k, _ in grid_items]
            value_lists = [v for _, v in grid_items]
            combos = [dict(zip(keys, vals)) for vals in itertools.product(*value_lists)]
        else:
            # 无网格：仅跑一组固定参数（等价于单次回测 + 排序脚手架）
            combos = [{}]

    total_combos = len(combos)
    if total_combos > max_combos:
        raise OptimizeConfigError(
            f"参数组合过多（{total_combos} > 上限 {max_combos}）。"
            f"请收窄网格或提高 max_combos。"
        )

    # 行情只拉一次（所有组合共享同一标的区间）
    data = _load_market_data(symbols, start, end, interval)
    instruments = _build_instruments(symbols, asset_types, multipliers)
    factory = STRATEGY_REGISTRY[strategy]

    results: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    for combo in combos:
        merged = {**fixed_params, **combo}
        try:
            strategy_obj = factory(merged)
            engine = BacktestEngine(
                strategy_obj,
                data,
                initial_cash=initial_cash,
                instruments=instruments,
            )
            result = engine.run()
            metrics = PerformanceMetrics(
                result.equity_curve, result.engine.initial_cash, result.trades
            ).to_dict()
            # 仅保留排序与展示关心的字段，控制体积
            compact = {
                "total_return": metrics.get("total_return"),
                "annual_return": metrics.get("annual_return"),
                "sharpe": metrics.get("sharpe"),
                "max_drawdown": metrics.get("max_drawdown"),
                "win_rate": metrics.get("win_rate"),
                "turnover": metrics.get("turnover"),
                "days": metrics.get("days"),
                "final_value": metrics.get("final_value"),
            }
            results.append({"params": merged, "metrics": compact})
        except Exception as exc:  # 单组失败隔离
            logger.warning("optimize combo %s failed: %s", merged, exc)
            failures.append({"params": merged, "error": str(exc)})

    # 排序：所有目标均为「越大越好」
    def _score(item: Dict[str, Any]) -> float:
        v = item["metrics"].get(objective)
        return float(v) if v is not None else float("-inf")

    results.sort(key=_score, reverse=True)
    top = [
        {"rank": i + 1, "params": r["params"], "metrics": r["metrics"]}
        for i, r in enumerate(results[: max(top_n, 1)])
    ]

    return {
        "strategy": strategy,
        "method": method,
        "objective": objective,
        "objective_direction": "higher",
        "symbols": symbols,
        "start": start,
        "end": end,
        "total_combos": total_combos,
        "completed": len(results),
        "failed": len(failures),
        "top": top,
        "failures": failures,
    }


def _sample_random_combos(
    distributions: Dict[str, Dict[str, Any]],
    n_samples: int,
    seed: Optional[int],
    max_combos: int,
) -> List[Dict[str, Any]]:
    """按参数分布随机抽样 ``n_samples`` 组（去重），用于随机搜索。

    ``distributions`` 每个参数支持三种分布::

        {"type": "int", "low": 2, "high": 20}          # 整数均匀
        {"type": "float", "low": 0.1, "high": 0.5}      # 浮点均匀
        {"type": "choice", "values": [3, 5, 8, 13]}     # 离散候选

    返回抽样的参数组合列表（长度 <= n_samples）。
    """
    if not distributions:
        raise OptimizeConfigError("随机搜索需提供 distributions 参数分布定义")
    if n_samples < 1:
        raise OptimizeConfigError("n_samples 必须 >= 1")
    if n_samples > max_combos:
        raise OptimizeConfigError(
            f"随机样本数过多（{n_samples} > 上限 {max_combos}），请减小 n_samples 或提高 max_combos"
        )

    rng = random.Random(seed)
    samples: List[Dict[str, Any]] = []
    seen: set = set()
    attempts = 0
    max_attempts = max(n_samples * 50, 2000)
    while len(samples) < n_samples and attempts < max_attempts:
        attempts += 1
        combo: Dict[str, Any] = {}
        for name, spec in distributions.items():
            stype = spec.get("type")
            if stype == "choice":
                values = spec.get("values") or []
                if not values:
                    raise OptimizeConfigError(f"分布 {name!r} 的 choice 需提供 values")
                combo[name] = rng.choice(values)
            elif stype in ("int", "float"):
                low = spec.get("low")
                high = spec.get("high")
                if low is None or high is None:
                    raise OptimizeConfigError(f"分布 {name!r} 需 low/high")
                if high < low:
                    raise OptimizeConfigError(f"分布 {name!r} 的 high 不得小于 low")
                val = low + (high - low) * rng.random()
                combo[name] = int(round(val)) if stype == "int" else float(val)
            else:
                raise OptimizeConfigError(
                    f"分布 {name!r} 未知 type={stype!r}（可选 int/float/choice）"
                )
        key = tuple(sorted(combo.items()))
        if key not in seen:
            seen.add(key)
            samples.append(combo)
    return samples
