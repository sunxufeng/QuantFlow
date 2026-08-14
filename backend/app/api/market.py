"""行情 API（M2）：标的列表 + 日线数据获取 + 数据同步（V1.1 N4）。"""

from __future__ import annotations

import datetime as dt
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from ..core.auth import get_current_user
from ..core.data import to_serializable
from ..core.db import db
from ..market.models import Bar, bars_to_table
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
# 用户行情导入（V7.1）：CSV 上传 -> 落库，回测/行情可直接使用（无需外部凭证）
# --------------------------------------------------------------------------- #
_UPLOAD_SOURCE = "upload"

_COLUMN_ALIASES = {
    "date": "date", "日期": "date", "时间": "date", "trade_date": "date", "交易日": "date",
    "open": "open", "开盘": "open", "开盘价": "open", "o": "open",
    "high": "high", "最高": "high", "最高价": "high", "h": "high",
    "low": "low", "最低": "low", "最低价": "low", "l": "low",
    "close": "close", "收盘": "close", "收盘价": "close", "c": "close",
    "volume": "volume", "成交量": "volume", "vol": "volume", "v": "volume",
    "amount": "amount", "成交额": "amount",
}


def _parse_ohlcv(text: str) -> List[dict]:
    """把 OHLCV CSV 文本解析为行 dict（date/open/high/low/close/volume/amount）。

    兼容 Yahoo 导出（Date,Open,High,Low,Close,Adj Close,Volume）与自定义列名。
    """
    import csv as _csv
    import io as _io

    reader = list(_csv.reader(_io.StringIO(text.strip())))
    if not reader:
        return []
    # 解析表头
    header = [h.strip() for h in reader[0]]
    idx = {}
    for i, h in enumerate(header):
        key = _COLUMN_ALIASES.get(h.lower())
        if key and key not in idx:
            idx[key] = i
    # 无表头时按位置推断：date,open,high,low,close,volume
    if not idx:
        for key, i in (("date", 0), ("open", 1), ("high", 2), ("low", 3), ("close", 4), ("volume", 5)):
            if i < len(header):
                idx[key] = i
    if "date" not in idx or "close" not in idx:
        raise ValueError("CSV 必须包含 date/日期 与 close/收盘 列")
    rows: List[dict] = []
    for raw in reader[1:]:
        if not raw or all(not c.strip() for c in raw):
            continue
        try:
            get = lambda k: raw[idx[k]].strip() if k in idx and idx[k] < len(raw) else ""
            date = get("date")
            close = float(get("close"))
            row = {
                "date": date,
                "open": float(get("open")) if "open" in idx and get("open") else close,
                "high": float(get("high")) if "high" in idx and get("high") else close,
                "low": float(get("low")) if "low" in idx and get("low") else close,
                "close": close,
                "volume": float(get("volume")) if "volume" in idx and get("volume") else 0.0,
                "amount": float(get("amount")) if "amount" in idx and get("amount") else 0.0,
            }
        except (ValueError, IndexError) as exc:
            raise ValueError(f"第 {len(rows) + 2} 行解析失败: {exc}") from exc
        rows.append(row)
    return rows


class MarketUploadRequest(BaseModel):
    symbol: str = Field(..., description="自定义标的代码，如 MY.AAPL / 600519.SH", min_length=1)
    name: str = Field("", description="标的名称（可选）")
    csv: Optional[str] = Field(None, description="OHLCV CSV 文本（含表头）")
    bars: Optional[List[dict]] = Field(None, description="或直接传 bars 列表")


@router.post("/upload", summary="上传用户行情（CSV/JSON -> 落库，V7.1）", status_code=201)
def upload_market(
    req: MarketUploadRequest,
    user: dict = Depends(get_current_user),
) -> dict:
    """上传自定义标的的日线行情，落库后可直接用于回测与行情快照。无需外部数据源凭证。"""
    symbol = req.symbol.strip().upper()
    if not symbol:
        raise HTTPException(status_code=422, detail="symbol 不能为空")
    # 解析
    raw_rows: List[dict] = []
    if req.bars:
        for b in req.bars:
            try:
                raw_rows.append({
                    "date": str(b["date"]),
                    "open": float(b.get("open", b["close"])),
                    "high": float(b.get("high", b["close"])),
                    "low": float(b.get("low", b["close"])),
                    "close": float(b["close"]),
                    "volume": float(b.get("volume", 0) or 0),
                    "amount": float(b.get("amount", 0) or 0),
                })
            except (KeyError, ValueError, TypeError) as exc:
                raise HTTPException(status_code=422, detail=f"bars 行非法: {exc}") from exc
    elif req.csv:
        try:
            raw_rows = _parse_ohlcv(req.csv)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
    else:
        raise HTTPException(status_code=422, detail="csv 与 bars 至少传一个")
    if not raw_rows:
        raise HTTPException(status_code=422, detail="未解析到任何行情行")
    # 按日期升序
    raw_rows.sort(key=lambda r: r["date"])
    bars = [
        Bar(
            symbol=symbol,
            date=r["date"],
            interval="daily",
            open=r["open"],
            high=r["high"],
            low=r["low"],
            close=r["close"],
            volume=r["volume"],
            amount=r["amount"],
            source=_UPLOAD_SOURCE,
            adjustment="none",
        )
        for r in raw_rows
    ]
    written = market_service.upload_bars(symbol, bars)
    return {
        "symbol": symbol,
        "name": req.name or symbol,
        "count": written,
        "first_date": bars[0].date,
        "last_date": bars[-1].date,
        "source": _UPLOAD_SOURCE,
    }


@router.get("/uploaded", summary="已导入的用户行情标的列表（V7.1）")
def list_uploaded() -> dict:
    items = market_service.uploaded_symbols()
    return {"items": items, "total": len(items)}


@router.delete("/uploaded/{symbol}", summary="删除用户导入的行情（V7.1）", status_code=204)
def delete_uploaded(symbol: str) -> None:
    n = market_service.delete_uploaded(symbol.strip().upper())
    if n == 0:
        raise HTTPException(status_code=404, detail="该标的无导入数据")



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
