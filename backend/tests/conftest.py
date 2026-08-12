"""pytest 全局配置：隔离测试数据库并重置业务表。"""

from __future__ import annotations

import os
import tempfile

import pytest

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
