"""轻量表格数据类型（DataTable）。

V1.0 演进：行情/特征/因子数据以 DataTable 在节点间传递，
后续基于 pandas 实现时保留 to_dict/from_dict 作为序列化契约。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional


class DataTable:
    """列式表格：columns + rows（每行一个 dict）。

    节点间传递的市场/指标数据统一用该类型，便于：
    - 跨节点传递（无需共享内存）
    - 序列化到运行结果（前端预览表格）
    - 后续无损迁移到 pandas DataFrame
    """

    def __init__(self, columns: List[str], rows: Optional[List[Dict[str, Any]]] = None):
        self.columns = list(columns)
        self.rows = rows or []

    def to_dict(self) -> dict:
        return {"columns": self.columns, "rows": self.rows}

    @classmethod
    def from_dict(cls, data: dict) -> "DataTable":
        return cls(columns=data.get("columns", []), rows=data.get("rows", []))

    def head(self, n: int = 5) -> "DataTable":
        return DataTable(self.columns, self.rows[:n])

    def __len__(self) -> int:
        return len(self.rows)

    def __repr__(self) -> str:
        return f"DataTable(columns={self.columns}, rows={len(self.rows)})"


# 值 -> 可序列化（执行结果落库 / 推送前端时调用）
def to_serializable(value: Any) -> Any:
    if isinstance(value, DataTable):
        return {"__type__": "table", **value.to_dict()}
    return value
