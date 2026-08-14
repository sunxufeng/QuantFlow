"""pytest 全局配置：隔离测试数据库并重置业务表。"""

from __future__ import annotations

import os
import tempfile
import time

import pytest
from fastapi.testclient import TestClient

_TMP_DIR = tempfile.mkdtemp(prefix="qf_test_")
os.environ.setdefault("QF_DB_PATH", os.path.join(_TMP_DIR, "test_quantflow.db"))
os.environ.setdefault("QF_MARKET_PROVIDER", "fixture")
os.environ["QF_DISABLE_SCHEDULER"] = "1"


@pytest.fixture(autouse=True)
def clean_db():
    """每个用例前清空业务表与日志缓冲，保证用例相互独立。"""
    from app.core.db import db
    from app.core.logging_store import LOG_STORE

    db.reset()
    LOG_STORE._records.clear()
    yield
    db.reset()
    LOG_STORE._records.clear()


@pytest.fixture
def client():
    """已注册并登录的鉴权客户端（带 Bearer 头）。

    V1.7 起主读接口均要求登录，故默认 client 自带合法令牌；
    需断言「未登录返回 401」的测试请改用 ``anon_client``。
    """
    from app.main import app

    with TestClient(app) as c:
        username = f"t_{int(time.time() * 1000)}_{os.getpid()}"
        password = "Test@123"
        c.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        resp = c.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        token = resp.json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c


@pytest.fixture
def anon_client():
    """未认证客户端：用于验证「未登录返回 401」的断言。"""
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def auth_client():
    """已注册并登录的鉴权客户端（带 Bearer 头）。"""
    from app.main import app

    with TestClient(app) as c:
        username = f"t_{int(time.time() * 1000)}_{os.getpid()}"
        password = "Test@123"
        c.post(
            "/api/auth/register",
            json={"username": username, "password": password},
        )
        resp = c.post(
            "/api/auth/login",
            json={"username": username, "password": password},
        )
        token = resp.json()["token"]
        c.headers["Authorization"] = f"Bearer {token}"
        yield c
