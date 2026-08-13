"""处理节点：清洗、去重、缺失值、对齐合并（M3 处理节点）。

对齐开发计划 §4.3「处理节点：清洗、去重、缺失值、对齐合并」。
"""

from __future__ import annotations


from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node
from ._utils import df_to_table, require_table, table_to_df


@work_node(
    "table.clean",
    label="数据清洗",
    category="处理",
    description="剔除关键列缺失的行，并可对指定列去除首尾空白",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("key_columns", "string", default="", label="关键列（逗号分隔，空=全部非空校验）"),
        ParamSpec("strip_text", "boolean", default=True, label="去除字符串空白"),
    ],
)
class CleanNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        table = require_table(inputs["table"])
        df = table_to_df(table)
        keys = [k.strip() for k in str(self.params.get("key_columns") or "").split(",") if k.strip()]
        if keys:
            df = df.dropna(subset=keys)
        else:
            df = df.dropna(how="any")
        if self.params.get("strip_text", True):
            import pandas as pd

            for col in df.columns:
                if pd.api.types.is_string_dtype(df[col]):
                    df[col] = df[col].map(lambda v: v.strip() if isinstance(v, str) else v)
        return {"table": df_to_table(df, table.columns)}


@work_node(
    "table.dedupe",
    label="去重",
    category="处理",
    description="按指定列去除重复行，保留首次出现",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("columns", "string", default="", label="去重列（逗号分隔，空=整行去重）"),
        ParamSpec("keep", "string", default="first", label="保留策略", options=["first", "last"]),
    ],
)
class DedupeNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        table = require_table(inputs["table"])
        df = table_to_df(table)
        cols = [c.strip() for c in str(self.params.get("columns") or "").split(",") if c.strip()]
        df = df.drop_duplicates(subset=cols or None, keep=str(self.params.get("keep") or "first"))
        return {"table": df_to_table(df.reset_index(drop=True), table.columns)}


@work_node(
    "table.fillna",
    label="缺失值填充",
    category="处理",
    description="对数值列填充缺失：前向/后向/零/均值/指定值",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("method", "string", default="ffill", label="填充方法",
                  options=["ffill", "bfill", "zero", "mean", "value"]),
        ParamSpec("columns", "string", default="", label="目标列（逗号分隔，空=全部数值列）"),
        ParamSpec("value", "number", default=0.0, label="指定填充值（method=value 时生效）"),
    ],
)
class FillNaNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        table = require_table(inputs["table"])
        df = table_to_df(table)
        cols = [c.strip() for c in str(self.params.get("columns") or "").split(",") if c.strip()]
        method = str(self.params.get("method") or "ffill")
        target = [c for c in (cols or df.columns.tolist()) if c in df.columns]
        for col in target:
            if not _is_numeric(df[col]):
                continue
            if method == "ffill":
                df[col] = df[col].ffill().bfill()
            elif method == "bfill":
                df[col] = df[col].bfill().ffill()
            elif method == "zero":
                df[col] = df[col].fillna(0.0)
            elif method == "mean":
                df[col] = df[col].fillna(df[col].mean())
            else:
                df[col] = df[col].fillna(float(self.params.get("value") or 0.0))
        return {"table": df_to_table(df, table.columns)}


@work_node(
    "table.merge",
    label="对齐合并",
    category="处理",
    description="按关键列对齐合并两张表（inner/left/outer）",
    inputs=[
        PortSpec("table_a", "table", label="表 A"),
        PortSpec("table_b", "table", label="表 B"),
    ],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("on", "string", default="date", label="对齐列"),
        ParamSpec("how", "string", default="inner", label="合并方式", options=["inner", "left", "outer"]),
        ParamSpec("suffixes", "string", default="_a,_b", label="重名列后缀"),
    ],
)
class MergeNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        ta = require_table(inputs["table_a"], "table_a")
        tb = require_table(inputs["table_b"], "table_b")
        on = str(self.params.get("on") or "date").strip()
        how = str(self.params.get("how") or "inner")
        suffixes = [s.strip() for s in str(self.params.get("suffixes") or "_a,_b").split(",")]
        suffixes = (suffixes + ["_a", "_b"])[:2]
        df = table_to_df(ta).merge(table_to_df(tb), on=on, how=how, suffixes=tuple(suffixes))
        return {"table": df_to_table(df)}


def _is_numeric(series) -> bool:
    import pandas as pd

    return pd.api.types.is_numeric_dtype(series)
