"""SQLite 持久化层（M4 起承载用户/项目/成员等业务数据）。

设计：
- 模块级 :class:`Database` 单例，RLock 串行化写操作（业务数据量小，足够）；
- WAL 模式支持并发读；`foreign_keys=ON` 保证成员表级联删除；
- 表结构幂等初始化（`CREATE TABLE IF NOT EXISTS`）；
- 路径可用环境变量 ``QF_DB_PATH`` 覆盖（生产/测试各自指定）。

V1.0 说明：工作流/运行实例仍为内存态（M1 原型定位），迁移 SQLite/Mongo 排入
V1.1；用户/项目/成员为多用户业务核心，必须先落地持久化。
"""

from __future__ import annotations

import os
import sqlite3
import threading
from typing import Any, Iterable, List, Optional

_BASE_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DEFAULT_DB_PATH = os.path.join(_BASE_DIR, "data", "quantflow.db")

_SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id            TEXT PRIMARY KEY,
    username      TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    salt          TEXT NOT NULL,
    role          TEXT NOT NULL DEFAULT 'user',
    created_at    TEXT NOT NULL,
    updated_at    TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS projects (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    owner_id    TEXT NOT NULL,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL,
    FOREIGN KEY(owner_id) REFERENCES users(id) ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS project_members (
    project_id TEXT NOT NULL,
    user_id    TEXT NOT NULL,
    role       TEXT NOT NULL DEFAULT 'member',
    created_at TEXT NOT NULL,
    PRIMARY KEY (project_id, user_id),
    FOREIGN KEY(project_id) REFERENCES projects(id) ON DELETE CASCADE,
    FOREIGN KEY(user_id)    REFERENCES users(id)    ON DELETE CASCADE
);

CREATE TABLE IF NOT EXISTS api_tokens (
    id           TEXT PRIMARY KEY,
    user_id      TEXT NOT NULL,
    name         TEXT NOT NULL,
    prefix       TEXT NOT NULL UNIQUE,
    secret_hash  TEXT NOT NULL,
    scopes       TEXT NOT NULL DEFAULT '*',
    created_at   TEXT NOT NULL,
    last_used_at TEXT,
    revoked_at   TEXT
);

CREATE TABLE IF NOT EXISTS data_updates (
    id           TEXT PRIMARY KEY,
    source       TEXT NOT NULL,
    status       TEXT NOT NULL,
    symbols      TEXT NOT NULL DEFAULT '',
    bars_written INTEGER NOT NULL DEFAULT 0,
    error        TEXT,
    started_at   TEXT NOT NULL,
    finished_at  TEXT
);

CREATE TABLE IF NOT EXISTS market_bars (
    symbol     TEXT NOT NULL,
    date       TEXT NOT NULL,
    interval   TEXT NOT NULL DEFAULT 'daily',
    open       REAL NOT NULL,
    high       REAL NOT NULL,
    low        REAL NOT NULL,
    close      REAL NOT NULL,
    volume     REAL NOT NULL DEFAULT 0,
    amount     REAL NOT NULL DEFAULT 0,
    source     TEXT NOT NULL DEFAULT '',
    adjustment TEXT NOT NULL DEFAULT 'none',
    PRIMARY KEY (symbol, date, interval)
);

CREATE TABLE IF NOT EXISTS notification_channels (
    id         TEXT PRIMARY KEY,
    type       TEXT NOT NULL,
    name       TEXT NOT NULL,
    config     TEXT NOT NULL DEFAULT '{}',
    enabled    INTEGER NOT NULL DEFAULT 1,
    created_at TEXT NOT NULL
);

-- V1.1 N6 分布式 Worker：共享运行态 + 任务队列 + 事件日志（SQLite 承载，进程间共享）
CREATE TABLE IF NOT EXISTS runs (
    run_id       TEXT PRIMARY KEY,
    workflow_id  TEXT,
    workflow_name TEXT NOT NULL DEFAULT '',
    status       TEXT NOT NULL,
    created_at   TEXT NOT NULL,
    started_at   REAL NOT NULL,
    finished_at  REAL,
    result       TEXT,
    nodes        TEXT NOT NULL DEFAULT '{}'
);

CREATE TABLE IF NOT EXISTS run_events (
    seq       INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id    TEXT NOT NULL,
    kind      TEXT NOT NULL,
    node_id   TEXT,
    payload   TEXT NOT NULL DEFAULT '{}',
    timestamp REAL NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_run_events_run ON run_events(run_id, seq);

CREATE TABLE IF NOT EXISTS run_jobs (
    id            TEXT PRIMARY KEY,
    workflow_id   TEXT,
    workflow_name TEXT NOT NULL DEFAULT '',
    payload       TEXT NOT NULL,
    status        TEXT NOT NULL DEFAULT 'queued',
    claimed_by    TEXT,
    claimed_at    REAL,
    error         TEXT,
    created_at    REAL NOT NULL,
    updated_at    REAL NOT NULL,
    priority      INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_run_jobs_status ON run_jobs(status, priority, created_at);

-- V1.2 定时调度：工作流定时执行计划
CREATE TABLE IF NOT EXISTS schedules (
    id            TEXT PRIMARY KEY,
    name          TEXT NOT NULL,
    trigger_type  TEXT NOT NULL,           -- 'cron' | 'interval'
    trigger_cfg   TEXT NOT NULL,           -- cron 表达式 或 {"minutes": N} JSON
    payload       TEXT NOT NULL,           -- {"nodes":[...],"edges":[...],"workflow_name":""}
    enabled       INTEGER NOT NULL DEFAULT 1,
    created_at    TEXT NOT NULL,
    last_run_at   TEXT,
    last_run_status TEXT,
    last_run_id   TEXT,
    next_run_at   TEXT
);

-- V1.1 N3 因子库：用户可持久化的因子定义（表达式 + 类别 + 参数），供工作流与分析复用
CREATE TABLE IF NOT EXISTS factor_library (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    category    TEXT NOT NULL DEFAULT '自定义',
    expression  TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    params      TEXT NOT NULL DEFAULT '{}',
    owner_id    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_factor_library_owner ON factor_library(owner_id);

-- V1.4 通用键值设置（用户可配置项持久化，如自定义 LLM 配置）
CREATE TABLE IF NOT EXISTS app_settings (
    key        TEXT PRIMARY KEY,
    value      TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

-- V6.1 用户级偏好（按用户隔离；整体以 JSON 持久化）
CREATE TABLE IF NOT EXISTS user_preferences (
    user_id  TEXT PRIMARY KEY,
    prefs    TEXT NOT NULL DEFAULT '{}',
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS alert_rules (
    id               TEXT PRIMARY KEY,
    name             TEXT NOT NULL,
    symbol           TEXT NOT NULL,
    metric           TEXT NOT NULL DEFAULT 'price',
    operator         TEXT NOT NULL DEFAULT '>',
    threshold        REAL NOT NULL,
    cooldown_minutes INTEGER NOT NULL DEFAULT 60,
    enabled          INTEGER NOT NULL DEFAULT 1,
    created_at       TEXT NOT NULL,
    last_triggered   TEXT,
    trigger_count    INTEGER NOT NULL DEFAULT 0
);

CREATE TABLE IF NOT EXISTS watchlists (
    symbol     TEXT PRIMARY KEY,
    added_at   TEXT NOT NULL
);

-- V3.1 个人工作流模板库（用户保存的可复用工作流，持久化，跨重启保留）
CREATE TABLE IF NOT EXISTS workflow_templates (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    nodes       TEXT NOT NULL,
    edges       TEXT NOT NULL DEFAULT '[]',
    tags        TEXT NOT NULL DEFAULT '[]',
    builtin     INTEGER NOT NULL DEFAULT 0,
    owner_id    TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_workflow_templates_owner ON workflow_templates(owner_id);
-- 注意：is_public 列及 idx_workflow_templates_public 索引由 TemplateStore._ensure()
-- 惰性补齐（ALTER TABLE ADD COLUMN），避免对「已存在旧表」重复执行 CREATE TABLE 时
-- 因列缺失导致 CREATE INDEX 失败。详见 core/template_store.py。

-- V98 报告存档（用户保存的综合/分析报告的 JSON 快照，可回看与再导出）
CREATE TABLE IF NOT EXISTS report_archive (
    id          TEXT PRIMARY KEY,
    name        TEXT NOT NULL,
    type        TEXT NOT NULL DEFAULT 'consolidate',
    content     TEXT NOT NULL,
    owner_id    TEXT,
    created_at  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_report_archive_owner ON report_archive(owner_id);

"""


class Database:
    """线程安全的 SQLite 访问封装。"""

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path or os.getenv("QF_DB_PATH", DEFAULT_DB_PATH)
        self._lock = threading.RLock()
        self._conn: Optional[sqlite3.Connection] = None

    @property
    def path(self) -> str:
        return self._path

    def _ensure(self) -> sqlite3.Connection:
        if self._conn is None:
            os.makedirs(os.path.dirname(self._path) or ".", exist_ok=True)
            self._conn = sqlite3.connect(self._path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA busy_timeout=5000")  # 多进程(worker)并发写容错
            self._conn.execute("PRAGMA foreign_keys=ON")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
        return self._conn

    def execute(self, sql: str, params: Iterable[Any] = ()) -> sqlite3.Cursor:
        with self._lock:
            cur = self._ensure().execute(sql, tuple(params))
            self._ensure().commit()
            return cur

    def executemany(self, sql: str, seq: Iterable[Iterable[Any]]) -> None:
        with self._lock:
            self._ensure().executemany(sql, (tuple(item) for item in seq))
            self._ensure().commit()

    def query(self, sql: str, params: Iterable[Any] = ()) -> List[dict]:
        with self._lock:
            rows = self._ensure().execute(sql, tuple(params)).fetchall()
            return [dict(row) for row in rows]

    def query_one(self, sql: str, params: Iterable[Any] = ()) -> Optional[dict]:
        rows = self.query(sql, params)
        return rows[0] if rows else None

    def reset(self) -> None:
        """清空全部业务表（测试用）。"""
        with self._lock:
            conn = self._ensure()
            conn.execute("DELETE FROM project_members")
            conn.execute("DELETE FROM projects")
            conn.execute("DELETE FROM users")
            conn.execute("DELETE FROM api_tokens")
            conn.execute("DELETE FROM data_updates")
            conn.execute("DELETE FROM market_bars")
            conn.execute("DELETE FROM notification_channels")
            conn.execute("DELETE FROM schedules")
            conn.execute("DELETE FROM run_events")
            conn.execute("DELETE FROM run_jobs")
            conn.execute("DELETE FROM runs")
            conn.execute("DELETE FROM app_settings")
            conn.commit()


db = Database()
