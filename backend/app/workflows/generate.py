"""自然语言 → 工作流生成（V3.0 AI 策略工作台）。

把用户的自然语言策略描述转换为可直接导入编辑器运行的工作流 JSON。

两条生成路径：
1. **规则兜底（默认、离线可用）**：复用已通过校验的内置模板骨架
   （均线交叉 / 动量 / 期货多空），按描述中的关键词与参数（标的、窗口）
   实例化，保证生成的工作流一定通过 ``validate_workflow``。
2. **LLM 增强（可选）**：当配置了真实 LLM 时，把节点目录与描述喂给模型，
   要求它产出符合 schema 的工作流 JSON；再做严格校验，失败则回退到规则生成。

无论哪条路径，返回结构都包含 ``nodes`` / ``edges``，可直接交给
``/api/workflows/import``。
"""

from __future__ import annotations

import copy
import json
import re
from typing import Dict, List, Optional, Tuple

from ..core.dag import validate_workflow
from ..core.registry import REGISTRY
from ..templates import BUILTIN_TEMPLATES

DEFAULT_SYMBOL = "TEST.STOCK"
DEFAULT_START = "2024-01-01"
DEFAULT_END = "2024-04-01"


# --------------------------------------------------------------------------- #
# 描述解析
# --------------------------------------------------------------------------- #
def _parse_symbol(text: str) -> str:
    m = re.search(r"TEST\.[A-Za-z]+", text)
    if m:
        return m.group(0).upper()
    return DEFAULT_SYMBOL


def _parse_window(text: str, default: int = 20) -> int:
    # 匹配「N 日 / N 天 / 窗口 N / window N」
    m = re.search(r"(?:窗口|window|(\d+)\s*(?:日|天|周期))", text, re.IGNORECASE)
    if m and m.group(1):
        try:
            return max(2, min(60, int(m.group(1))))
        except ValueError:
            return default
    return default


# --------------------------------------------------------------------------- #
# 规则兜底生成
# --------------------------------------------------------------------------- #
def _clone_template(tpl_id: str) -> Dict:
    for t in BUILTIN_TEMPLATES:
        if t["id"] == tpl_id:
            return copy.deepcopy(t)
    raise KeyError(f"未知模板: {tpl_id}")


def _apply_quote_params(nodes: List[Dict], symbol: str, start: str, end: str) -> None:
    for n in nodes:
        if n.get("node_type") == "data.quotes":
            n.setdefault("params", {})
            n["params"].update({"symbol": symbol, "start": start, "end": end})
            # 保证有画布坐标（编辑器 applyWorkflow 也有兜底）
            n.setdefault("position", {"x": 40, "y": 80})


def _rule_generate(text: str) -> Tuple[Dict, List[str]]:
    t = text.lower()
    warnings: List[str] = []
    if any(k in t for k in ["期货", "future", "多空", "做空", "futures"]):
        tpl = _clone_template("futures_ma_cross")
        name = "期货均线多空策略"
        symbol = _parse_symbol(text) or "TEST.FUTURE"
    elif any(k in t for k in ["动量", "momentum", "追涨", "趋势", "动量"]):
        tpl = _clone_template("momentum")
        name = "动量因子策略"
        symbol = _parse_symbol(text)
    else:
        tpl = _clone_template("ma_cross")
        name = "均线交叉策略"
        symbol = _parse_symbol(text)
        short = _parse_window(text, 5)
        long = max(short + 1, _parse_window(text, 20))
        # 把指标窗口写回对应节点
        for n in tpl["nodes"]:
            if n.get("node_type") == "indicator.ma":
                n["params"]["window"] = n["params"].get("window", 20) if n["id"] == "ma_long" else short
        # 长均线用较大窗口
        for n in tpl["nodes"]:
            if n.get("node_type") == "indicator.ma" and n["id"] == "ma_long":
                n["params"]["window"] = long

    _apply_quote_params(tpl["nodes"], symbol, DEFAULT_START, DEFAULT_END)
    # 为节点补齐 position（避免编辑器里重叠）
    for i, n in enumerate(tpl["nodes"]):
        n.setdefault("position", {"x": 40 + i * 220, "y": 80})
    # 为边补齐 id
    for i, e in enumerate(tpl["edges"]):
        e.setdefault("id", f"e{i+1}")

    result = {
        "name": name,
        "description": f"由规则生成：{text}",
        "nodes": tpl["nodes"],
        "edges": tpl["edges"],
    }
    return result, warnings


# --------------------------------------------------------------------------- #
# LLM 增强生成
# --------------------------------------------------------------------------- #
# 仅允许 LLM 使用「已知可端到端运行」的节点集合，且必须以 backtest.run 收口，
# 否则回退规则模板，避免生成「结构合法但运行失败」的工作流。
SAFE_NODE_TYPES = {"data.quotes", "indicator.ma", "factor.expression", "backtest.run"}

