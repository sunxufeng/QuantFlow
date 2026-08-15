"""执行成本与最优执行分析（V62–V66）。

纯函数实现，供 API / 单测复用。与 execution/gateway.py（券商连接）解耦，
专注于交易成本建模、市场冲击、TWAP/VWAP 切片与滑点归因研究。
"""
from __future__ import annotations

from typing import List, Dict, Any, Optional

import numpy as np


def transaction_cost(
    trades: List[Dict[str, Any]],
    commission_rate: float = 0.0003,
    min_commission: float = 5.0,
    fixed_per_trade: float = 0.0,
    stamp_tax: float = 0.001,
    regulator_fee: float = 0.00002,
) -> Dict[str, Any]:
    """逐笔交易成本模型（A 股风格）。

    每笔：佣金 = max(成交额×rate, 最低佣金) + 固定费；
    卖出另计印花税；双边计规费。返回每笔明细、总额、成本率与组成占比。
    """
    if not trades:
        raise ValueError("trades 不能为空")
    details = []
    total_notional = 0.0
    total_cost = 0.0
    comp = {"commission": 0.0, "stamp": 0.0, "regulator": 0.0, "fixed": 0.0}
    for t in trades:
        price = float(t["price"])
        shares = float(t["shares"])
        side = str(t.get("side", "buy")).lower()
        if price <= 0 or shares <= 0:
            raise ValueError("price/shares 须为正")
        notional = price * shares
        comm = max(notional * commission_rate, min_commission) + fixed_per_trade
        stamp = notional * stamp_tax if side == "sell" else 0.0
        reg = notional * regulator_fee
        cost = comm + stamp + reg
        details.append({
            "side": side,
            "price": price,
            "shares": shares,
            "notional": round(notional, 2),
            "commission": round(comm, 2),
            "stamp_tax": round(stamp, 2),
            "regulator_fee": round(reg, 2),
            "cost": round(cost, 2),
            "cost_pct": round(cost / notional, 6),
        })
        total_notional += notional
        total_cost += cost
        comp["commission"] += comm
        comp["stamp"] += stamp
        comp["regulator"] += reg
        comp["fixed"] += fixed_per_trade
    total_notional = total_notional or 1e-12
    comp_pct = {k: round(v / total_cost, 4) if total_cost > 0 else 0.0 for k, v in comp.items()}
    return {
        "n_trades": len(trades),
        "total_notional": round(total_notional, 2),
        "total_cost": round(total_cost, 2),
        "total_cost_pct": round(total_cost / total_notional, 6),
        "avg_cost_pct": round(total_cost / total_notional, 6),
        "components": {k: round(v, 2) for k, v in comp.items()},
        "components_pct": comp_pct,
        "details": details,
    }


def market_impact(
    shares: float,
    price: float,
    adv: float,
    volatility: float,
    participation: float = 0.1,
    eta: float = 0.5,
    gamma: float = 0.3,
) -> Dict[str, Any]:
    """平方根市场冲击模型（Almgren–Chriss 风格）。

    临时冲击（执行时滑点）：eta·σ·√(换手率)；永久冲击（信息泄漏）：gamma·换手率。
    换手率 = shares/ADV。返回冲击占比、冲击成本、价差代理成本、清仓天数。
    """
    if shares <= 0 or price <= 0 or adv <= 0 or volatility <= 0:
        raise ValueError("shares/price/adv/volatility 须为正")
    if not (0 < participation <= 1):
        raise ValueError("participation 须 ∈ (0,1]")
    turnover = shares / adv
    temp_impact = eta * volatility * np.sqrt(turnover)
    perm_impact = gamma * turnover
    notional = shares * price
    spread_proxy = 0.0005 * notional  # 半价差代理
    impact_cost = notional * (temp_impact + perm_impact)
    total_cost = impact_cost + spread_proxy
    liquidation_days = shares / (participation * adv)
    return {
        "turnover": round(float(turnover), 6),
        "temporary_impact_pct": round(float(temp_impact), 6),
        "permanent_impact_pct": round(float(perm_impact), 6),
        "total_impact_pct": round(float(temp_impact + perm_impact), 6),
        "impact_cost": round(float(impact_cost), 2),
        "spread_proxy_cost": round(float(spread_proxy), 2),
        "total_cost": round(float(total_cost), 2),
        "notional": round(float(notional), 2),
        "participation": participation,
        "liquidation_days": round(float(liquidation_days), 2),
    }


