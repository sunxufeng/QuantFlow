"""行情 API（M2）：标的列表 + 日线数据获取 + 数据同步（V1.1 N4）。"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from ..core.auth import get_current_user
from ..core.data import to_serializable
from ..core.db import db
from ..market.models import bars_to_table
from ..market.scheduler import data_sync_service
from ..market.service import market_service
from ..market.sources import DataSourceError
from ..alerts import alert_service

router = APIRouter(
    prefix="/market",
    tags=["market"],
    dependencies=[Depends(get_current_user)],
)


def _today() -> str:
    return dt.date.today().isoformat()


@router.get("/instruments", summary="可用标的列表")
def list_instruments() -> dict:
    try:
        items = market_service.instruments()
    except DataSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return {
        "total": len(items),
        "items": [i.to_dict() for i in items],
    }


@router.get("/bars", summary="获取日线行情（自动缓存 + 数据源降级）")
def get_bars(
    symbol: str = Query(..., description="如 600519.SH / 000001.SZ / 510300.SH"),
    start: str = Query(None, description="YYYY-MM-DD"),
    end: str = Query(None, description="YYYY-MM-DD"),
    as_table: bool = Query(True, description="返回 DataTable 结构（工作流节点可直接消费）"),
) -> dict:
    if end and start and end < start:
        raise HTTPException(status_code=422, detail="end 不得早于 start")
    try:
        bars = market_service.bars(symbol=symbol, start=start, end=end)
    except DataSourceError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    if as_table:
        table = bars_to_table(bars)
        return {"symbol": symbol, "count": len(bars), "data": to_serializable(table)}
    return {"symbol": symbol, "count": len(bars), "bars": [b.to_dict() for b in bars]}


@router.get("/sync/status", summary="行情同步状态（V1.1 N4）")
def sync_status() -> dict:
    return data_sync_service.status()


@router.post("/sync", summary="手动触发行情同步（V1.1 N4）", status_code=202)
def sync_trigger(user: dict = Depends(get_current_user)) -> dict:
    return data_sync_service.run_once()


# --------------------------------------------------------------------------- #
# 行情缓存 / 数据源管理（V5.0）
# --------------------------------------------------------------------------- #
@router.get("/cache", summary="行情缓存与数据源快照（V5.0）")
def cache_snapshot() -> dict:
    return market_service.cache_summary()


class CacheRefreshRequest(BaseModel):
    symbols: Optional[List[str]] = None
    start: Optional[str] = None
    end: Optional[str] = None


@router.post("/cache/refresh", summary="强制从数据源重新拉取并落库（V5.0）", status_code=200)
def cache_refresh(
    req: CacheRefreshRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    try:
        return market_service.refresh(symbols=req.symbols, start=req.start, end=req.end)
    except DataSourceError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc



# --------------------------------------------------------------------------- #
# 自选股监控 / 行情看板（V2.4）
# --------------------------------------------------------------------------- #
@router.get("/watchlist", summary="自选股列表")
def get_watchlist() -> dict:
    rows = db.query("SELECT symbol FROM watchlists ORDER BY added_at DESC, symbol")
    return {"items": [r["symbol"] for r in rows]}


@router.post("/watchlist", summary="添加自选股", status_code=201)
def add_watchlist(symbol: str = Query(..., description="标的代码")):
    sym = symbol.strip().upper()
    if not sym:
        raise HTTPException(status_code=422, detail="symbol 不能为空")
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    db.execute(
        "INSERT OR IGNORE INTO watchlists (symbol, added_at) VALUES (?, ?)",
        (sym, now),
    )
    return {"symbol": sym, "added": True}


@router.delete("/watchlist/{symbol}", summary="移除自选股", status_code=204)
def remove_watchlist(symbol: str) -> None:
    db.execute("DELETE FROM watchlists WHERE symbol = ?", (symbol.strip().upper(),))


@router.get("/watchlist/monitor", summary="自选股监控 + 价格预警（V5.1）")
def watchlist_monitor() -> dict:
    """把自选股、实时行情快照、以及绑定到该标的的价格预警规则聚合为一个视图。"""
    rows = db.query("SELECT symbol FROM watchlists ORDER BY added_at DESC, symbol")
    symbols = [r["symbol"] for r in rows]
    all_alerts = alert_service.list_rules()
    items = []
    for sym in symbols:
        try:
            bars = market_service.bars(sym, "2000-01-01", _today())
        except DataSourceError:
            bars = []
        quote = None
        if bars:
            last = bars[-1]
            prev_close = bars[-2].close if len(bars) >= 2 else None
            change_pct = (
                (last.close - prev_close) / prev_close * 100.0
                if prev_close and prev_close > 0
                else None
            )
            quote = {
                "date": last.date,
                "last": last.close,
                "prev_close": prev_close,
                "change_pct": round(change_pct, 4) if change_pct is not None else None,
                "open": last.open,
                "high": last.high,
                "low": last.low,
                "volume": last.volume,
            }
        alerts = [a for a in all_alerts if a.get("symbol") == sym]
        items.append({"symbol": sym, "quote": quote, "alerts": alerts})
    return {"items": items, "total": len(items)}


@router.get("/quotes", summary="批量行情快照（最新价 + 当日涨跌）")
def get_quotes(symbols: str = Query(..., description="逗号分隔的标的，如 TEST.STOCK,TEST.BANK")):
    out = []
    for raw in symbols.split(","):
        sym = raw.strip().upper()
        if not sym:
            continue
        try:
            bars = market_service.bars(sym, "2000-01-01", _today())
        except DataSourceError:
            bars = []
        if not bars:
            out.append({"symbol": sym, "error": "无行情数据"})
            continue
        last = bars[-1]
        prev_close = bars[-2].close if len(bars) >= 2 else None
        change_pct = (
            (last.close - prev_close) / prev_close * 100.0
            if prev_close and prev_close > 0
            else None
        )
        out.append({
            "symbol": sym,
            "date": last.date,
            "last": last.close,
            "prev_close": prev_close,
            "change_pct": round(change_pct, 4) if change_pct is not None else None,
            "open": last.open,
            "high": last.high,
            "low": last.low,
            "volume": last.volume,
        })
    return {"items": out}
