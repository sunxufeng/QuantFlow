"""ML 节点：训练、预测、评估、模型持久化（M3 ML 节点）。

对齐开发计划 §4.3「ML 节点：XGBoost/LightGBM/RF/SVR/MLP 训练+预测」、
「ML 评估节点 + 模型持久化」。

设计说明：
- 模型经 base64(pickle) 编码为字符串在 ``model`` 端口传递，JSON 可序列化，
  兼容跨节点/落库/前端预览，预测/评估节点消费同字符串。
- ``ml.save_model`` 将模型 pickle 落盘（backend/data/models/），
  ``ml.load_model`` 从盘加载，实现跨 run 复用。
"""

from __future__ import annotations

import base64
import os
import pickle
import uuid
from typing import Any, Dict

from ..core.data import DataTable
from ..core.node import BaseWorkNode, ParamSpec, PortSpec, work_node
from ._utils import df_to_table, require_table, table_to_df

MODEL_REGISTRY = {
    "xgboost": "XGBRegressor",
    "lightgbm": "LGBMRegressor",
    "random_forest": "RandomForestRegressor",
    "svr": "SVR",
    "mlp": "MLPRegressor",
}


def _encode_model(model) -> str:
    """模型 -> base64 pickle 字符串（JSON 安全）。"""
    return base64.b64encode(pickle.dumps(model)).decode("ascii")


def _decode_model(payload: str):
    """base64 pickle 字符串 -> 模型对象。"""
    return pickle.loads(base64.b64decode(payload))


def _model_dir() -> str:
    base = os.environ.get("QF_DATA_DIR", os.path.join(os.path.dirname(__file__), "..", "..", "data"))
    d = os.path.join(base, "models")
    os.makedirs(d, exist_ok=True)
    return d


def _build_model(model_type: str, **kwargs):
    from sklearn.ensemble import RandomForestRegressor
    from sklearn.neural_network import MLPRegressor
    from sklearn.svm import SVR

    mt = str(model_type).strip().lower()
    if mt == "xgboost":
        from xgboost import XGBRegressor

        return XGBRegressor(n_estimators=int(kwargs.get("n_estimators", 100)), random_state=42)
    if mt == "lightgbm":
        from lightgbm import LGBMRegressor

        return LGBMRegressor(n_estimators=int(kwargs.get("n_estimators", 100)), random_state=42, verbose=-1)
    if mt == "random_forest":
        return RandomForestRegressor(n_estimators=int(kwargs.get("n_estimators", 100)), random_state=42)
    if mt == "svr":
        return SVR(C=float(kwargs.get("C", 1.0)))
    if mt == "mlp":
        hidden = int(kwargs.get("hidden_units", 64))
        return MLPRegressor(hidden_layer_sizes=(hidden,), max_iter=int(kwargs.get("max_iter", 500)), random_state=42)
    raise ValueError(f"未知模型类型: {model_type}（支持 {sorted(MODEL_REGISTRY)}）")


@work_node(
    "ml.train",
    label="模型训练",
    category="ML",
    description="用特征列预测目标列，训练回归模型（XGBoost/LightGBM/RF/SVR/MLP），输出模型与评估指标",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("model", "string", label="模型"), PortSpec("metrics", "table", label="评估指标")],
    params=[
        ParamSpec("model_type", "string", default="random_forest", label="模型",
                  options=sorted(MODEL_REGISTRY.keys())),
        ParamSpec("feature_columns", "string", default="", label="特征列（逗号分隔，空=除目标列外全部数值列）"),
        ParamSpec("target_column", "string", default="close", label="目标列"),
        ParamSpec("test_size", "number", default=0.2, label="测试集比例"),
        ParamSpec("n_estimators", "number", default=100, label="树数量（RF/GBDT）"),
    ],
)
class TrainNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score
        from sklearn.model_selection import train_test_split

        df = table_to_df(require_table(inputs["table"])).dropna()
        target = str(self.params["target_column"]).strip()
        if target not in df.columns:
            raise ValueError(f"目标列不存在: {target}")
        feat_raw = [c.strip() for c in str(self.params.get("feature_columns") or "").split(",") if c.strip()]
        if feat_raw:
            features = [c for c in feat_raw if c in df.columns]
            missing = set(feat_raw) - set(features)
            if missing:
                raise ValueError(f"特征列不存在: {sorted(missing)}")
        else:
            features = [c for c in df.columns if c != target and _is_numeric(df[c])]
        if not features:
            raise ValueError("没有可用特征列")
        X, y = df[features].astype(float), df[target].astype(float)
        test_size = min(max(float(self.params.get("test_size") or 0.2), 0.05), 0.5)
        n_samples = max(int(len(X) * test_size), 1)
        n_train = len(X) - n_samples
        X_train, X_test = X.iloc[:n_train], X.iloc[n_train:]
        y_train, y_test = y.iloc[:n_train], y.iloc[n_train:]
        model = _build_model(
            self.params["model_type"],
            n_estimators=self.params.get("n_estimators", 100),
        )
        model.fit(X_train, y_train)
        pred = model.predict(X_test)
        y_true = y_test.tolist()
        mse = mean_squared_error(y_true, pred)
        metrics = DataTable(
            columns=["metric", "value"],
            rows=[
                {"metric": "model_type", "value": self.params["model_type"]},
                {"metric": "features", "value": ",".join(features)},
                {"metric": "target", "value": target},
                {"metric": "train_samples", "value": int(len(X_train))},
                {"metric": "test_samples", "value": int(len(X_test))},
                {"metric": "mse", "value": round(float(mse), 6)},
                {"metric": "rmse", "value": round(float(mse ** 0.5), 6)},
                {"metric": "mae", "value": round(float(mean_absolute_error(y_true, pred)), 6)},
                {"metric": "r2", "value": round(float(r2_score(y_true, pred)), 6)},
            ],
        )
        return {"model": _encode_model(model), "metrics": metrics}


