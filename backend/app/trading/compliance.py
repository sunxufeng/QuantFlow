"""交易合规预检引擎（移植自 panda_quantflow 的 ``exchange/*_verify`` 系列）。

panda 在下单前对每笔委托做四道校验：
- ``FutureOrderTradeTimeVerify``  —— 交易时段校验
- ``FutureOrderAccountVerify``   —— 账户 / 持仓充足性校验
- ``FutureOrderLimitPriceVerify``—— 涨跌停限价校验
- ``FutureOrderSplitManager``     —— 平今/平昨拆单（上期所/能源中心先平昨再平今）

这里把这套**纯逻辑**移植到 quantflow 的模拟交易体系，去掉对 CoreContext /
Mongo / QuotationData 的依赖，改为读取 ``trading.store`` 的账户状态。校验结果
分两级：``error``（应拒绝下单）与 ``warn``（提示但不拦截，例如拆单建议）。
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

from ..market.session import is_market_open

# 各交易所涨跌停幅度（占上一交易日收盘价的比例）
LIMIT_PCT_BY_EXCHANGE = {
    "SH": 0.10, "SZ": 0.10,          # 股票 ±10%
    "SHF": 0.10, "DCE": 0.10, "CZC": 0.10, "INE": 0.10, "CFE": 0.10,  # 期货默认 ±10%
    "SHFE": 0.10,
}
DEFAULT_LIMIT_PCT = 0.10

# 先平昨再平今的交易所（panda: SHFE / INE）
SPLIT_YD_FIRST_EXCHANGES = {"SHF", "SHFE", "INE"}

# 标的后缀 -> 资产类型 / 交易所
_FUTURE_SUFFIXES = {"SHF", "SHFE", "DCE", "CZC", "INE", "CFE"}


def infer_asset_type(symbol: str) -> Dict[str, str]:
    """根据标的代码推断资产类型与交易所。"""
    sym = (symbol or "").upper().strip()
    if "." in sym:
        exch = sym.rsplit(".", 1)[1]
    else:
        exch = ""
    if exch in _FUTURE_SUFFIXES:
        return {"asset_type": "future", "exchange": exch, "market": "future"}
    return {"asset_type": "stock", "exchange": exch or "SH", "market": "stock"}


def _limit_pct(exchange: str) -> float:
    return LIMIT_PCT_BY_EXCHANGE.get(exchange, DEFAULT_LIMIT_PCT)


def verify_order(
    user_id: str,
    symbol: str,
    side: str,
    otype: str,
    qty: float,
    price: Optional[float] = None,
    now: Optional[Any] = None,
    today_qty: Optional[float] = None,
) -> Dict[str, Any]:
    """对一笔委托做预检，返回 {ok, violations, suggestions}。

    - violations: 列表，元素 {code, level('error'|'warn'), message}
    - suggestions: 列表，元素为可读的建议文本（如拆单方案）
    ``error`` 级表示应拒绝下单；``warn`` 仅提示。
    """
    from ..trading import store

    violations: List[Dict[str, str]] = []
    suggestions: List[str] = []

    meta = infer_asset_type(symbol)
    asset_type = meta["asset_type"]
    exchange = meta["exchange"]

    # 1) 交易时段校验（移植 FutureOrderTradeTimeVerify）
    if not is_market_open(asset_type, now):
        violations.append({
            "code": "NOT_TRADING_TIME",
            "level": "error",
            "message": f"当前非{('股票' if asset_type == 'stock' else '期货')}交易时段，委托将被拒绝",
        })

    # 2) 账户 / 持仓充足性校验（移植 FutureOrderAccountVerify）
    if side == "buy":
        last = store.last_price(symbol)
        ref_price = price if (otype == "limit" and price) else last
        if ref_price:
            need = qty * ref_price
            cash = store.get_cash(user_id)
            if need > cash:
                violations.append({
                    "code": "CASH_NOT_ENOUGH",
                    "level": "error",
                    "message": f"资金不足：需约 {need:,.2f}，账户可用 {cash:,.2f}",
                })
    else:  # sell —— 平多需持仓充足
        pos = store.get_position(user_id, symbol)
        held = float(pos["qty"]) if pos else 0.0
        if held < qty:
            violations.append({
                "code": "POSITION_NOT_ENOUGH",
                "level": "error",
                "message": f"可平持仓不足：拟卖 {qty:g}，当前多仓 {held:g}",
            })
        # 3) 平今/平昨拆单建议（移植 FutureOrderSplitManager，仅 SHFE/INE）
        if exchange in SPLIT_YD_FIRST_EXCHANGES:
            today = float(today_qty) if today_qty is not None else 0.0
            yd = max(held - today, 0.0)
            if qty > yd and today > 0:
                suggestions.append(
                    f"【{exchange}】平仓请先平昨仓再平今仓：建议先平昨 {yd:g} 手，再平今 {qty - yd:g} 手"
                )
            elif qty <= yd:
                suggestions.append(f"【{exchange}】优先平昨仓 {qty:g} 手（避免平今高手续费）")

    # 4) 涨跌停限价校验（移植 FutureOrderLimitPriceVerify）
    last = store.last_price(symbol)
    if last and otype == "limit" and price is not None:
        pct = _limit_pct(exchange)
        limit_up = last * (1 + pct)
        limit_down = last * (1 - pct)
        if side == "buy" and price >= limit_up:
            violations.append({
                "code": "LIMIT_UP",
                "level": "error",
                "message": f"涨停价 {limit_up:,.2f}，无法以 {price:,.2f} 买入",
            })
        elif side == "sell" and price <= limit_down:
            violations.append({
                "code": "LIMIT_DOWN",
                "level": "error",
                "message": f"跌停价 {limit_down:,.2f}，无法以 {price:,.2f} 卖出",
            })

    ok = not any(v["level"] == "error" for v in violations)
    return {"ok": ok, "violations": violations, "suggestions": suggestions}


def enforce_compliance(user_id: str, symbol: str, side: str, otype: str, qty: float,
                       price=None, now=None, today_qty=None) -> None:
    """在 submit_order 中调用：存在 error 级违规时抛 ValueError。

    由环境变量 ``QF_ENFORCE_ORDER_COMPLIANCE`` 控制是否启用（默认关闭，避免影响
    现有模拟交易测试与流程；UI 的「合规预检」面板始终可用）。
    """
    if os.getenv("QF_ENFORCE_ORDER_COMPLIANCE", "0") not in ("1", "true", "True"):
        return
    res = verify_order(user_id, symbol, side, otype, qty, price, now, today_qty)
    if not res["ok"]:
        msgs = [v["message"] for v in res["violations"] if v["level"] == "error"]
        raise ValueError("；".join(msgs))
