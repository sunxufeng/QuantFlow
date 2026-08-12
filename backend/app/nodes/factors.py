"""因子节点：表达式引擎、IC/ICIR、因子合成（M3 因子节点）。

对齐开发计划 §4.3「因子节点：因子计算、IC/ICIR、因子合成（重要度+Spearman）」。
表达式因子节点基于 pandas eval，支持对列名的算术/逻辑运算。
"""

from __future__ import annotations

from typing import Any, Dict

from ..core.data import DataTable
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node
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
        expr = str(self.params["expression"]).strip()
        output = str(self.params.get("output") or "factor").strip() or "factor"
        if not expr:
            raise ValueError("表达式为空")
        try:
            df[output] = df.eval(expr)
        except Exception as exc:
            raise ValueError(f"表达式求值失败（{expr}）: {exc}") from exc
        return {"table": df_to_table(df)}


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
        if "date" in df.columns:
            grouped = df.dropna(subset=[factor, ret]).groupby("date")
        else:
            grouped = [("", df.dropna(subset=[factor, ret]))]
        ics, rows = [], []
        for date, sub in grouped:
            if len(sub) < 3:
                continue
            ic = sub[factor].rank().corr(sub[ret].rank())
            rows.append({"date": str(date), "ic": round(float(ic), 6) if ic is not None else None})
            if ic is not None:
                ics.append(float(ic))
        icir = None
        if len(ics) >= 2:
            mean = sum(ics) / len(ics)
            std = (sum((x - mean) ** 2 for x in ics) / (len(ics) - 1)) ** 0.5
            icir = mean / std if std > 0 else None
        rows.append({"date": "__summary__", "ic": None})
        rows.append({"date": "__ic_mean__", "ic": (sum(ics) / len(ics)) if ics else None})
        rows.append({"date": "__icir__", "ic": icir})
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
        if weights_raw:
            weights = [float(w) for w in weights_raw]
            if len(weights) != len(cols):
                raise ValueError("权重数量需与因子列一致")
            total = sum(weights) or 1.0
            weights = [w / total for w in weights]
        else:
            weights = [1.0 / len(cols)] * len(cols)
        output = str(self.params.get("output") or "composite").strip() or "composite"
        norm_sum = None
        for col, w in zip(cols, weights):
            series = df[col].astype(float)
            mean, std = series.mean(), series.std(ddof=0)
            if std is None or std == 0 or std != std:
                std = 1e-12
            norm = (series - mean) / std * w
            norm_sum = norm if norm_sum is None else norm_sum + norm
        df[output] = norm_sum
        return {"table": df_to_table(df)}
