"""用户投研工作区快照（V7.0）。

把 V5.x / V6.x 散落在各页面的能力聚合到一处，形成「投研总览」：
- 模拟账户快照（权益 / 现金 / 已实现盈亏 / 持仓数 / 挂单数 / 初始资金）
- 价格预警（规则总数 / 启用数 / 已触发数）
- 自选股（标的数量）
- 调度状态（行情自动同步 + 预警自动巡检）
- 因子库（当前用户拥有的因子数）

每个分区独立 try/except，单分区异常不影响其余分区返回（best-effort）。
全部基于本地数据，离线可用。
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from ..alerts import alert_service
from ..alerts import scheduler as alert_scheduler
from ..core.auth import get_current_user
from ..core.db import db
from ..factors import library
from ..market.scheduler import data_sync_service
from ..trading import engine

router = APIRouter(prefix="/workspace", tags=["workspace"])


@router.get("", summary="用户投研工作区快照（V7.0）")
def workspace(user: dict = Depends(get_current_user)) -> dict:
    uid = user.get("id")

    # 模拟账户快照
    trading = None
    try:
        s = engine.summary(uid)
        trading = {
            "equity": s.get("equity"),
            "cash": s.get("cash"),
            "market_value": s.get("market_value"),
            "realized_pnl": s.get("realized_pnl"),
            "position_count": s.get("position_count"),
            "open_orders": s.get("open_orders"),
            "initial_cash": s.get("initial_cash"),
        }
    except Exception:
        trading = None

    # 价格预警
    alerts = None
    try:
        rules = alert_service.list_rules()
        alerts = {
            "total": len(rules),
            "enabled": sum(1 for r in rules if r.get("enabled")),
            "triggered": sum(1 for r in rules if (r.get("trigger_count") or 0) > 0),
        }
    except Exception:
        alerts = None

    # 自选股
    watchlist = None
    try:
        rows = db.query("SELECT COUNT(*) AS c FROM watchlists")
        watchlist = {"count": int(rows[0]["c"]) if rows else 0}
    except Exception:
        watchlist = None

    # 调度状态
    scheduler = None
    try:
        scheduler = {
            "data_sync": data_sync_service.status(),
            "alert_eval": alert_scheduler.status(),
        }
    except Exception:
        scheduler = None

    # 因子库（按用户隔离）
    factors = None
    try:
        owned = library.list_factors(owner_id=uid)
        factors = {"count": len(owned)}
    except Exception:
        factors = None

    return {
        "trading": trading,
        "alerts": alerts,
        "watchlist": watchlist,
        "scheduler": scheduler,
        "factors": factors,
    }
