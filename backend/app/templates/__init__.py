"""内置示例工作流模板库（V1.1 遗留项，V1.3 扩展）。

提供 3 个可直接加载运行的内置策略模板：均线交叉（股票）、动量因子（股票）、
期货均线多空（期货）。模板为纯 dict（nodes + edges），可被前端「模板库」加载到画布，
也可经 API 读取。所有模板均通过 validate_workflow 校验，并使用 fixture 行情端到端运行。
"""

from __future__ import annotations

from typing import Dict, List

# 每个模板：{id, name, description, tags, nodes, edges}
BUILTIN_TEMPLATES: List[Dict] = [
    {
        "id": "ma_cross",
        "name": "均线交叉策略",
        "description": (
            "拉取行情 → 计算 5/20 日均线 → 生成「短均线上穿长均线」信号 → "
            "对信号表运行 ma_cross 回测。演示「数据→特征→因子→回测」完整链路。"
        ),
        "tags": ["股票", "均线", "趋势"],
        "nodes": [
            {
                "id": "quotes",
                "node_type": "data.quotes",
                "params": {
                    "symbol": "TEST.STOCK",
                    "start": "2024-01-01",
                    "end": "2024-04-01",
                },
            },
            {"id": "ma_short", "node_type": "indicator.ma", "params": {"window": 5}},
            {"id": "ma_long", "node_type": "indicator.ma", "params": {"window": 20}},
            {
                "id": "signal",
                "node_type": "factor.expression",
                "params": {"expression": "ma5 > ma20", "output": "signal"},
            },
            {
                "id": "bt",
                "node_type": "backtest.run",
                "params": {"strategy": "ma_cross"},
            },
        ],
        "edges": [
            {"source": "quotes", "source_port": "table", "target": "ma_short", "target_port": "table"},
            {"source": "ma_short", "source_port": "table", "target": "ma_long", "target_port": "table"},
            {"source": "ma_long", "source_port": "table", "target": "signal", "target_port": "table"},
            {"source": "signal", "source_port": "table", "target": "bt", "target_port": "table"},
        ],
    },
    {
        "id": "momentum",
        "name": "动量因子策略",
        "description": (
            "拉取行情 → 用收盘价动量(日收益率) 构建因子列 → 对行情表运行 buy_hold 回测。"
            "演示因子构建与回测的最小闭环。"
        ),
        "tags": ["股票", "动量", "因子"],
        "nodes": [
            {
                "id": "quotes",
                "node_type": "data.quotes",
                "params": {
                    "symbol": "TEST.STOCK",
                    "start": "2024-01-01",
                    "end": "2024-03-01",
                },
            },
            {
                "id": "mom",
                "node_type": "factor.expression",
                "params": {"expression": "close.pct_change()", "output": "momentum"},
            },
            {
                "id": "bt",
                "node_type": "backtest.run",
                "params": {"strategy": "buy_hold"},
            },
        ],
        "edges": [
            {"source": "quotes", "source_port": "table", "target": "mom", "target_port": "table"},
            {"source": "mom", "source_port": "table", "target": "bt", "target_port": "table"},
        ],
    },
    {
        "id": "futures_ma_cross",
        "name": "期货均线多空策略",
        "description": (
            "拉取股指期货行情（TEST.FUTURE，合约乘数 10）→ 用 futures_ma_cross 策略："
            "均线金叉做多、死叉做空（多空净仓 + 保证金 + 强平）。演示 V1.3 期货回测链路。"
        ),
        "tags": ["期货", "均线", "多空", "保证金"],
        "nodes": [
            {
                "id": "quotes",
                "node_type": "data.quotes",
                "params": {
                    "symbol": "TEST.FUTURE",
                    "start": "2024-01-01",
                    "end": "2024-04-01",
                },
            },
            {
                "id": "bt",
                "node_type": "backtest.run",
                "params": {
                    "strategy": "futures_ma_cross",
                    "asset_type": "future",
                    "contracts": 1,
                    "multiplier": 10.0,
                },
            },
        ],
        "edges": [
            {"source": "quotes", "source_port": "table", "target": "bt", "target_port": "table"},
        ],
    },
]


def list_templates() -> List[Dict]:
    """返回模板列表（含 nodes/edges，前端可直接加载）。"""
    return BUILTIN_TEMPLATES


def get_template(template_id: str) -> Dict | None:
    for t in BUILTIN_TEMPLATES:
        if t["id"] == template_id:
            return t
    return None
