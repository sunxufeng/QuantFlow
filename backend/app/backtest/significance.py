"""策略评估与显著性（V92–V96）：对策略/因子做统计显著性评估，填补平台空白。

五个纯函数（输入收益/权益曲线/标量即可离线运行、可单测）：
- V92 Deflated Sharpe Ratio：考虑多次检验后的「真实」夏普，给出被运气解释的概率。
- V93 Probabilistic Sharpe Ratio（PSR）：夏普超过目标值的概率。
- V94 策略容量估计：由日均成交额(ADV)、参与率、冲击系数、年化换手估计策略容量。
- V95 状态条件收益统计：把收益序列按市场状态标签拆分，给出各状态均值/波动/夏普。
- V96 策略分散度：多策略权益曲线的相关系数矩阵 + 有效策略数。

数值上保证无 NaN；依赖 scipy（venv 已具备）。
"""

from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence

import numpy as np
from scipy import stats


# ----------------------------- V92 Deflated Sharpe Ratio -----------------------------

def deflated_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    n_trials: int = 1,
) -> Dict:
    """考虑多次检验后的 Deflated Sharpe Ratio。

    采用 Bailey & López de Prado (2014) 框架：夏普标准误用 Lo(2002) 偏度/峰度修正；
    N 次独立检验的期望最大夏普由标准正态极值期望近似。

    返回 { "deflated_sharpe", "expected_max_sr", "p_lucky", "sr_se", "n_trials" }。
    p_lucky：观测夏普完全由运气（≤ 期望最大）解释的概率。
    """
    if n_obs <= 0:
        raise ValueError("n_obs 必须为正数")
    if n_trials < 1:
        raise ValueError("n_trials 至少为 1")
    # Lo(2002) 夏普标准误修正
    var_term = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe ** 2
    se = math.sqrt(max(var_term, 1e-12) / n_obs)
    if n_trials <= 1:
        expected_max = 0.0
    else:
        g = 0.5772156649015329  # Euler–Mascheroni
        lnN = math.log(n_trials)
        expected_max = math.sqrt((1.0 - g) * (2.0 * lnN - math.log(lnN) - math.log(4.0 * math.pi)))
    expected_max_sr = expected_max * se
    deflated = sharpe - expected_max_sr
    z = (expected_max_sr - sharpe) / se  # = -expected_max
    p_lucky = float(stats.norm.cdf(z))
    return {
        "deflated_sharpe": float(deflated),
        "expected_max_sr": float(expected_max_sr),
        "p_lucky": p_lucky,
        "sr_se": float(se),
        "n_trials": int(n_trials),
    }


# ----------------------------- V93 Probabilistic Sharpe Ratio -----------------------------

def probabilistic_sharpe_ratio(
    sharpe: float,
    n_obs: int,
    skew: float = 0.0,
    kurtosis: float = 3.0,
    target_sr: float = 0.0,
) -> Dict:
    """Probabilistic Sharpe Ratio：夏普 ≥ 目标值的概率（Bailey & López de Prado）。

    返回 { "prob", "z", "sr_se" }。prob = Φ(z)。
    """
    if n_obs <= 0:
        raise ValueError("n_obs 必须为正数")
    var_term = 1.0 - skew * sharpe + (kurtosis - 1.0) / 4.0 * sharpe ** 2
    se = math.sqrt(max(var_term, 1e-12) / n_obs)
    z = (sharpe - target_sr) * math.sqrt(n_obs) / math.sqrt(max(var_term, 1e-12))
    prob = float(stats.norm.cdf(z))
    return {"prob": prob, "z": float(z), "sr_se": float(se)}


# ----------------------------- V94 策略容量估计 -----------------------------

