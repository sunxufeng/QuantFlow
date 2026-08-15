"""ML 量化分析：收益预测 / 聚类选股 / 异常检测 / 特征重要性 / 特征工程。

纯函数实现，供 API 层与单测复用。不依赖工作流节点（nodes/ml_nodes.py），
面向量化研究者的交互式分析端点。
"""
from __future__ import annotations

import math
from typing import List, Optional, Dict, Any

import numpy as np


def _safe_array(x, name: str) -> np.ndarray:
    arr = np.asarray(x, dtype=float)
    if arr.size == 0:
        raise ValueError(f"{name} 为空")
    return arr


def _r2(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    ss_res = float(np.sum((y_true - y_pred) ** 2))
    ss_tot = float(np.sum((y_true - y_true.mean()) ** 2))
    if ss_tot < 1e-12:
        return 0.0
    return float(1.0 - ss_res / ss_tot)


def _ic(y_true: np.ndarray, y_pred: np.ndarray) -> float:
    y_true = np.asarray(y_true, dtype=float)
    y_pred = np.asarray(y_pred, dtype=float)
    if len(y_true) < 2:
        return 0.0
    std_t = y_true.std(ddof=0)
    std_p = y_pred.std(ddof=0)
    if std_t < 1e-12 or std_p < 1e-12:
        return 0.0
    return float(np.corrcoef(y_true, y_pred)[0, 1])


def predict_returns(
    features: List[List[float]],
    targets: List[float],
    method: str = "ridge",
    test_size: float = 0.3,
    seed: int = 42,
    feature_names: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """时序收益预测基线模型（OLS / Ridge / Lasso）。

    按时间顺序切分训练/测试（不洗牌，避免前视），返回样本外 R²、IC、系数与
    样本外预测值。
    """
    X = _safe_array(features, "features")
    y = _safe_array(targets, "targets")
    if X.ndim != 2 or y.ndim != 1 or X.shape[0] != y.shape[0]:
        raise ValueError("features 须为 (n, k) 矩阵，targets 长度须一致")
    n, k = X.shape
    if n < 10:
        raise ValueError("样本数须 >= 10")
    method = (method or "ridge").lower()
    if method not in ("ols", "ridge", "lasso"):
        raise ValueError("method 须为 ols/ridge/lasso")

    from sklearn.linear_model import LinearRegression, Ridge, Lasso

    rng = np.random.default_rng(seed)
    n_test = max(1, int(round(n * test_size)))
    n_test = min(n_test, n - 1)
    cut = n - n_test
    Xtr, Xte = X[:cut], X[cut:]
    ytr, yte = y[:cut], y[cut:]

    if method == "ols":
        model = LinearRegression()
    elif method == "ridge":
        model = Ridge(alpha=1.0, random_state=int(rng.integers(1e6)))
    else:
        model = Lasso(alpha=0.01, random_state=int(rng.integers(1e6)), max_iter=5000)
    model.fit(Xtr, ytr)
    pred_tr = model.predict(Xtr)
    pred_te = model.predict(Xte)
    coef = [float(c) for c in model.coef_]
    names = feature_names or [f"f{i}" for i in range(k)]

    if method == "lasso":
        nonzero = int(sum(1 for c in coef if abs(c) > 1e-6))
    else:
        nonzero = k

    return {
        "method": method,
        "n_train": int(cut),
        "n_test": int(n_test),
        "train_r2": round(_r2(ytr, pred_tr), 4),
        "test_r2": round(_r2(yte, pred_te), 4),
        "test_ic": round(_ic(yte, pred_te), 4),
        "coefficients": coef,
        "feature_names": names,
        "nonzero_coef": nonzero,
        "test_predictions": [round(float(p), 6) for p in pred_te],
        "test_actual": [round(float(v), 6) for v in yte],
    }


def cluster_stocks(
    features: List[List[float]],
    names: Optional[List[str]] = None,
    n_clusters: int = 3,
    seed: int = 42,
) -> Dict[str, Any]:
    """基于特征的 KMeans 聚类选股。

    返回簇标签、簇内样本数、每簇特征均值，以及最接近簇心的代表性标的
    （选股候选）。
    """
    X = _safe_array(features, "features")
    if X.ndim != 2:
        raise ValueError("features 须为 (n, k) 矩阵")
    n, k = X.shape
    if n < 2:
        raise ValueError("样本数须 >= 2")
    n_clusters = max(1, min(int(n_clusters), n))
    names = names or [str(i) for i in range(n)]

    from sklearn.cluster import KMeans

    km = KMeans(n_clusters=n_clusters, random_state=int(seed), n_init=10)
    labels = km.fit_predict(X)
    centers = km.cluster_centers_

    clusters: Dict[str, Any] = {}
    representatives: List[str] = []
    for c in range(n_clusters):
        idx = [i for i in range(n) if int(labels[i]) == c]
        if not idx:
            continue
        sub = X[idx]
        # 距簇心最近的样本作为代表
        d = np.linalg.norm(sub - centers[c], axis=1)
        rep_local = int(np.argmin(d))
        rep = names[idx[rep_local]]
        representatives.append(rep)
        clusters[str(c)] = {
            "size": len(idx),
            "members": [names[i] for i in idx],
            "center": [round(float(v), 4) for v in centers[c]],
            "representative": rep,
        }
    return {
        "n_clusters": n_clusters,
        "inertia": round(float(km.inertia_), 4),
        "labels": [int(l) for l in labels],
        "names": names,
        "clusters": clusters,
        "representatives": representatives,
    }


def detect_anomalies(
    series: List[float],
    method: str = "zscore",
    threshold: float = 3.0,
    dates: Optional[List[str]] = None,
    contamination: float = 0.05,
) -> Dict[str, Any]:
    """收益率序列异常检测。

    - zscore：标准 Z 分数（|z| > threshold 判异常）
    - robust：中位数/MAD 稳健 Z（抗离群）
    - isolation：IsolationForest 无监督异常
    返回每个样本的分数与异常标记、异常索引、异常日期。
    """
    s = _safe_array(series, "series").ravel()
    n = len(s)
    if n < 5:
        raise ValueError("序列长度须 >= 5")
    method = (method or "zscore").lower()
    scores = np.zeros(n)
    is_anom = np.zeros(n, dtype=bool)

    if method == "robust":
        med = float(np.median(s))
        mad = float(np.median(np.abs(s - med)))
        scale = mad * 1.4826 if mad > 1e-12 else (s.std(ddof=0) + 1e-12)
        scores = (s - med) / scale
        is_anom = np.abs(scores) > threshold
    elif method == "isolation":
        from sklearn.ensemble import IsolationForest

        X = s.reshape(-1, 1)
        iso = IsolationForest(contamination=contamination, random_state=42)
        iso.fit(X)
        raw = iso.decision_function(X)  # 越大越正常
        scores = -raw  # 越大越异常
        pred = iso.predict(X)  # -1 异常
        is_anom = pred == -1
    else:  # zscore
        mu = float(s.mean())
        sd = float(s.std(ddof=0)) + 1e-12
        scores = (s - mu) / sd
        is_anom = np.abs(scores) > threshold

    anom_idx = [int(i) for i in np.where(is_anom)[0]]
    anom_dates = None
    if dates:
        anom_dates = [dates[i] for i in anom_idx if i < len(dates)]
    return {
        "method": method,
        "threshold": threshold,
        "scores": [round(float(v), 4) for v in scores],
        "is_anomaly": [bool(b) for b in is_anom],
        "n_anomalies": int(is_anom.sum()),
        "anomaly_indices": anom_idx,
        "anomaly_dates": anom_dates,
    }


def feature_importance(
    features: List[List[float]],
    targets: List[float],
    feature_names: Optional[List[str]] = None,
    method: str = "permutation",
    seed: int = 42,
) -> Dict[str, Any]:
    """特征重要性（排列重要性 / 相关性）。

    排列重要性：对每一列做随机打乱后，Ridge 模型 R² 的下降量即重要性。
    """
    X = _safe_array(features, "features")
    y = _safe_array(targets, "targets")
    if X.ndim != 2 or X.shape[0] != len(y):
        raise ValueError("features/targets 维度不匹配")
    n, k = X.shape
    if n < 10:
        raise ValueError("样本数须 >= 10")
    names = feature_names or [f"f{i}" for i in range(k)]
    method = (method or "permutation").lower()

    from sklearn.linear_model import Ridge

    base = Ridge(alpha=1.0, random_state=int(seed))
    base.fit(X, y)
    base_r2 = _r2(y, base.predict(X))

    if method == "correlation":
        imp = np.array([
            abs(_ic(y, X[:, j])) for j in range(k)
        ])
    else:  # permutation
        rng = np.random.default_rng(seed)
        imp = np.zeros(k)
        for j in range(k):
            drops = []
            for _ in range(5):
                Xp = X.copy()
                perm = rng.permutation(Xp[:, j])
                Xp[:, j] = perm
                drops.append(base_r2 - _r2(y, base.predict(Xp)))
            imp[j] = float(np.mean(drops))

    order = np.argsort(imp)[::-1]
    total = float(imp.sum()) + 1e-12
    ranked = [
        {
            "feature": names[int(i)],
            "importance": round(float(imp[int(i)]), 6),
            "relative": round(float(imp[int(i)]) / total, 4),
        }
        for i in order
    ]
    return {
        "method": method,
        "base_r2": round(float(base_r2), 4),
        "ranked": ranked,
        "top_features": [names[int(i)] for i in order[: min(5, k)]],
    }


def build_features(
    prices: List[float],
    windows: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """由价格序列构造常用 ML 特征矩阵。

    含：对数收益、滚动波动率(多窗口)、动量(多窗口)、RSI、乖离率(Z-score)。
    返回特征名与 (n-warmup) x k 特征矩阵。
    """
    p = _safe_array(prices, "prices").ravel()
    if len(p) < 30:
        raise ValueError("价格长度须 >= 30")
    windows = windows or [5, 10, 20]
    ret = np.diff(np.log(p))
    n = len(ret)
    cols: List[np.ndarray] = []
    names: List[str] = []

    cols.append(ret)
    names.append("log_ret")

    for w in windows:
        if w < 2 or w >= n:
            continue
        vol = np.array([
            float(np.std(ret[max(0, i - w + 1): i + 1], ddof=0)) for i in range(n)
        ])
        cols.append(vol)
        names.append(f"vol_{w}")
        mom = np.array([float(p[i + 1] / p[max(0, i + 1 - w)] - 1.0) for i in range(n)])
        cols.append(mom)
        names.append(f"mom_{w}")

    # RSI(14)
    w = 14
    if n > w:
        gains = np.where(ret > 0, ret, 0.0)
        losses = np.where(ret < 0, -ret, 0.0)
        rsi = np.zeros(n)
        for i in range(n):
            ag = gains[max(0, i - w + 1): i + 1].mean()
            al = losses[max(0, i - w + 1): i + 1].mean()
            rsi[i] = 100.0 - 100.0 / (1.0 + (ag / (al + 1e-12)))
        cols.append(rsi / 100.0)
        names.append("rsi_14")

    # 价格乖离 Z-score(20)
    wz = 20
    if n > wz:
        z = np.array([
            float((p[i] - p[max(0, i - wz): i + 1].mean()) / (p[max(0, i - wz): i + 1].std(ddof=0) + 1e-12))
            for i in range(1, len(p))
        ])
        cols.append(z)
        names.append("zscore_20")

    M = np.column_stack(cols)  # (n, k)
    mask = ~np.isnan(M).any(axis=1)
    M = M[mask]
    return {
        "feature_names": names,
        "n_features": len(names),
        "n_samples": int(M.shape[0]),
        "matrix": [[round(float(v), 6) for v in row] for row in M],
    }


__all__ = [
    "predict_returns",
    "cluster_stocks",
    "detect_anomalies",
    "feature_importance",
    "build_features",
]
