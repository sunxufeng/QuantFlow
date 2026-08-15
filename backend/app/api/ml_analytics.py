"""ML 量化分析 API 端点（/api/ml/*）。"""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from ..core.auth import get_current_user
from app.ml import analytics as ml

router = APIRouter()


class PredictReq(BaseModel):
    features: List[List[float]]
    targets: List[float]
    method: str = "ridge"
    test_size: float = 0.3
    seed: int = 42
    feature_names: Optional[List[str]] = None


class ClusterReq(BaseModel):
    features: List[List[float]]
    names: Optional[List[str]] = None
    n_clusters: int = 3
    seed: int = 42


class AnomalyReq(BaseModel):
    series: List[float]
    method: str = "zscore"
    threshold: float = 3.0
    dates: Optional[List[str]] = None
    contamination: float = 0.05


class ImportanceReq(BaseModel):
    features: List[List[float]]
    targets: List[float]
    feature_names: Optional[List[str]] = None
    method: str = "permutation"
    seed: int = 42


class FeaturesReq(BaseModel):
    prices: List[float]
    windows: Optional[List[int]] = None


@router.post("/ml/predict")
def api_predict(req: PredictReq, _: str = Depends(get_current_user)):
    try:
        return ml.predict_returns(
            req.features, req.targets, req.method, req.test_size, req.seed, req.feature_names
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ml/cluster")
def api_cluster(req: ClusterReq, _: str = Depends(get_current_user)):
    try:
        return ml.cluster_stocks(req.features, req.names, req.n_clusters, req.seed)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ml/anomaly")
def api_anomaly(req: AnomalyReq, _: str = Depends(get_current_user)):
    try:
        return ml.detect_anomalies(
            req.series, req.method, req.threshold, req.dates, req.contamination
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ml/importance")
def api_importance(req: ImportanceReq, _: str = Depends(get_current_user)):
    try:
        return ml.feature_importance(
            req.features, req.targets, req.feature_names, req.method, req.seed
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.post("/ml/features")
def api_features(req: FeaturesReq, _: str = Depends(get_current_user)):
    try:
        return ml.build_features(req.prices, req.windows)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
