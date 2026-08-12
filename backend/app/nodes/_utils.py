"""节点共享工具：DataTable <-> pandas DataFrame 转换。

M3 节点库统一基于 pandas 计算（特征/ML/因子/回测节点），
通过本模块与平台 DataTable 序列化契约互转，保证：
- 节点间传递仍用 DataTable（前端预览/落库兼容）
- 计算层享受 pandas 的向量化与丰富函数
"""

from __future__ import annotations

import math
from typing import Any, Dict, List

from ..core.data import DataTable

# NaN 兜底值：pandas NaN / inf 无法 JSON 序列化
_EMPTY = None


def _clean_value(v: Any) -> Any:
    if isinstance(v, float) and (math.isnan(v) or math.isinf(v)):
        return _EMPTY
    return v


def table_to_df(table: Any) -> "Any":
    """DataTable（或 dict）-> pandas DataFrame（列顺序保持）。"""
    import pandas as pd

    if isinstance(table, DataTable):
        return pd.DataFrame(table.rows, columns=table.columns)
    if isinstance(table, dict) and "columns" in table and "rows" in table:
        return pd.DataFrame(table["rows"], columns=table["columns"])
    if isinstance(table, pd.DataFrame):
        return table
    raise TypeError(f"table 端口需要 DataTable/dict，收到 {type(table).__name__}")


def df_to_table(df: Any, columns: List[str] | None = None) -> DataTable:
    """pandas DataFrame -> DataTable（NaN 清理 + 可序列化）。"""
    if df is None:
        return DataTable(columns or [], [])
    cols = list(columns) if columns is not None else [str(c) for c in df.columns]
    rows: List[Dict[str, Any]] = []
    for _, row in df.iterrows():
        rows.append({c: _clean_value(row[c]) for c in cols if c in df.columns})
    return DataTable(columns=cols, rows=rows)


def require_table(value: Any, port_name: str = "table") -> DataTable:
    """将输入端口值统一为 DataTable；缺失/非法抛可读错误。"""
    if isinstance(value, DataTable):
        return value
    if isinstance(value, dict) and "columns" in value and "rows" in value:
        return DataTable.from_dict(value)
    raise TypeError(f"输入端口 '{port_name}' 需要表格数据，收到 {type(value).__name__}")


def numeric_columns(table: DataTable) -> List[str]:
    """返回全数值列（供特征/因子/ML 默认列选择）。"""
    out = []
    for col in table.columns:
        vals = [r.get(col) for r in table.rows]
        if vals and all(isinstance(v, (int, float)) and not isinstance(v, bool) for v in vals):
            out.append(col)
    return out