@work_node(
    "ml.predict",
    label="模型预测",
    category="ML",
    description="用已训练模型对特征表做预测，追加 prediction 列",
    inputs=[
        PortSpec("model", "string", label="模型"),
        PortSpec("table", "table", label="特征表"),
    ],
    outputs=[PortSpec("table", "table")],
    params=[
        ParamSpec("output", "string", default="prediction", label="预测列名"),
        ParamSpec("feature_columns", "string", default="", label="特征列（逗号分隔，空=全部数值列）"),
    ],
)
class PredictNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        model = inputs.get("model")
        if model is None:
            raise ValueError("缺少模型输入")
        model = _decode_model(model)
        df = table_to_df(require_table(inputs["table"])).copy()
        feat_raw = [c.strip() for c in str(self.params.get("feature_columns") or "").split(",") if c.strip()]
        numeric_cols = [c for c in df.columns if _is_numeric(df[c])]
        features = [c for c in (feat_raw or numeric_cols) if c in df.columns]
        if not features:
            raise ValueError("预测表没有数值特征列")
        pred = model.predict(df[features].astype(float))
        output = str(self.params.get("output") or "prediction").strip() or "prediction"
        df[output] = [float(x) for x in pred]
        return {"table": df_to_table(df)}


@work_node(
    "ml.evaluate",
    label="模型评估",
    category="ML",
    description="对比真实值与预测值，输出回归评估指标表",
    inputs=[PortSpec("table", "table")],
    outputs=[PortSpec("metrics", "table")],
    params=[
        ParamSpec("target", "string", default="close", label="真实值列"),
        ParamSpec("prediction", "string", default="prediction", label="预测值列"),
    ],
)
class EvaluateNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score

        df = table_to_df(require_table(inputs["table"])).dropna()
        target = str(self.params["target"]).strip()
        pred = str(self.params["prediction"]).strip()
        for col in (target, pred):
            if col not in df.columns:
                raise ValueError(f"缺少列: {col}")
        y_true, y_hat = df[target].astype(float).tolist(), df[pred].astype(float).tolist()
        mse = mean_squared_error(y_true, y_hat)
        rows = [
            {"metric": "samples", "value": int(len(y_true))},
            {"metric": "mse", "value": round(float(mse), 6)},
            {"metric": "rmse", "value": round(float(mse ** 0.5), 6)},
            {"metric": "mae", "value": round(float(mean_absolute_error(y_true, y_hat)), 6)},
            {"metric": "r2", "value": round(float(r2_score(y_true, y_hat)), 6)},
        ]
        return {"metrics": DataTable(columns=["metric", "value"], rows=rows)}


@work_node(
    "ml.save_model",
    label="模型持久化",
    category="ML",
    description="将训练好的模型 pickle 落盘，返回模型 ID（跨 run 复用）",
    inputs=[PortSpec("model", "string", label="模型")],
    outputs=[PortSpec("model_id", "string", label="模型 ID")],
)
class SaveModelNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        model = inputs.get("model")
        if model is None:
            raise ValueError("缺少模型输入")
        model = _decode_model(model)
        model_id = "model_" + uuid.uuid4().hex[:12]
        path = os.path.join(_model_dir(), f"{model_id}.pkl")
        with open(path, "wb") as f:
            pickle.dump(model, f)
        return {"model_id": model_id}


@work_node(
    "ml.load_model",
    label="模型加载",
    category="ML",
    description="按模型 ID 从磁盘加载模型",
    inputs=[],
    outputs=[PortSpec("model", "string", label="模型")],
    params=[ParamSpec("model_id", "string", required=True, label="模型 ID")],
)
class LoadModelNode(BaseWorkNode):
    def execute(self, ctx, inputs):
        model_id = str(self.params["model_id"]).strip()
        path = os.path.join(_model_dir(), f"{model_id}.pkl")
        if not os.path.exists(path):
            raise ValueError(f"模型不存在: {model_id}")
        with open(path, "rb") as f:
            return {"model": _encode_model(pickle.load(f))}


def _is_numeric(series) -> bool:
    import pandas as pd

    return pd.api.types.is_numeric_dtype(series)
