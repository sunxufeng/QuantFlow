"""行情 API（M2）：标的列表 + 日线数据获取。"""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query

from ..market.models import bars_to_table
from ..market.service import market_service
from ..core.data import to_serializable

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/instruments", summary="可用标的列表")
def list_instruments() -> dict:
    items = market_service.instruments()
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
    bars = market_service.bars(symbol=symbol, start=start, end=end)
    if as_table:
        table = bars_to_table(bars)
        return {"symbol": symbol, "count": len(bars), "data": to_serializable(table)}
    return {"symbol": symbol, "count": len(bars), "bars": [b.to_dict() for b in bars]}
