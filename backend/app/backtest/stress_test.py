"""压力测试 / 情景分析（V29）。

对一组持仓组合施加**历史危机情景**或**自定义冲击**，计算组合层面的
损益影响（P&L impact），并按严重程度排序，识别最脆弱情景与最拖后腿的持仓。

与 :mod:`app.backtest.montecarlo`（基于历史日收益的经验自助重采样）不同，
本模块是**确定性情景冲击**：每个情景给出「资产类别 → 收益率冲击」的映射，
对组合做一次性线性重估，回答「若 X 危机重现，我的组合会跌多少」。

情景库（``STRESS_SCENARIOS``）为常见的历史极端事件，冲击值为该事件期间
典型资产类别的累计收益（近似，仅用于压力演示，非精确回测）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

# 资产类别 -> 中文标签（用于前端展示）
ASSET_CLASS_LABELS = {
    "equity": "股票",
    "bond": "债券",
    "gold": "黄金",
    "cash": "现金",
    "reit": "房地产(REIT)",
    "em": "新兴市场",
    "commodity": "大宗商品",
    "oil": "原油",
    "tech": "科技股",
    "growth": "成长股",
    "value": "价值股",
}

# 预置历史危机情景：资产类别 -> 该期间累计收益冲击（小数，如 -0.5 = -50%）
STRESS_SCENARIOS: Dict[str, Dict[str, Any]] = {
    "2008全球金融危机": {
        "year": 2008,
        "desc": "雷曼破产引发系统性信用危机，风险资产全面崩塌。",
        "shocks": {
            "equity": -0.50, "bond": 0.05, "gold": 0.05, "cash": 0.0,
            "reit": -0.60, "em": -0.55, "commodity": -0.35, "oil": -0.55,
            "tech": -0.45, "growth": -0.55, "value": -0.45,
        },
    },
    "2020新冠冲击": {
        "year": 2020,
        "desc": "疫情全球扩散，流动性挤兑，油价负值，风险资产急跌后分化。",
        "shocks": {
            "equity": -0.34, "bond": -0.03, "gold": 0.08, "cash": 0.0,
            "reit": -0.40, "em": -0.30, "commodity": -0.25, "oil": -0.60,
            "tech": -0.20, "growth": -0.25, "value": -0.40,
        },
    },
    "2022加息冲击": {
        "year": 2022,
        "desc": "通胀高企、激进加息，股债双杀，长久期成长承压最重。",
        "shocks": {
            "equity": -0.20, "bond": -0.15, "gold": -0.10, "cash": 0.01,
            "reit": -0.25, "em": -0.22, "commodity": 0.10, "oil": 0.05,
            "tech": -0.33, "growth": -0.30, "value": -0.12,
        },
    },
    "2000互联网泡沫破裂": {
        "year": 2000,
        "desc": "科技/互联网估值泡沫破裂，成长与科技领跌，避险资产受益。",
        "shocks": {
            "equity": -0.20, "bond": 0.10, "gold": 0.02, "cash": 0.0,
            "reit": -0.10, "em": -0.25, "commodity": -0.05, "oil": -0.10,
            "tech": -0.45, "growth": -0.40, "value": -0.10,
        },
    },
    "2018波动率飙升": {
        "year": 2018,
        "desc": "VIX 一夜翻倍（波动率危机），低波动策略踩踏，权益急挫。",
        "shocks": {
            "equity": -0.10, "bond": 0.02, "gold": 0.03, "cash": 0.0,
            "reit": -0.12, "em": -0.14, "commodity": -0.05, "oil": -0.08,
            "tech": -0.12, "growth": -0.13, "value": -0.08,
        },
    },
    "2022英国养老金危机": {
        "year": 2022,
        "desc": "英债收益率暴冲，利率衍生品保证金螺旋，长久期资产重挫。",
        "shocks": {
            "equity": -0.08, "bond": -0.20, "gold": -0.05, "cash": 0.0,
            "reit": -0.18, "em": -0.12, "commodity": 0.04, "oil": 0.0,
            "tech": -0.12, "growth": -0.15, "value": -0.06,
        },
    },
}


def list_scenarios() -> List[Dict[str, Any]]:
    """返回预置情景清单（供前端下拉/勾选）。"""
    out = []
    for name, sc in STRESS_SCENARIOS.items():
        out.append({
            "name": name,
            "year": sc["year"],
            "desc": sc["desc"],
            "asset_classes": sorted(sc["shocks"].keys()),
        })
    return out


def _holding_shock(h: Dict[str, Any], scenario_shocks: Dict[str, float],
                   custom: Optional[Dict[str, float]]) -> float:
    """计算单个持仓在该情景下的冲击收益率。

    优先级：自定义按 symbol 覆盖 > 自定义按 asset_class 覆盖 >
    情景按 asset_class 冲击 > 0（未覆盖资产类别视为不受影响）。
    """
    symbol = str(h.get("symbol", ""))
    asset_class = str(h.get("asset_class", "") or "").strip().lower()
    if custom:
        if symbol in custom:
            return float(custom[symbol])
        if asset_class in custom:
            return float(custom[asset_class])
    if asset_class in scenario_shocks:
        return float(scenario_shocks[asset_class])
    return 0.0


def _validate_holdings(holdings: Sequence[Dict[str, Any]], base_value: float) -> None:
    if not holdings:
        raise ValueError("holdings 不能为空")
    total_w = sum(float(h.get("weight", 0.0)) for h in holdings)
    if abs(total_w - 1.0) > 0.01 and abs(total_w) < 1e-9:
        pass  # 允许权重未归一化，下面按总和归一
    if base_value <= 0:
        raise ValueError("base_value 必须为正数")


def run_stress_test(
    holdings: Sequence[Dict[str, Any]],
    scenarios: Optional[List[str]] = None,
    custom_shocks: Optional[Dict[str, float]] = None,
    custom_name: str = "自定义情景",
    base_value: float = 1_000_000.0,
) -> Dict[str, Any]:
    """对持仓组合跑压力测试。

    参数
    ----
    holdings: [{symbol, asset_class, weight, price?}]，weight 为组合权重（0~1，未归一化会自动归一）
    scenarios: 要跑的预置情景名列表；缺省跑全部
    custom_shocks: 自定义冲击 {symbol 或 asset_class: 冲击收益率}
    custom_name: 自定义情景展示名
    base_value: 组合基准市值（默认 100 万）

    返回
    ----
    { base_value, scenarios[], worst, summary }
    """
    _validate_holdings(holdings, base_value)

    total_w = sum(float(h.get("weight", 0.0)) or 0.0 for h in holdings)
    if total_w <= 0:
        raise ValueError("holdings 权重之和必须为正数")
    norm = [float(h.get("weight", 0.0)) / total_w for h in holdings]

    scenario_names = scenarios if scenarios else list(STRESS_SCENARIOS.keys())

    results: List[Dict[str, Any]] = []
    for name in scenario_names:
        sc = STRESS_SCENARIOS.get(name)
        if sc is None:
            # 视作自定义情景：name 作为键，custom_shocks 作为该情景冲击
            shocks = dict(custom_shocks or {})
            desc = "自定义情景"
            year = None
        else:
            shocks = sc["shocks"]
            desc = sc["desc"]
            year = sc["year"]

        contribs = []
        impact = 0.0
        for h, w in zip(holdings, norm):
            shk = _holding_shock(h, shocks, custom_shocks if (name not in STRESS_SCENARIOS) else None)
            c = w * shk * base_value
            impact += c
            contribs.append({
                "symbol": h.get("symbol"),
                "asset_class": h.get("asset_class"),
                "weight": round(w, 6),
                "shock": round(shk, 6),
                "contribution": round(c, 2),
            })
        contribs.sort(key=lambda x: x["contribution"])
        worst_h = contribs[0] if contribs else None
        results.append({
            "name": name,
            "year": year,
            "desc": desc,
            "impact_value": round(impact, 2),
            "impact_pct": round(impact / base_value, 6),
            "post_value": round(base_value + impact, 2),
            "worst_holding": worst_h,
            "contributions": contribs,
        })

    # 自定义情景（若有且未包含在 scenarios 显式列举里）
    if custom_shocks and custom_name not in scenario_names:
        contribs = []
        impact = 0.0
        for h, w in zip(holdings, norm):
            shk = _holding_shock(h, {}, custom_shocks)
            c = w * shk * base_value
            impact += c
            contribs.append({
                "symbol": h.get("symbol"),
                "asset_class": h.get("asset_class"),
                "weight": round(w, 6),
                "shock": round(shk, 6),
                "contribution": round(c, 2),
            })
        contribs.sort(key=lambda x: x["contribution"])
        results.append({
            "name": custom_name,
            "year": None,
            "desc": "用户自定义冲击",
            "impact_value": round(impact, 2),
            "impact_pct": round(impact / base_value, 6),
            "post_value": round(base_value + impact, 2),
            "worst_holding": contribs[0] if contribs else None,
            "contributions": contribs,
        })

    results.sort(key=lambda r: r["impact_pct"])
    worst = results[0] if results else None

    impact_pcts = [r["impact_pct"] for r in results]
    summary = {
        "n_scenarios": len(results),
        "max_loss_pct": round(min(impact_pcts), 6) if impact_pcts else 0.0,
        "min_loss_pct": round(max(impact_pcts), 6) if impact_pcts else 0.0,
        "mean_loss_pct": round(sum(impact_pcts) / len(impact_pcts), 6) if impact_pcts else 0.0,
        "worst_scenario": worst["name"] if worst else None,
    }

    return {
        "base_value": base_value,
        "asset_class_labels": ASSET_CLASS_LABELS,
        "scenarios": results,
        "worst": worst,
        "summary": summary,
    }
