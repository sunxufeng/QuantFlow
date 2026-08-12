"""节点数据传递与输出预览（M2 执行引擎 DataBridge）。

对标开发计划 §4.2「节点数据传递（引用/落盘策略、输出预览生成）」：

- 节点产出统一经 :meth:`DataBridge.capture` 登记：生成输出预览（表格取前 N 行），
  超出阈值的大数据落盘为 JSON（磁盘引用），小数据保留内存引用
- :meth:`DataBridge.read` 按 run_id + node_id 读取完整产出（回放/二次消费）
- 预览用于前端运行视图（节点输出预览），避免全量数据传输
"""

from __future__ import annotations

import json
import os
from typing import Any, Dict, Optional

from ..core.data import DataTable

# 默认数据目录（backend/data/runs/<run_id>/<node_id>.json）
DEFAULT_RUN_DATA_DIR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data", "runs"
)

# 预览行数 / 数组元素数
PREVIEW_ROWS = 10

# 内存转落盘的序列化大小阈值（字节）
SPILL_THRESHOLD = 512_000


def make_preview(value: Any, depth: int = 0) -> Any:
    """生成输出预览（表格/数组截断，标量原样）。"""
    if isinstance(value, DataTable):
        return {
            "type": "table",
            "columns": value.columns,
            "rows": value.rows[:PREVIEW_ROWS],
            "total_rows": len(value.rows),
        }
    if isinstance(value, list):
        return {
            "type": "array",
            "length": len(value),
            "preview": value[:PREVIEW_ROWS],
        }
    if isinstance(value, dict) and depth < 2:
        return {
            "type": "object",
            "keys": list(value.keys())[:PREVIEW_ROWS],
            "preview": {k: make_preview(v, depth + 1) for k, v in list(value.items())[:3]},
        }
    return value


class DataBridge:
    """节点产出登记器：内存引用 + 大数据落盘 + 预览生成。"""

    def __init__(self, data_dir: Optional[str] = None, spill_threshold: int = SPILL_THRESHOLD) -> None:
        self.data_dir = data_dir or DEFAULT_RUN_DATA_DIR
        self.spill_threshold = spill_threshold
        # 内存引用：run_id -> node_id -> outputs（同一进程内下游/回放直接读取）
        self._store: Dict[str, Dict[str, Any]] = {}

    # ------------------------------------------------------------------ #
    def capture(self, run_id: str, node_id: str, outputs: Dict[str, Any]) -> dict:
        """登记节点产出，返回输出记录（存储方式 + 预览 + 引用）。"""
        preview = {port: make_preview(value) for port, value in outputs.items()}
        storage = "memory"
        path = ""
        size = self._serialized_size(outputs)
        if size > self.spill_threshold:
            path = self._write_disk(run_id, node_id, outputs)
            storage = "disk"
        self._store.setdefault(run_id, {})[node_id] = outputs
        return {
            "run_id": run_id,
            "node_id": node_id,
            "storage": storage,
            "path": path,
            "bytes": size,
            "preview": preview,
        }

    def read(self, run_id: str, node_id: str) -> Dict[str, Any]:
        """读取节点完整产出；未登记时返回空 dict。"""
        run_store = self._store.get(run_id, {})
        if node_id in run_store:
            return run_store[node_id]
        path = self._path(run_id, node_id)
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                data = json.load(f)
            run_store[node_id] = data
            return data
        return {}

    def drop_run(self, run_id: str) -> None:
        """运行结束后清理（V1.0 保留内存引用用于查询，提供接口供回收）。"""
        self._store.pop(run_id, None)
        run_dir = os.path.join(self.data_dir, run_id)
        if os.path.isdir(run_dir):
            import shutil

            shutil.rmtree(run_dir, ignore_errors=True)

    # ------------------------------------------------------------------ #
    def _write_disk(self, run_id: str, node_id: str, outputs: Dict[str, Any]) -> str:
        path = self._path(run_id, node_id)
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(outputs, f, ensure_ascii=False, default=_json_default)
        return os.path.relpath(path, start=self.data_dir)

    def _path(self, run_id: str, node_id: str) -> str:
        safe_id = node_id.replace("/", "_").replace("\\", "_")
        return os.path.join(self.data_dir, run_id, f"{safe_id}.json")

    @staticmethod
    def _serialized_size(outputs: Dict[str, Any]) -> int:
        try:
            return len(json.dumps(outputs, ensure_ascii=False, default=_json_default))
        except Exception:
            return 0


def _json_default(obj: Any) -> Any:
    """DataTable 序列化兜底。"""
    if isinstance(obj, DataTable):
        return {"__type__": "table", **obj.to_dict()}
    return str(obj)
