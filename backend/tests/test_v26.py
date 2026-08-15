"""V26 自定义基准持久化（无凭证）：保存 / 列举 / 读取 / 删除。"""
from __future__ import annotations

import pytest
import tempfile
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _authed_client():
    global client
    c = TestClient(app)
    c.post("/api/auth/register", json={"username": "v26_u", "password": "secret123"})
    token = c.post(
        "/api/auth/login", json={"username": "v26_u", "password": "secret123"}
    ).json()["token"]
    c.headers["Authorization"] = f"Bearer {token}"
    client = c
    yield


@pytest.fixture(autouse=True)
def _store():
    tmp = tempfile.mkdtemp(prefix="bench_v26_")
    backtest_api._benchmark_store.benchmark_dir = tmp


def test_save_then_list_benchmark():
    res = client.post("/api/backtest/benchmarks", json={
        "name": "沪深300等权篮子",
        "symbols": ["CSI300", "CSI500"],
    })
    assert res.status_code == 200, res.text
    d = res.json()
    assert d["bench_id"]
    assert d["mode"] == "basket"

    lst = client.get("/api/backtest/benchmarks").json()
    assert len(lst["items"]) == 1
    item = lst["items"][0]
    assert item["name"] == "沪深300等权篮子"
    assert item["mode"] == "basket"
    assert item["symbols"] == ["CSI300", "CSI500"]


def test_save_explicit_values():
    res = client.post("/api/backtest/benchmarks", json={
        "name": "显式序列基准",
        "values": [1.0, 1.02, 1.01, 1.05],
    })
    assert res.status_code == 200, res.text
    assert res.json()["mode"] == "explicit"


def test_save_missing_both_422():
    res = client.post("/api/backtest/benchmarks", json={"name": "空基准"})
    assert res.status_code == 422


def test_weights_length_mismatch_422():
    res = client.post("/api/backtest/benchmarks", json={
        "name": "错配权重",
        "symbols": ["A", "B", "C"],
        "weights": [0.5, 0.5],
    })
    assert res.status_code == 422


def test_get_and_delete_benchmark():
    bid = client.post("/api/backtest/benchmarks", json={
        "name": "待删基准", "symbols": ["X"],
    }).json()["bench_id"]

    got = client.get(f"/api/backtest/benchmarks/{bid}")
    assert got.status_code == 200
    assert got.json()["name"] == "待删基准"

    deleted = client.delete(f"/api/backtest/benchmarks/{bid}")
    assert deleted.status_code == 200
    assert deleted.json()["deleted"] == bid

    missing = client.get(f"/api/backtest/benchmarks/{bid}")
    assert missing.status_code == 404
    gone = client.delete(f"/api/backtest/benchmarks/{bid}")
    assert gone.status_code == 404