_SYSTEM_PROMPT = (
    "你是 QuantFlow 量化工作流生成器。只输出一个 JSON 对象，"
    "描述一个可运行的工作流，结构严格如下：\n"
    '{"name": "策略名", "description": "简短说明", '
    '"nodes": [{"id":"n1","node_type":"data.quotes","params":{"symbol":"TEST.STOCK","start":"2024-01-01","end":"2024-04-01"}}], '
    '"edges": [{"source":"n1","source_port":"table","target":"n2","target_port":"table"}]}\n'
    "约束（必须严格遵守）：\n"
    "1. 只能用以下 node_type：data.quotes（行情源）、indicator.ma（均线指标，参数 window）、"
    "factor.expression（因子表达式，参数 expression/output）、backtest.run（回测，参数 strategy）。\n"
    "2. 必须以一个 backtest.run 节点作为终点（汇点），且从 data.quotes 开始形成有向链路。\n"
    "3. 端口统一用 source_port:\"table\" / target_port:\"table\"；strategy用 ma_cross / buy_hold / futures_ma_cross 之一。\n"
    "4. factor.expression 的 expression 只能使用真实行情列 open/high/low/close/volume 与四则运算及"
    " log/abs/.shift()（例如 '(close-open)/open'、'close/close.shift(1)-1'、'log(volume)'），"
    "严禁引用 ma / rsi / 任何指标变量或未定义符号，否则该节点会求值失败。\n"
    "5. 信号优先用 indicator.ma（短/长均线交叉）喂给 backtest.run；factor.expression 仅用于简单价格/成交量衍生。\n"
    "可用节点类型与端口详情：\n"
)


def _catalog_text() -> str:
    parts = []
    for spec in REGISTRY.specs():
        ins = ",".join(f"{p['name']}:{p.get('type','')}" for p in spec.get("inputs", []))
        outs = ",".join(f"{p['name']}:{p.get('type','')}" for p in spec.get("outputs", []))
        parts.append(f"- {spec['node_type']}：{spec.get('description','')} （输入[{ins}] 输出[{outs}]）")
    return "\n".join(parts)


def _extract_json(text: str) -> Optional[dict]:
    # 优先匹配 ```json ... ``` 代码块
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(1))
        except json.JSONDecodeError:
            pass
    # 否则截取第一个 { 到最后一个 }
    s = text.find("{")
    e = text.rfind("}")
    if s != -1 and e != -1 and e > s:
        try:
            return json.loads(text[s : e + 1])
        except json.JSONDecodeError:
            return None
    return None


def _llm_generate(text: str) -> Optional[Tuple[Dict, List[str]]]:
    """调用已配置的 LLM 生成工作流；任何异常返回 None 以触发回退。"""
    try:
        from ..core.llm import get_provider

        provider = get_provider()
        if not provider.is_configured():
            return None
        messages = [
            {"role": "system", "content": _SYSTEM_PROMPT + _catalog_text()},
            {"role": "user", "content": f"请为以下策略描述生成工作流 JSON：{text}"},
        ]
        out = provider.chat([__import__("app.core.llm", fromlist=["LLMMessage"]).LLMMessage(**m) for m in messages])
    except Exception:
        return None

    parsed = _extract_json(out or "")
    if not parsed or not isinstance(parsed.get("nodes"), list) or not parsed.get("edges"):
        return None
    # 规范化
    nodes = []
    for n in parsed["nodes"]:
        if not n.get("id") or not n.get("node_type"):
            return None
        if n["node_type"] not in SAFE_NODE_TYPES:
            return None
        nodes.append({
            "id": n["id"],
            "node_type": n["node_type"],
            "params": n.get("params") or {},
            "position": n.get("position") or {"x": 40, "y": 80},
        })
    edges = []
    for i, e in enumerate(parsed["edges"]):
        if not e.get("source") or not e.get("target"):
            return None
        edges.append({
            "id": e.get("id") or f"e{i+1}",
            "source": e["source"],
            "source_port": e.get("source_port", "table"),
            "target": e["target"],
            "target_port": e.get("target_port", "table"),
        })
    # 必须存在 backtest.run 收口节点，否则执行期会因无回测汇点而失败
    if not any(n["node_type"] == "backtest.run" for n in nodes):
        return None
    try:
        validate_workflow(nodes, edges)
    except Exception:
        return None
    return {
        "name": parsed.get("name") or "LLM 生成的策略",
        "description": parsed.get("description") or f"由 LLM 生成：{text}",
        "nodes": nodes,
        "edges": edges,
    }, []


# --------------------------------------------------------------------------- #
# 对外入口
# --------------------------------------------------------------------------- #
def generate_from_text(text: str, use_llm: bool = True) -> Dict:
    """生成工作流。优先尝试 LLM（若可用且 use_llm），失败回退规则生成。"""
    warnings: List[str] = []
    source = "rule"
    result: Optional[Dict] = None

    if use_llm:
        llm = _llm_generate(text)
        if llm is not None:
            result, _ = llm
            source = "llm"
        else:
            warnings.append("LLM 未配置或生成未通过校验，已回退到规则模板生成")

    if result is None:
        result, w = _rule_generate(text)
        warnings.extend(w)

    return {
        "name": result["name"],
        "description": result["description"],
        "nodes": result["nodes"],
        "edges": result["edges"],
        "source": source,
        "warnings": warnings,
    }
