"""V105 对冲 / 反向交易计算器（纯逻辑，移植自 panda reverse_operation 的计算内核）。

panda 的 ``ReverseOperationProxy`` 是重度依赖事件总线 / Mongo / Redis / CTP 的实盘编排器，
其源码本身不含可移植的数学（见 ``reverse_operation_proxy.py`` 与 ``strategy/ase.py``：
后者仅演示 ``insert_future_group_order(account, long_dict, short_dict)`` 这类篮子组单）。
本模块只移植其「反向 / 对冲 / 篮子组单」的**计算内核**，彻底剥离所有外部基础设施依赖：

- ``beta_neutral_hedge``：用股指合约对股票组合做 Beta 中性对冲，给出应对冲的合约手数（开空/开多）。
- ``reverse_position``：给定当前持仓（带符号数量），给出反向平仓 / 反手的下单量与方向。
- ``group_order``：给定多头篮子与空头篮子（dict[symbol->qty]），给出组单结构，对应 panda 的
  ``insert_future_group_order`` / ``insert_stock_group_order``。

所有函数均为纯函数，输入/输出为普通 dict，便于单测、API 与前端复用。
"""

from __future__ import annotations


def _as_float(v, name: str) -> float:
    try:
        return float(v)
    except (TypeError, ValueError):
        raise ValueError(f"{name} 必须为数值，收到：{v!r}")


def beta_neutral_hedge(
    portfolio: list,
    future_price: float,
    multiplier: float,
    target_beta: float = 0.0,
    future_beta: float = 1.0,
    round_lot: float = 1.0,
):
    """Beta 中性对冲计算器。

    :param portfolio: 股票组合，元素为 dict：``{"symbol", "market_value", "beta"}``。
        ``market_value`` 为持仓市值（元），``beta`` 为该标的贝塔。
    :param future_price: 股指期货合约当前价位（指数点，如 IF=3800）。
    :param multiplier: 合约乘数（IF/IH=300，IC/IM=200）。
    :param target_beta: 目标组合贝塔（默认 0 = 完全中性）。
    :param future_beta: 股指合约自身贝塔（对冲比例，默认 1.0）。
    :param round_lot: 合约最小变动手数（默认 1 手）。
    :return: dict，含组合贝塔、组合市值、应对冲手数、方向、对冲名义金额、残差贝塔等。
    """
    if not portfolio:
        raise ValueError("portfolio 不能为空")
    future_price = _as_float(future_price, "future_price")
    multiplier = _as_float(multiplier, "multiplier")
    target_beta = _as_float(target_beta, "target_beta")
    future_beta = _as_float(future_beta, "future_beta")
    round_lot = _as_float(round_lot, "round_lot")
    if future_price <= 0 or multiplier <= 0:
        raise ValueError("future_price 与 multiplier 必须为正")
    if round_lot <= 0:
        raise ValueError("round_lot 必须为正")

    total_value = 0.0
    weighted_beta = 0.0
    rows = []
    for item in portfolio:
        mv = _as_float(item.get("market_value"), "portfolio[].market_value")
        beta = _as_float(item.get("beta"), "portfolio[].beta")
        if mv < 0:
            raise ValueError("market_value 不能为负")
        total_value += mv
        weighted_beta += mv * beta
        rows.append({"symbol": item.get("symbol", ""), "market_value": mv, "beta": beta})
    if total_value <= 0:
        raise ValueError("组合市值必须大于 0")

    portfolio_beta = weighted_beta / total_value
    # 将组合贝塔从 portfolio_beta 调整到 target_beta 所需合约（含合约贝塔）：
    #   (target - portfolio_beta) * 组合市值 = 合约数 * future_price * multiplier * future_beta
    raw_contracts = (target_beta - portfolio_beta) * total_value / (future_price * multiplier * future_beta)
    side = "sell" if raw_contracts < 0 else "buy"
    raw_abs = abs(raw_contracts)
    # 向下/上取至最小变动手数整数倍（优先取接近的整数手，避免不足一手的碎单）
    contracts = max(round_lot, round(raw_abs / round_lot) * round_lot)
    if round(raw_abs / round_lot) == 0:
        contracts = 0.0
    hedge_notional = contracts * future_price * multiplier
    sign = 1.0 if side == "buy" else -1.0
    residual_beta = portfolio_beta + sign * hedge_notional * future_beta / total_value

    return {
        "kind": "beta",
        "portfolio_beta": round(portfolio_beta, 4),
        "portfolio_value": round(total_value, 2),
        "target_beta": round(target_beta, 4),
        "future_price": round(future_price, 2),
        "multiplier": multiplier,
        "contracts": int(contracts) if contracts == int(contracts) else contracts,
        "side": side,
        "side_label": "开多(买入)" if side == "buy" else "开空(卖出)",
        "hedge_notional": round(hedge_notional, 2),
        "residual_beta": round(residual_beta, 4),
        "note": (
            f"组合贝塔 {portfolio_beta:.2f} → 目标 {target_beta:.2f}："
            f"需{side_label(side)} {_fmt_qty(contracts)} 手股指（名义 {hedge_notional:,.0f} 元），"
            f"对冲后残差贝塔约 {residual_beta:.2f}。"
        ),
        "rows": rows,
    }