def twap_schedule(
    parent_qty: float,
    n_slices: int,
    interval_seconds: float = 60.0,
    start_seconds: float = 0.0,
) -> Dict[str, Any]:
    """TWAP 切片：父单在 n_slices 段内均匀切分。"""
    if parent_qty <= 0 or n_slices <= 0:
        raise ValueError("parent_qty/n_slices 须为正")
    qty = parent_qty / n_slices
    children = []
    for i in range(n_slices):
        s = start_seconds + i * interval_seconds
        e = s + interval_seconds
        children.append({
            "slice": i + 1,
            "qty": round(qty, 4),
            "start_sec": round(s, 2),
            "end_sec": round(e, 2),
            "weight": round(1.0 / n_slices, 6),
        })
    return {
        "parent_qty": parent_qty,
        "n_slices": n_slices,
        "interval_seconds": interval_seconds,
        "total_seconds": interval_seconds * n_slices,
        "avg_slice_qty": round(qty, 4),
        "children": children,
    }


def vwap_schedule(
    parent_qty: float,
    volume_profile: Optional[List[float]] = None,
    n_slices: int = 6,
    interval_seconds: float = 60.0,
    start_seconds: float = 0.0,
) -> Dict[str, Any]:
    """VWAP 切片：按成交量分布（默认 U 型）加权切分父单。"""
    if parent_qty <= 0 or n_slices <= 0:
        raise ValueError("parent_qty/n_slices 须为正")
    if volume_profile is None:
        # 默认 U 型：开盘/收盘重，中间轻
        m = (n_slices - 1) / 2.0
        profile = [1.0 + 1.0 * abs(i - m) / (m + 1e-9) for i in range(n_slices)]
    else:
        if len(volume_profile) != n_slices:
            raise ValueError("volume_profile 长度须等于 n_slices")
        profile = [max(0.0, float(v)) for v in volume_profile]
    total = sum(profile) or 1e-12
    weights = [p / total for p in profile]
    children = []
    for i in range(n_slices):
        s = start_seconds + i * interval_seconds
        e = s + interval_seconds
        children.append({
            "slice": i + 1,
            "qty": round(parent_qty * weights[i], 4),
            "weight": round(weights[i], 6),
            "start_sec": round(s, 2),
            "end_sec": round(e, 2),
        })
    return {
        "parent_qty": parent_qty,
        "n_slices": n_slices,
        "profile": [round(p, 4) for p in profile],
        "weights": [round(w, 6) for w in weights],
        "children": children,
    }


def slippage_attribution(
    arrival_mid: float,
    fill_price: float,
    side: str,
    shares: float,
    fee_bps: float = 0.0,
    vwap_benchmark: Optional[float] = None,
    impact_bps: float = 0.0,
) -> Dict[str, Any]:
    """已实现滑点归因：分解为择时、市场冲击、费用三部分（bps）。

    - 总滑点 = (fill - arrival)/arrival ×1e4，买入为正(劣化)、卖出取反。
    - 择时 = 相对 VWAP 基准的偏离（缺省用 arrival 视为 0）。
    - 冲击 = 估计市场冲击（inputs）。
    - 费用 = fee_bps。
    """
    if arrival_mid <= 0 or fill_price <= 0 or shares <= 0:
        raise ValueError("arrival_mid/fill_price/shares 须为正")
    side = str(side).lower()
    sign = 1.0 if side == "buy" else -1.0
    total_bps = sign * (fill_price - arrival_mid) / arrival_mid * 1e4
    fee_component = fee_bps
    impact_component = impact_bps
    if vwap_benchmark and vwap_benchmark > 0:
        timing_bps = sign * (arrival_mid - vwap_benchmark) / vwap_benchmark * 1e4
    else:
        timing_bps = 0.0
    residual = total_bps - timing_bps - impact_component - fee_component
    return {
        "side": side,
        "arrival_mid": arrival_mid,
        "fill_price": fill_price,
        "vwap_benchmark": vwap_benchmark,
        "total_slippage_bps": round(float(total_bps), 2),
        "timing_bps": round(float(timing_bps), 2),
        "impact_bps": round(float(impact_component), 2),
        "fee_bps": round(float(fee_component), 2),
        "residual_bps": round(float(residual), 2),
        "notional": round(float(shares * arrival_mid), 2),
    }


__all__ = [
    "transaction_cost",
    "market_impact",
    "twap_schedule",
    "vwap_schedule",
    "slippage_attribution",
]
