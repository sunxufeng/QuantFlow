"""行情数据自动更新调度器（V1.1 N4）。

目标：按配置周期从数据源拉取行情并 upsert 落库（SQLite），并记录每次更新的
状态（最近运行时间 / 状态 / 写入条数 / 错误），前端与监控可查。

设计要点：
- 复用 :data:`app.market.service.market_service` 的统一入口，落库由
  :class:`SQLiteMarketDataRepository` 完成（增量 upsert）；
- 数据源通过 ``QF_MARKET_PROVIDER`` 选择（演示 fixture / 生产 tushare），
  调度器本身与具体源解耦，生产只需配置授权即可启用；
- 同步窗口由 ``QF_DATA_SYNC_START`` / ``QF_DATA_SYNC_END`` 控制，
  缺省回退到内置数据的可用区间；生产可按需设为滚动窗口；
- 进程内 ``BackgroundScheduler``；多实例横向扩展属于 N6（分布式 Worker）。
"""

from __future__ import annotations

import logging
import os
import uuid
from datetime import datetime, timezone
from typing import Dict, Optional

from apscheduler.schedulers.background import BackgroundScheduler

from ..core.db import db
from .service import DEFAULT_END, DEFAULT_START, market_service

logger = logging.getLogger("quantflow.market.sync")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DataSyncService:
    """行情同步调度与状态记录。"""

    def __init__(self, service=None) -> None:
        self.service = service or market_service
        self._scheduler: Optional[BackgroundScheduler] = None
        self._latest: Optional[Dict] = None

    def _window(self) -> tuple[str, str]:
        """增量窗口：

        - 若显式设置了 ``QF_DATA_SYNC_START`` / ``QF_DATA_SYNC_END``，优先使用（全量/回补场景）；
        - 否则走增量：``start`` 取「已落库最新日 + 1 天」，避免每次重拉整段历史，
          仅拉取上次同步之后产生的新行情；``end`` 缺省回退到内置数据可用区间上界。
        """
        end = os.getenv("QF_DATA_SYNC_END") or DEFAULT_END
        explicit_start = os.getenv("QF_DATA_SYNC_START")
        if explicit_start:
            return explicit_start, end
        latest = self.service.repository.latest_date("daily")
        if latest:
            # 仅续拉最新日之后的新数据（日期字符串可比较：YYYY-MM-DD）
            start = self._next_day(latest)
        else:
            start = DEFAULT_START
        return start, end

    @staticmethod
    def _next_day(date_str: str) -> str:
        from datetime import timedelta

        d = datetime.strptime(date_str, "%Y-%m-%d") + timedelta(days=1)
        return d.strftime("%Y-%m-%d")

    def run_once(self) -> Dict:
        """手动/定时触发一次同步，返回本次运行记录。

        增量语义：窗口内若无新数据（start > end），直接记 success 且
        ``bars_written=0``，不回源、不重复写入。
        """
        start, end = self._window()
        before = self.service.repository.count()
        symbols = [i.symbol for i in self.service.instruments()]
        status = "success"
        error: Optional[str] = None
        started_at = _utc_now()
        try:
            if start <= end:
                for sym in symbols:
                    # use_cache=False 强制回源，确保增量更新生效
                    self.service.bars(sym, start=start, end=end, use_cache=False)
            else:
                logger.info("增量窗口无新数据（start=%s > end=%s），跳过回源", start, end)
        except Exception as exc:  # pragma: no cover - 取决于数据源可用性
            status = "failed"
            error = str(exc)
            logger.exception("行情同步失败：%s", exc)
        after = self.service.repository.count()
        bars_written = max(0, after - before)
        finished_at = _utc_now()
        rec = {
            "id": f"du_{uuid.uuid4().hex[:12]}",
            "source": self.service.primary.name,
            "status": status,
            "symbols": ",".join(symbols),
            "bars_written": bars_written,
            "error": error,
            "started_at": started_at,
            "finished_at": finished_at,
            "stored_bars": after,
        }
        db.execute(
            "INSERT INTO data_updates "
            "(id, source, status, symbols, bars_written, error, started_at, finished_at) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                rec["id"],
                rec["source"],
                rec["status"],
                rec["symbols"],
                rec["bars_written"],
                rec["error"],
                rec["started_at"],
                rec["finished_at"],
            ),
        )
        self._latest = rec
        logger.info(
            "行情同步完成：source=%s status=%s symbols=%d bars_written=%d",
            rec["source"],
            rec["status"],
            len(symbols),
            rec["bars_written"],
        )
        return rec

    def start(self) -> None:
        """启动调度：立即跑一次，随后按 QF_DATA_SYNC_INTERVAL_MIN 周期重复。"""
        if self._scheduler is not None:
            return
        if os.getenv("QF_DISABLE_SCHEDULER") == "1":
            logger.info("行情同步调度已禁用（QF_DISABLE_SCHEDULER=1）")
            return
        interval = int(os.getenv("QF_DATA_SYNC_INTERVAL_MIN", "0") or "0")
        self._scheduler = BackgroundScheduler()
        if interval > 0:
            self._scheduler.add_job(
                self.run_once,
                "interval",
                minutes=interval,
                next_run_time=datetime.now(),
                id="market_sync",
                replace_existing=True,
            )
        else:
            # 仅启动时同步一次（演示/单机默认）
            self._scheduler.add_job(
                self.run_once,
                "date",
                run_date=datetime.now(),
                id="market_sync",
                replace_existing=True,
            )
        self._scheduler.start()
        logger.info("行情同步调度已启动（interval=%d 分钟）", interval)

    def shutdown(self) -> None:
        if self._scheduler is not None:
            self._scheduler.shutdown(wait=False)
            self._scheduler = None
            logger.info("行情同步调度已停止")

    def status(self) -> Dict:
        if self._latest is not None:
            return self._latest
        row = db.query_one(
            "SELECT id, source, status, symbols, bars_written, error, started_at, finished_at "
            "FROM data_updates ORDER BY started_at DESC LIMIT 1"
        )
        if row is None:
            return {
                "id": None,
                "source": self.service.primary.name,
                "status": "never_run",
                "symbols": "",
                "bars_written": 0,
                "error": None,
                "started_at": None,
                "finished_at": None,
                "stored_bars": self.service.repository.count(),
            }
        return {
            "id": row["id"],
            "source": row["source"],
            "status": row["status"],
            "symbols": row["symbols"],
            "bars_written": row["bars_written"],
            "error": row["error"],
            "started_at": row["started_at"],
            "finished_at": row["finished_at"],
            "stored_bars": self.service.repository.count(),
        }


# 全局单例（main.py 启动/关闭挂载）
data_sync_service = DataSyncService()