def strategy_capacity(
    adv: float,
    participation: float = 0.1,
    impact_coef: float = 0.1,
    annual_turnover: float = 2.0,
    trading_days: int = 252,
) -> Dict:
    """策略容量估计（基于流动性与冲击）。

    核心口径：年化可交易额 = ADV × 参与率 × 交易日；容量 = 年化可交易额 / 年化换手。
    另给出：在给定 AUM 下，按平方根冲击模型的年化冲击成本估计。

    返回 { "daily_tradable", "annual_tradable", "capacity", "impact_cost_at_capacity" }。
    """
    if adv <= 0 or participation <= 0 or annual_turnover <= 0:
        raise ValueError("adv / participation / annual_turnover 必须为正数")
    daily_tradable = float(adv * participation)
    annual_tradable = daily_tradable * trading_days
    capacity = annual_tradable / annual_turnover
    # 在「容量」AUM 下，每交易日交易额 = AUM*年换手/交易日，占可交易额比例 → 平方冲击
    frac = (capacity * annual_turnover / trading_days) / max(daily_tradable, 1e-12)
    impact_cost_at_capacity = float(impact_coef * frac ** 2)
    return {
        "daily_tradable": daily_tradable,
        "annual_tradable": annual_tradable,
        "capacity": capacity,
        "impact_cost_at_capacity": impact_cost_at_capacity,
    }


# ----------------------------- V95 状态条件收益统计 -----------------------------

def regime_conditional_stats(
    returns: Sequence[float],
    regime_labels: Sequence[str],
    regimes: Optional[Sequence[str]] = None,
) -> Dict:
    """把收益序列按状态标签拆分，给出各状态均值/波动/夏普（年化）。

    返回 { "per_regime": { regime: {mean, vol, sharpe, n} }, "regimes" }。
    """
    r = np.asarray(returns, dtype=float)
    lab = list(regime_labels)
    if r.shape[0] != len(lab):
        raise ValueError("returns 与 regime_labels 长度必须一致")
    if r.shape[0] < 2:
        raise ValueError("returns 长度至少为 2")
    regime_set = list(regimes) if regimes is not None else sorted(set(lab))
    per = {}
    for reg in regime_set:
        idx = [i for i, x in enumerate(lab) if x == reg]
        if not idx:
            continue
        sub = r[idx]
        mean = float(np.mean(sub))
        vol = float(np.std(sub, ddof=1)) if len(sub) > 1 else 0.0
        # 年化（假设日频，252 期）
        ann_mean = mean * 252.0
        ann_vol = vol * math.sqrt(252.0)
        sharpe = float(ann_mean / ann_vol) if ann_vol > 0 else 0.0
        per[reg] = {"mean": mean, "vol": vol, "sharpe": sharpe, "n": len(sub)}
    return {"per_regime": per, "regimes": regime_set}


# ----------------------------- V96 策略分散度 -----------------------------

def strategy_diversification(
    equity_curves: Dict[str, Sequence[float]],
) -> Dict:
    """多策略权益曲线 → 相关系数矩阵 + 有效策略数。

    有效策略数（等权）：k / (1 + (k-1)·平均两两相关系数)。
    返回 { "strategies", "correlation_matrix", "avg_correlation", "effective_strategies" }。
    """
    if len(equity_curves) < 2:
        raise ValueError("至少提供 2 条策略权益曲线")
    names = list(equity_curves.keys())
    # 统一长度：截取到最短公共长度
    min_len = min(len(v) for v in equity_curves.values())
    if min_len < 2:
        raise ValueError("每条权益曲线长度至少为 2")
    M = np.array([np.asarray(equity_curves[n], dtype=float)[:min_len] for n in names])
    # 用日收益计算相关
    rets = np.diff(M, axis=1)
    corr = np.corrcoef(rets)
    k = len(names)
    # 平均两两相关系数（去对角）
    off = []
    for i in range(k):
        for j in range(i + 1, k):
            off.append(float(corr[i, j]))
    avg_corr = float(np.mean(off)) if off else 0.0
    denom = 1.0 + (k - 1) * avg_corr
    # effective 不超过实际策略数 k（ρ 为负时公式会 > k，此处封顶以保持语义合理）
    effective = float(k) if denom <= 1e-9 else min(float(k), k / denom)
    return {
        "strategies": names,
        "correlation_matrix": corr.tolist(),
        "avg_correlation": avg_corr,
        "effective_strategies": float(effective),
    }
