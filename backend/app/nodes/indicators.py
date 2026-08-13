"""特征节点：技术指标（M3 特征节点）。

对齐开发计划 §4.3「特征节点：MA/EMA/MACD/RSI/KDJ/BOLL」。
输入为行情表（含 date + close 等数值列），输出在原表基础上追加指标列。
"""

from __future__ import annotations


from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node
from ._utils import df_to_table, require_table, table_to_df


def _price_column(df) -> str:
    for col in ("close", "Close", "收盘", "close_price"):
        if col in df.columns:
            return col
    raise ValueError("行情表缺少 close 列")


@work_node(
    "indicator.ma",
    label="均线 MA",
    category="特征",
    description="简单移动平均，输出 ma 列",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[ParamSpec("window", "number", default=20, label="周期")],
)
class MANode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        w = int(self.params["window"] or 20)
        col = _price_column(df)
        df[f"ma{w}"] = df[col].rolling(window=w, min_periods=w).mean()
        return {"table": df_to_table(df)}


@work_node(
    "indicator.ema",
    label="指数均线 EMA",
    category="特征",
    description="指数移动平均，输出 ema 列",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[ParamSpec("window", "number", default=12, label="周期")],
)
class EMANode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        w = int(self.params["window"] or 12)
        col = _price_column(df)
        df[f"ema{w}"] = df[col].ewm(span=w, adjust=False).mean()
        return {"table": df_to_table(df)}


@work_node(
    "indicator.macd",
    label="MACD",
    category="特征",
    description="MACD：DIF/DEA/HIST（12/26/9 经典参数可调）",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("fast", "number", default=12, label="快线周期"),
        ParamSpec("slow", "number", default=26, label="慢线周期"),
        ParamSpec("signal", "number", default=9, label="信号周期"),
    ],
)
class MACDNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        fast, slow, signal = int(self.params["fast"]), int(self.params["slow"]), int(self.params["signal"])
        col = _price_column(df)
        ema_fast = df[col].ewm(span=fast, adjust=False).mean()
        ema_slow = df[col].ewm(span=slow, adjust=False).mean()
        df["macd_dif"] = ema_fast - ema_slow
        df["macd_dea"] = df["macd_dif"].ewm(span=signal, adjust=False).mean()
        df["macd_hist"] = (df["macd_dif"] - df["macd_dea"]) * 2
        return {"table": df_to_table(df)}


@work_node(
    "indicator.rsi",
    label="RSI",
    category="特征",
    description="相对强弱指标（14 周期），输出 rsi 列",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[ParamSpec("window", "number", default=14, label="周期")],
)
class RSINode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        w = int(self.params["window"] or 14)
        col = _price_column(df)
        delta = df[col].diff()
        gain = delta.clip(lower=0.0)
        loss = -delta.clip(upper=0.0)
        avg_gain = gain.ewm(alpha=1.0 / w, adjust=False).mean()
        avg_loss = loss.ewm(alpha=1.0 / w, adjust=False).mean()
        rs = avg_gain / avg_loss.replace(0.0, 1e-12)
        df["rsi"] = 100.0 - 100.0 / (1.0 + rs)
        df.loc[avg_loss == 0.0, "rsi"] = 100.0
        return {"table": df_to_table(df)}


@work_node(
    "indicator.kdj",
    label="KDJ",
    category="特征",
    description="随机指标 KDJ（9/3/3），输出 k/d/j 列",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("window", "number", default=9, label="RSV 周期"),
        ParamSpec("k_smooth", "number", default=3, label="K 平滑"),
        ParamSpec("d_smooth", "number", default=3, label="D 平滑"),
    ],
)
class KDJNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        w = int(self.params["window"] or 9)
        k_smooth = int(self.params["k_smooth"] or 3)
        d_smooth = int(self.params["d_smooth"] or 3)
        low = df["low"].rolling(window=w, min_periods=1).min()
        high = df["high"].rolling(window=w, min_periods=1).max()
        rsv = (df["close"] - low) / (high - low).replace(0.0, 1e-12) * 100.0
        k = rsv.ewm(alpha=1.0 / k_smooth, adjust=False).mean()
        d = k.ewm(alpha=1.0 / d_smooth, adjust=False).mean()
        df["kdj_k"] = k
        df["kdj_d"] = d
        df["kdj_j"] = 3.0 * k - 2.0 * d
        return {"table": df_to_table(df)}


@work_node(
    "indicator.boll",
    label="布林带 BOLL",
    category="特征",
    description="布林带：中轨 MA、上下轨 ±k 倍标准差，输出 boll_mid/up/low",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("window", "number", default=20, label="周期"),
        ParamSpec("num_std", "number", default=2.0, label="标准差倍数"),
    ],
)
class BOLLNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        df = table_to_df(require_table(inputs["table"])).copy()
        w = int(self.params["window"] or 20)
        k = float(self.params.get("num_std") or 2.0)
        col = _price_column(df)
        mid = df[col].rolling(window=w, min_periods=w).mean()
        std = df[col].rolling(window=w, min_periods=w).std(ddof=0)
        df["boll_mid"] = mid
        df["boll_up"] = mid + k * std
        df["boll_low"] = mid - k * std
        return {"table": df_to_table(df)}
