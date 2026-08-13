"""因子节点：表达式引擎、IC/ICIR、因子合成（M3 因子节点）。

V1.1 N3 起，核心计算统一委托给独立模块 ``app.factors``（stats / transform / analyzer），
本文件仅负责端口/参数编排与 DataTable 契约转换，输出格式与历史测试保持一致。
"""

from __future__ import annotations


from ..core.data import DataTable
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node
from ..factors.stats import ic_series, ic_summary
from ..factors.transform import composite_factors, expression_factor
from ._utils import df_to_table, require_table, table_to_df


@work_node(
    "factor.expression",
    label="表达式因子",
    category="因子",
    description="按 pandas 表达式计算新因子列，如 (close-open)/open、log(volume) 等",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("expression", "string", default="(close-open)/open", label="表达式",
                  description="基于列名的 pandas 表达式，如 log(close)、(close-open)/open"),
        ParamSpec("output", "string", default="factor", label="输出列名"),
    ],
)
class ExpressionFactorNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        return {"table": df_to_table(expression_factor(df, self.params["expression"], self.params["output"]))}


@work_node(
    "factor.ic",
    label="IC / ICIR",
    category="因子",
    description="计算因子与下期收益的 RankIC 序列与 ICIR（IC 均值 / IC 标准差）",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("factor", "string", default="factor", label="因子列"),
        ParamSpec("forward_return", "string", default="fwd_return", label="下期收益列"),
    ],
)
class ICNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        factor = str(self.params["factor"]).strip()
        ret = str(self.params["forward_return"]).strip()
        for col in (factor, ret):
            if col not in df.columns:
                raise ValueError(f"缺少列: {col}")

        series = ic_series(df, factor, ret, "date" if "date" in df.columns else None)
        rows = [
            {"date": d, "ic": round(ic, 6)}
            for d, ic in series
            if ic is not None
        ]
        summary = ic_summary([ic for _, ic in series])
        rows.append({"date": "__summary__", "ic": None})
        rows.append({"date": "__ic_mean__", "ic": summary["mean"]})
        rows.append({"date": "__icir__", "ic": summary["ir"]})
        return {"table": DataTable(columns=["date", "ic"], rows=rows)}


@work_node(
    "factor.composite",
    label="因子合成",
    category="因子",
    description="多因子等权/按重要度合成（先横截面标准化，再加权求和）",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("factor_columns", "string", default="factor1,factor2", label="因子列（逗号分隔）"),
        ParamSpec("weights", "string", default="", label="权重（逗号分隔，空=等权）"),
        ParamSpec("output", "string", default="composite", label="输出列名"),
    ],
)
class CompositeFactorNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        cols = [c.strip() for c in str(self.params["factor_columns"]).split(",") if c.strip()]
        if not cols:
            raise ValueError("至少需要一个因子列")
        for c in cols:
            if c not in df.columns:
                raise ValueError(f"缺少因子列: {c}")
        weights_raw = [w.strip() for w in str(self.params.get("weights") or "").split(",") if w.strip()]
        weights = None
        if weights_raw:
            weights = [float(w) for w in weights_raw]
            if len(weights) != len(cols):
                raise ValueError("权重数量需与因子列一致")
        output = str(self.params.get("output") or "composite").strip() or "composite"
        df[output] = composite_factors(df, cols, weights)
        return {"table": df_to_table(df)}
