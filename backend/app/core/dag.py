"""DAG 工作流图：构建、校验、拓扑排序、环检测。

工作流 JSON 结构（前后端契约）：
    {
      "nodes": [{"id": "n1", "node_type": "math.add", "params": {...}}],
      "edges":  [{"id": "e1", "source": "n1", "source_port": "result",
                  "target": "n2", "target_port": "a"}]
    }
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Set

from .node import BaseWorkNode, WorkflowValidationError
from .registry import REGISTRY


@dataclass
class WorkflowNode:
    id: str
    node_type: str
    params: Dict = field(default_factory=dict)


@dataclass
class WorkflowEdge:
    id: str
    source: str
    source_port: str
    target: str
    target_port: str


class WorkflowGraph:
    """一张工作流图。构建时完成全部静态校验。"""

    def __init__(self):
        self.nodes: Dict[str, WorkflowNode] = {}
        self.edges: List[WorkflowEdge] = []
        # 邻接（执行依赖）：node -> 下游节点集合
        self._adjacency: Dict[str, Set[str]] = {}
        # 每个节点已满足依赖数 / 总依赖数（用于并发调度）
        self._deps: Dict[str, int] = {}
        # (target, target_port) -> 上游输出节点
        self._port_feeds: Dict[tuple, str] = {}

    # ------------------------------------------------------------------ #
    # 构建
    # ------------------------------------------------------------------ #
    @classmethod
    def build(cls, nodes: List[dict], edges: List[dict]) -> "WorkflowGraph":
        graph = cls()

        # 1. 节点：唯一 id + 已注册类型
        for n in nodes:
            nid, ntype = n.get("id", ""), n.get("node_type", "")
            if not nid:
                raise WorkflowValidationError("节点缺少 id")
            if nid in graph.nodes:
                raise WorkflowValidationError(f"节点 id 重复: {nid}")
            if not REGISTRY.has(ntype):
                raise WorkflowValidationError(f"节点 {nid} 引用了未注册类型: {ntype}")
            graph.nodes[nid] = WorkflowNode(id=nid, node_type=ntype, params=n.get("params") or {})
            graph._adjacency[nid] = set()
            graph._deps[nid] = 0

        # 2. 边：端口存在性 + 端口类型兼容
        for e in edges:
            eid = e.get("id", "")
            source, target = e.get("source", ""), e.get("target", "")
            sp, tp = e.get("source_port", ""), e.get("target_port", "")
            if source not in graph.nodes or target not in graph.nodes:
                raise WorkflowValidationError(f"边 {eid} 引用了不存在的节点: {source} -> {target}")
            if source == target:
                raise WorkflowValidationError(f"自环不允许: {source} -> {target}")
            src_cls = REGISTRY.get(graph.nodes[source].node_type)
            tgt_cls = REGISTRY.get(graph.nodes[target].node_type)
            src_port = next((p for p in src_cls.output_ports if p.name == sp), None)
            tgt_port = next((p for p in tgt_cls.input_ports if p.name == tp), None)
            if src_port is None:
                raise WorkflowValidationError(f"节点 {source} 无输出端口 '{sp}'")
            if tgt_port is None:
                raise WorkflowValidationError(f"节点 {target} 无输入端口 '{tp}'")
            if not _types_compatible(src_port.type, tgt_port.type):
                raise WorkflowValidationError(
                    f"端口类型不兼容: {source}.{sp}({src_port.type}) -> {target}.{tp}({tgt_port.type})"
                )
            feed_key = (target, tp)
            if feed_key in graph._port_feeds:
                raise WorkflowValidationError(
                    f"端口 {target}.{tp} 已接入 {graph._port_feeds[feed_key]}，输入端口只允许单一来源"
                )
            graph._port_feeds[feed_key] = source
            graph.edges.append(
                WorkflowEdge(id=eid or f"{source}:{sp}->{target}:{tp}",
                             source=source, source_port=sp, target=target, target_port=tp)
            )
            if target not in graph._adjacency[source]:
                graph._adjacency[source].add(target)
                graph._deps[target] += 1

        # 3. 环检测 + 拓扑序
        graph.topo_order()
        return graph

    # ------------------------------------------------------------------ #
    # 图算法
    # ------------------------------------------------------------------ #
    def topo_order(self) -> List[str]:
        """Kahn 拓扑排序；存在环时抛 WorkflowValidationError。"""
        indegree = dict(self._deps)
        ready = [nid for nid, d in indegree.items() if d == 0]
        order: List[str] = []
        while ready:
            nid = ready.pop()
            order.append(nid)
            for nxt in self._adjacency[nid]:
                indegree[nxt] -= 1
                if indegree[nxt] == 0:
                    ready.append(nxt)
        if len(order) != len(self.nodes):
            cyclic = [nid for nid, d in indegree.items() if d > 0]
            raise WorkflowValidationError(f"工作流存在环，无法执行: {cyclic}")
        return order

    def dependency_count(self, node_id: str) -> int:
        return self._deps.get(node_id, 0)

    def downstream(self, node_id: str) -> Set[str]:
        return self._adjacency.get(node_id, set())


def _types_compatible(src: str, dst: str) -> bool:
    if src == dst:
        return True
    # 宽松规则：任意值可流入 string 端口（展示型端口）
    return dst == "string"


def validate_workflow(nodes: List[dict], edges: List[dict]) -> WorkflowGraph:
    """构建 + 校验入口（API 层调用）。"""
    return WorkflowGraph.build(nodes, edges)
