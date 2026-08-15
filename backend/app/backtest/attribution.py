"""绩效归因分析（V27 增强）。

提供三类归因方法，纯标准库实现，便于单测与前端直连：

1. Brinson 归因（按板块 / 资产类别）
   - 将组合相对基准的超额收益拆解为配置效应、选股效应、交互效应。
   - 配置效应  = (w_p - w_b) * r_b
   - 选股效应  = w_b * (r_p - r_b)
   - 交互效应  = (w_p - w_b) * (r_p - r_b)
   - 三者之和 = 组合收益 - 基准收益（即主动收益）。

2. 因子归因
   - 组合收益 = Σ(因子暴露_i * 因子收益_i) + 特异性收益(α)。
   - 输出每个因子的贡献及可解释比例。

3. 持仓贡献归因
   - 单笔持仓贡献 = 权重_i * 收益_i，按贡献排序并累计。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def _round(x: Optional[float], n: int = 6) -> Optional[float]:
    return None if x is None else round(x, n)


def brinson_attribution(groups: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Brinson 多板块归因。

    groups 每项需包含：name, portfolio_weight, benchmark_weight,
    portfolio_return, benchmark_return。
    """
    if not groups:
        raise ValueError("Brinson 归因需要至少一个板块分组")

    out_groups: List[Dict[str, Any]] = []
    tot_alloc = tot_sel = tot_inter = 0.0
    rp = rb = 0.0
    for g in groups:
        name = g.get("name", "")
        wp = float(g["portfolio_weight"])
        wb = float(g["benchmark_weight"])
        rp_g = float(g["portfolio_return"])
        rb_g = float(g["benchmark_return"])
        alloc = (wp - wb) * rb_g
        sel = wb * (rp_g - rb_g)
        inter = (wp - wb) * (rp_g - rb_g)
        tot_alloc += alloc
        tot_sel += sel
        tot_inter += inter
        rp += wp * rp_g
        rb += wb * rb_g
        out_groups.append({
            "name": name,
            "portfolio_weight": _round(wp),
            "benchmark_weight": _round(wb),
            "portfolio_return": _round(rp_g),
            "benchmark_return": _round(rb_g),
            "allocation": _round(alloc),
            "selection": _round(sel),
            "interaction": _round(inter),
            "total": _round(alloc + sel + inter),
        })

    active = rp - rb
    return {
        "method": "brinson",
        "portfolio_return": _round(rp),
        "benchmark_return": _round(rb),
        "active_return": _round(active),
        "total_allocation": _round(tot_alloc),
        "total_selection": _round(tot_sel),
        "total_interaction": _round(tot_inter),
        "checksum_ok": abs((tot_alloc + tot_sel + tot_inter) - active) < 1e-6,
        "groups": out_groups,
    }


def factor_attribution(factors: List[Dict[str, Any]], specific_return: float = 0.0) -> Dict[str, Any]:
    """因子归因。

    factors 每项需包含：name, exposure, factor_return。
    specific_return 为无法被因子解释的特异性收益（α）。
    """
    if not factors:
        raise ValueError("因子归因需要至少一个因子")

    out_factors: List[Dict[str, Any]] = []
    explained = 0.0
    for f in factors:
        name = f.get("name", "")
        beta = float(f["exposure"])
        fr = float(f["factor_return"])
        contrib = beta * fr
        explained += contrib
        out_factors.append({
            "name": name,
            "exposure": _round(beta),
            "factor_return": _round(fr),
            "contribution": _round(contrib),
        })
    total = explained + specific_return
    r_squared = (explained / total) if total not in (0.0, None) and abs(total) > 1e-12 else None
    return {
        "method": "factor",
        "explained_return": _round(explained),
        "specific_return": _round(specific_return),
        "total_return": _round(total),
        "r_squared": _round(r_squared, 4) if r_squared is not None else None,
        "factors": out_factors,
    }


def holdings_attribution(holdings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """持仓贡献归因。

    holdings 每项需包含：symbol, weight，以及以下二者之一：
    - contribution：直接给出的收益贡献；
    - return_ / return：由权重 * 收益推导。
    """
    if not holdings:
        raise ValueError("持仓归因需要至少一条持仓")

    out: List[Dict[str, Any]] = []
    total = 0.0
    for h in holdings:
        symbol = h.get("symbol", "")
        w = float(h["weight"])
        if h.get("contribution") is not None:
            contrib = float(h["contribution"])
        else:
            r = float(h.get("return_") if h.get("return_") is not None else h.get("return", 0.0))
            contrib = w * r
        total += contrib
        out.append({
            "symbol": symbol,
            "weight": _round(w),
            "contribution": _round(contrib),
        })
    out.sort(key=lambda x: (x["contribution"] or 0), reverse=True)
    cum = 0.0
    for item in out:
        cum += item["contribution"] or 0.0
        item["cumulative"] = _round(cum)
        item["cumulative_pct"] = _round(cum / total, 4) if total not in (0.0, None) and abs(total) > 1e-12 else None
    return {
        "method": "holdings",
        "total_return": _round(total),
        "holdings": out,
    }


def performance_attribution(
    method: str,
    groups: Optional[List[Dict[str, Any]]] = None,
    factors: Optional[List[Dict[str, Any]]] = None,
    holdings: Optional[List[Dict[str, Any]]] = None,
    specific_return: float = 0.0,
    name: Optional[str] = None,
) -> Dict[str, Any]:
    """统一入口：按 method 分派到对应归因实现。"""
    method = (method or "").lower()
    if method == "brinson":
        if not groups:
            raise ValueError("Brinson 归因缺少 groups 参数")
        result = brinson_attribution(groups)
    elif method == "factor":
        if not factors:
            raise ValueError("因子归因缺少 factors 参数")
        result = factor_attribution(factors, specific_return=specific_return)
    elif method == "holdings":
        if not holdings:
            raise ValueError("持仓归因缺少 holdings 参数")
        result = holdings_attribution(holdings)
    else:
        raise ValueError(f"不支持的归因方法：{method!r}（可选 brinson/factor/holdings）")

    if name:
        result["name"] = name
    return result
