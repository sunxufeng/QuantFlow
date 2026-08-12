"""工作流执行引擎：并发 DAG 执行 + 失败传播。

M1 原型采用 ThreadPoolExecutor 的 ready-queue 调度：
- 依赖满足即执行（兄弟节点并行）
- 节点失败 → 该节点 FAILED，其下游（传递闭包）标记 BLOCKED，其余分支继续
- 产出记录每个节点的运行状态与输出，供前端 WebSocket 可视化复用
"""

from __future__ import annotations

import threading
import time
import uuid
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from .dag import WorkflowGraph
from .data import to_serializable
from .node import (
    NodeExecutionError,
    WorkNodeContext,
    instantiate_node,
)


# --------------------------------------------------------------------------- #
# 运行状态
# --------------------------------------------------------------------------- #
class NodeStatus:
    PENDING = "pending"
    RUNNING = "running"
    SUCCEEDED = "succeeded"
    FAILED = "failed"
    BLOCKED = "blocked"


@dataclass
class NodeRunState:
    node_id: str
    status: str = NodeStatus.PENDING
    error: Optional[str] = None
    duration_ms: float = 0.0
    outputs: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "node_id": self.node_id,
            "status": self.status,
            "error": self.error,
            "duration_ms": round(self.duration_ms, 2),
            "outputs": {k: to_serializable(v) for k, v in self.outputs.items()},
        }


@dataclass
class RunResult:
    run_id: str
    status: str
    node_states: Dict[str, NodeRunState] = field(default_factory=dict)
    started_at: float = 0.0
    finished_at: float = 0.0

    def to_dict(self) -> dict:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round((self.finished_at - self.started_at) * 1000, 2),
            "nodes": [st.to_dict() for st in self.node_states.values()],
        }


# --------------------------------------------------------------------------- #
# 执行器
# --------------------------------------------------------------------------- #
class WorkflowExecutor:
    def __init__(self, max_workers: int = 4):
        self.max_workers = max_workers

    def run(self, graph: WorkflowGraph, run_id: Optional[str] = None) -> RunResult:
        run_id = run_id or uuid.uuid4().hex[:12]
        result = RunResult(run_id=run_id, status="running", started_at=time.time())
        states = {nid: NodeRunState(node_id=nid) for nid in graph.nodes}
        result.node_states = states

        outputs: Dict[str, Dict[str, Any]] = {}
        pending = dict(graph._deps)          # 每个节点剩余未满足的依赖数
        submitted: Set[str] = set()
        cancelled: Set[str] = set()          # 失败节点的下游（传递闭包）
        run_failed = False
        lock = threading.Lock()

        def _mark_cancelled(start: str) -> None:
            stack = list(graph.downstream(start))
            while stack:
                nid = stack.pop()
                if nid in cancelled:
                    continue
                cancelled.add(nid)
                stack.extend(graph.downstream(nid))

        def _collect_inputs(nid: str) -> Dict[str, Any]:
            inputs: Dict[str, Any] = {}
            for edge in graph.edges:
                if edge.target == nid:
                    inputs[edge.target_port] = outputs.get(edge.source, {}).get(edge.source_port)
            return inputs

        def _run_node(nid: str) -> None:
            nonlocal run_failed
            node = graph.nodes[nid]
            inst = instantiate_node(node.node_type, nid, node.params)
            ctx = WorkNodeContext(run_id=run_id, node_id=nid)
            started = time.time()
            states[nid].status = NodeStatus.RUNNING
            inputs = _collect_inputs(nid)
            try:
                inst.validate_inputs(inputs)
                out = inst.execute(ctx, inputs)
                states[nid].outputs = out or {}
                states[nid].duration_ms = (time.time() - started) * 1000
                states[nid].status = NodeStatus.SUCCEEDED
            except NodeExecutionError as exc:
                states[nid].error = exc.message
                states[nid].duration_ms = (time.time() - started) * 1000
                states[nid].status = NodeStatus.FAILED
                raise
            except Exception as exc:  # 兜底：未包装异常统一转为节点失败
                states[nid].error = f"{type(exc).__name__}: {exc}"
                states[nid].duration_ms = (time.time() - started) * 1000
                states[nid].status = NodeStatus.FAILED
                raise NodeExecutionError(nid, states[nid].error) from exc
            finally:
                with lock:
                    if states[nid].status == NodeStatus.SUCCEEDED:
                        outputs[nid] = states[nid].outputs
                    elif not run_failed:
                        run_failed = True
                        _mark_cancelled(nid)

        def _schedule_ready(pool: ThreadPoolExecutor, futures: dict) -> None:
            with lock:
                ready = [
                    nid for nid, d in pending.items()
                    if nid not in submitted and nid not in cancelled and d <= 0
                ]
                for nid in ready:
                    if run_failed:
                        break
                    submitted.add(nid)
                    futures[pool.submit(_run_node, nid)] = nid

        with ThreadPoolExecutor(max_workers=self.max_workers) as pool:
            futures: dict = {}
            _schedule_ready(pool, futures)
            while futures:
                done, _ = wait(futures, return_when=FIRST_COMPLETED)
                for fut in done:
                    nid = futures.pop(fut)
                    try:
                        fut.result()
                    except NodeExecutionError:
                        pass  # 状态已由 _run_node 记录
                    with lock:
                        for nxt in graph.downstream(nid):
                            pending[nxt] -= 1
                _schedule_ready(pool, futures)

        # 收尾：未执行的节点按取消原因标记
        for nid, st in states.items():
            if st.status in (NodeStatus.PENDING, NodeStatus.RUNNING):
                st.status = NodeStatus.BLOCKED

        result.status = "failed" if run_failed else "succeeded"
        result.finished_at = time.time()
        return result