def reverse_position(current_qty: float, mode: str = "close"):
    """反向持仓计算器。

    :param current_qty: 当前持仓数量（带符号：+ 多 / - 空）。
    :param mode: ``"close"`` 平仓（回到 0）；``"flip"`` 反手（平掉并开等量反向）。
    :return: dict，含下单方向、下单量、说明。
    """
    current_qty = _as_float(current_qty, "current_qty")
    if mode not in ("close", "flip"):
        raise ValueError("mode 必须为 close 或 flip")
    if mode == "close":
        order_qty = -current_qty
        note = f"当前{'多' if current_qty > 0 else '空'}仓 {_fmt_qty(abs(current_qty))} 手 → 反向平仓至 0。"
    else:  # flip
        order_qty = -2 * current_qty
        note = (
            f"当前{'多' if current_qty > 0 else '空'}仓 {_fmt_qty(abs(current_qty))} 手 → "
            f"反手为{'空' if current_qty > 0 else '多'}仓同等数量。"
        )
    side = "sell" if order_qty < 0 else "buy"
    return {
        "kind": "reverse",
        "current_qty": current_qty,
        "mode": mode,
        "order_side": side,
        "order_side_label": "卖出" if side == "sell" else "买入",
        "order_qty": _fmt_qty(abs(order_qty)),
        "note": note,
    }


def group_order(long_dict: dict, short_dict: dict, prices: dict = None):
    """篮子组单计算器（对应 panda insert_future_group_order / insert_stock_group_order）。

    :param long_dict: 多头篮子 ``{symbol: qty}``。
    :param short_dict: 空头篮子 ``{symbol: qty}``。
    :param prices: 可选 ``{symbol: price}``，用于计算多空名义金额与净敞口。
    :return: dict，含逐笔组单列表、多/空数量、名义金额与净敞口。
    """
    long_dict = long_dict or {}
    short_dict = short_dict or {}
    if not isinstance(long_dict, dict) or not isinstance(short_dict, dict):
        raise ValueError("long_dict / short_dict 必须为对象")

    orders = []
    long_qty = 0.0
    short_qty = 0.0
    long_notional = 0.0
    short_notional = 0.0
    for sym, qty in long_dict.items():
        q = _as_float(qty, f"long_dict[{sym}]")
        orders.append({"symbol": sym, "side": "buy", "qty": _fmt_qty(q)})
        long_qty += q
        if prices and sym in prices:
            long_notional += q * _as_float(prices[sym], f"prices[{sym}]")
    for sym, qty in short_dict.items():
        q = _as_float(qty, f"short_dict[{sym}]")
        orders.append({"symbol": sym, "side": "sell", "qty": _fmt_qty(q)})
        short_qty += q
        if prices and sym in prices:
            short_notional += q * _as_float(prices[sym], f"prices[{sym}]")

    net_notional = long_notional - short_notional
    return {
        "kind": "group",
        "orders": orders,
        "long_count": len(long_dict),
        "short_count": len(short_dict),
        "long_qty": _fmt_qty(long_qty),
        "short_qty": _fmt_qty(short_qty),
        "long_notional": round(long_notional, 2),
        "short_notional": round(short_notional, 2),
        "net_notional": round(net_notional, 2),
        "note": (
            f"组单：多头 {len(long_dict)} 只 / 空头 {len(short_dict)} 只"
            + (f"，多空净敞口 {net_notional:,.0f} 元" if prices else "")
            + "。"
        ),
    }


def compute_hedge(payload: dict) -> dict:
    """API 入口：按 ``kind`` 分发到对应计算器。

    :param payload: 含 ``kind``（beta | reverse | group）及对应字段的 dict。
    """
    kind = (payload or {}).get("kind")
    if kind == "beta":
        return beta_neutral_hedge(
            payload.get("portfolio") or [],
            payload.get("future_price"),
            payload.get("multiplier"),
            target_beta=payload.get("target_beta", 0.0),
            future_beta=payload.get("future_beta", 1.0),
            round_lot=payload.get("round_lot", 1.0),
        )
    if kind == "reverse":
        return reverse_position(payload.get("current_qty", 0), payload.get("mode", "close"))
    if kind == "group":
        return group_order(
            payload.get("long_dict") or {},
            payload.get("short_dict") or {},
            payload.get("prices"),
        )
    raise ValueError("kind 必须为 beta / reverse / group 之一")


def side_label(side: str) -> str:
    return "卖出" if side == "sell" else "买入"


def _fmt_qty(q) -> float:
    q = float(q)
    if q == int(q):
        return int(q)
    return round(q, 4)
