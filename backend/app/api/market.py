"""行情 API（M2）：标的列表 + 日线数据获取 + 数据同步（V1.1 N4）。"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query

from ..core.auth import get_current_user
from ..core.data import to_serializable
from ..market.models import bars_to_table
from ..market.scheduler import data_sync_service
from ..market.service import market_service
from ..market.sources import DataSourceError

router = APIRouter(
    prefix="/market",
    tags=["market"],
    dependencies=[Depends(get_current_user)],
)


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
