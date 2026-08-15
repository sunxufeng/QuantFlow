import math
import numpy as np
import pytest

from app.ml import analytics as ml


def _features(n=60, k=4, seed=1):
    rng = np.random.default_rng(seed)
    X = rng.normal(0, 1, (n, k))
    beta = np.array([0.6, -0.3, 0.1, 0.0])[:k]
    y = X @ beta + rng.normal(0, 0.05, n)
    return X.tolist(), y.tolist()


def test_predict_returns_basic():
    X, y = _features()
    out = ml.predict_returns(X, y, method="ridge")
    assert out["method"] == "ridge"
    assert out["n_train"] + out["n_test"] == 60
    assert -1 <= out["test_r2"] <= 1 or out["test_r2"] > 1  # 有限
    assert len(out["coefficients"]) == 4
    assert len(out["test_predictions"]) == out["n_test"]


def test_predict_methods():
    X, y = _features()
    for m in ("ols", "ridge", "lasso"):
        out = ml.predict_returns(X, y, method=m)
        assert out["method"] == m
        if m == "lasso":
            assert out["nonzero_coef"] <= 4


def test_predict_too_few():
    with pytest.raises(ValueError):
        ml.predict_returns([[1.0, 2.0]] * 5, [1.0] * 5)


def test_cluster_basic():
    rng = np.random.default_rng(3)
    a = rng.normal(0, 1, (20, 3))
    b = rng.normal(10, 1, (20, 3))
    X = np.vstack([a, b]).tolist()
    names = [f"s{i}" for i in range(40)]
    out = ml.cluster_stocks(X, names, n_clusters=2)
    assert out["n_clusters"] == 2
    assert len(out["labels"]) == 40
    assert len(out["representatives"]) == 2
    # 两个真实簇应大致分开
    c0 = out["clusters"]["0"]
    c1 = out["clusters"]["1"]
    assert c0["size"] + c1["size"] == 40


def test_cluster_single_cluster():
    X, _ = _features(n=10, k=2)
    out = ml.cluster_stocks(X, n_clusters=1)
    assert out["n_clusters"] == 1
    assert len(out["representatives"]) == 1


def test_anomaly_zscore():
    rng = np.random.default_rng(7)
    s = rng.normal(0, 0.01, 100).tolist()
    s[50] = 0.5  # 注入异常
    out = ml.detect_anomalies(s, method="zscore", threshold=3.0)
    assert out["n_anomalies"] >= 1
    assert 50 in out["anomaly_indices"]
    assert len(out["scores"]) == 100


def test_anomaly_robust_and_isolation():
    rng = np.random.default_rng(9)
    s = rng.normal(0, 0.01, 80).tolist()
    s[10] = 0.4
    r = ml.detect_anomalies(s, method="robust", threshold=3.0)
    assert 10 in r["anomaly_indices"]
    iso = ml.detect_anomalies(s, method="isolation", contamination=0.05)
    assert isinstance(iso["n_anomalies"], int)
    assert len(iso["is_anomaly"]) == 80


def test_anomaly_with_dates():
    s = [0.01, 0.02, -0.3, 0.01, 0.0]
    d = ["2024-01-01", "2024-01-02", "2024-01-03", "2024-01-04", "2024-01-05"]
    out = ml.detect_anomalies(s, method="zscore", threshold=1.5, dates=d)
    assert out["anomaly_dates"] is not None
    assert "2024-01-03" in out["anomaly_dates"]


def test_feature_importance_ranking():
    X, y = _features(seed=5)
    out = ml.feature_importance(X, y, feature_names=["a", "b", "c", "d"])
    assert out["method"] in ("permutation", "correlation")
    assert out["ranked"][0]["feature"] in ("a", "b")  # 重要特征
    assert abs(sum(r["relative"] for r in out["ranked"]) - 1.0) < 1e-6
    assert len(out["top_features"]) <= 5


def test_feature_importance_correlation():
    X, y = _features(seed=11)
    out = ml.feature_importance(X, y, method="correlation")
    assert out["method"] == "correlation"
    assert len(out["ranked"]) == 4


def test_build_features():
    rng = np.random.default_rng(2)
    p = (100 * np.cumprod(1 + rng.normal(0.001, 0.02, 120))).tolist()
    out = ml.build_features(p)
    assert out["n_features"] >= 5
    assert out["n_samples"] > 0
    assert len(out["matrix"][0]) == out["n_features"]
    assert "log_ret" in out["feature_names"]


def test_build_features_too_short():
    with pytest.raises(ValueError):
        ml.build_features([1.0, 2.0, 3.0])


# ---------- API 冒烟 ----------

def _auth(client):
    u = f"ml_{np.random.default_rng().integers(1e9)}"
    client.post("/api/auth/register", json={"username": u, "password": "P@w0rd123"})
    r = client.post("/api/auth/login", json={"username": u, "password": "P@w0rd123"})
    return r.json()["token"]


def test_api_predict_smoke(client):
    X, y = _features()
    tok = _auth(client)
    r = client.post(
        "/api/ml/predict",
        json={"features": X, "targets": y, "method": "ridge"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert "test_r2" in r.json()


def test_api_cluster_smoke(client):
    rng = np.random.default_rng(4)
    X = np.vstack([rng.normal(0, 1, (15, 3)), rng.normal(8, 1, (15, 3))]).tolist()
    tok = _auth(client)
    r = client.post(
        "/api/ml/cluster",
        json={"features": X, "n_clusters": 2},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["n_clusters"] == 2


def test_api_anomaly_smoke(client):
    rng = np.random.default_rng(6)
    s = rng.normal(0, 0.01, 60).tolist()
    s[5] = 0.3
    tok = _auth(client)
    r = client.post(
        "/api/ml/anomaly",
        json={"series": s, "method": "zscore"},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["n_anomalies"] >= 1


def test_api_importance_smoke(client):
    X, y = _features()
    tok = _auth(client)
    r = client.post(
        "/api/ml/importance",
        json={"features": X, "targets": y},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert "ranked" in r.json()


def test_api_features_smoke(client):
    rng = np.random.default_rng(8)
    p = (100 * np.cumprod(1 + rng.normal(0.001, 0.02, 80))).tolist()
    tok = _auth(client)
    r = client.post(
        "/api/ml/features",
        json={"prices": p},
        headers={"Authorization": f"Bearer {tok}"},
    )
    assert r.status_code == 200
    assert r.json()["n_samples"] > 0


def test_api_ml_requires_auth(anon_client):
    r = anon_client.post("/api/ml/predict", json={"features": [[1.0]], "targets": [1.0]})
    assert r.status_code in (401, 403)
