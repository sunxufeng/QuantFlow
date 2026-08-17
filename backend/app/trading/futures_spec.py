"""中国期货品种规格表与计算器（V108，移植自 panda FutureInfoMap 的品种元数据）。

panda 的 ``FutureInfoMap`` 从 Mongo 读取每个合约的 ``contractmul``（合约乘数）、
``fttransmargin``（保证金率）、``ftpricelimit``（涨跌停幅度）等。本模块把这些
**常见品种的参考规格**静态化，做成零依赖、可直接使用的规格表与计算函数，
弥补 quantflow 回测/对冲/虚拟券商此前只用「泛化 10% 保证金 + 每手 3 元」的不足。

字段说明（均为**参考值**，实际以交易所公告与券商通知为准，可在 ``FUTURES_SPEC`` 覆盖）：
- ``multiplier``    合约乘数（每手对应标的量，如 IF=300 元/点、沪铜=5 吨/手）
- ``margin_rate``   交易所保证金比例（初始）
- ``price_limit``   涨跌停幅度（相对昨结算，如 0.10 = ±10%）
- ``min_tick``      最小变动价位
- ``exchange``      交易所代码
- ``commission``    手续费模型：``{"per_lot": X}`` 按手固定，或 ``{"rate": r}`` 按成交额比例

符号解析：期货合约形如 ``IF2409`` / ``cu2501`` / ``sc2501``，取前置字母（去数字与
交易所后缀）作为品种代码查表；纯字母（如 ``IC``）原样查表。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Dict, Optional

# 交易所代码 -> 中文名（用于展示）
EXCHANGE_NAMES = {
    "CFFEX": "中金所",
    "SHFE": "上期所",
    "DCE": "大商所",
    "CZCE": "郑商所",
    "INE": "上海国际能源交易中心",
    "GFEX": "广期所",
}

# 常见中国期货品种参考规格。
# 注意：保证金率/涨跌停幅度会随市场与合约调整，此处为常用参考值。
FUTURES_SPEC: Dict[str, dict] = {
    # ---------------- 中金所 CFFEX（股指期货 + 国债期货） ----------------
    "IF": {"name": "沪深300股指", "exchange": "CFFEX", "multiplier": 300.0, "margin_rate": 0.12,
           "price_limit": 0.10, "min_tick": 0.2, "commission": {"rate": 0.000023}},
    "IH": {"name": "上证50股指", "exchange": "CFFEX", "multiplier": 300.0, "margin_rate": 0.12,
           "price_limit": 0.10, "min_tick": 0.2, "commission": {"rate": 0.000023}},
    "IC": {"name": "中证500股指", "exchange": "CFFEX", "multiplier": 200.0, "margin_rate": 0.12,
           "price_limit": 0.10, "min_tick": 0.2, "commission": {"rate": 0.000023}},
    "IM": {"name": "中证1000股指", "exchange": "CFFEX", "multiplier": 200.0, "margin_rate": 0.12,
           "price_limit": 0.10, "min_tick": 0.2, "commission": {"rate": 0.000023}},
    "T": {"name": "10年期国债", "exchange": "CFFEX", "multiplier": 10000.0, "margin_rate": 0.02,
          "price_limit": 0.02, "min_tick": 0.005, "commission": {"per_lot": 3.0}},
    "TF": {"name": "5年期国债", "exchange": "CFFEX", "multiplier": 10000.0, "margin_rate": 0.012,
           "price_limit": 0.012, "min_tick": 0.005, "commission": {"per_lot": 3.0}},
    "TS": {"name": "2年期国债", "exchange": "CFFEX", "multiplier": 20000.0, "margin_rate": 0.005,
           "price_limit": 0.005, "min_tick": 0.005, "commission": {"per_lot": 3.0}},

    # ---------------- 上期所 SHFE ----------------
    "cu": {"name": "沪铜", "exchange": "SHFE", "multiplier": 5.0, "margin_rate": 0.10,
           "price_limit": 0.04, "min_tick": 10.0, "commission": {"per_lot": 5.0}},
    "al": {"name": "沪铝", "exchange": "SHFE", "multiplier": 5.0, "margin_rate": 0.10,
           "price_limit": 0.04, "min_tick": 5.0, "commission": {"per_lot": 3.0}},
    "au": {"name": "沪金", "exchange": "SHFE", "multiplier": 1000.0, "margin_rate": 0.08,
           "price_limit": 0.05, "min_tick": 0.02, "commission": {"per_lot": 10.0}},
    "ag": {"name": "沪银", "exchange": "SHFE", "multiplier": 15.0, "margin_rate": 0.10,
           "price_limit": 0.06, "min_tick": 1.0, "commission": {"per_lot": 5.0}},
    "rb": {"name": "螺纹钢", "exchange": "SHFE", "multiplier": 10.0, "margin_rate": 0.10,
           "price_limit": 0.05, "min_tick": 1.0, "commission": {"per_lot": 3.0}},
    "ni": {"name": "沪镍", "exchange": "SHFE", "multiplier": 1.0, "margin_rate": 0.10,
           "price_limit": 0.08, "min_tick": 10.0, "commission": {"per_lot": 6.0}},

    # ---------------- 大商所 DCE ----------------
    "m": {"name": "豆粕", "exchange": "DCE", "multiplier": 10.0, "margin_rate": 0.10,
          "price_limit": 0.05, "min_tick": 1.0, "commission": {"per_lot": 1.5}},
    "i": {"name": "铁矿石", "exchange": "DCE", "multiplier": 100.0, "margin_rate": 0.12,
          "price_limit": 0.08, "min_tick": 0.5, "commission": {"per_lot": 5.0}},
    "p": {"name": "棕榈油", "exchange": "DCE", "multiplier": 10.0, "margin_rate": 0.10,
          "price_limit": 0.05, "min_tick": 2.0, "commission": {"per_lot": 2.5}},
    "c": {"name": "玉米", "exchange": "DCE", "multiplier": 10.0, "margin_rate": 0.10,
          "price_limit": 0.05, "min_tick": 1.0, "commission": {"per_lot": 1.2}},

    # ---------------- 郑商所 CZCE ----------------
    "SR": {"name": "白糖", "exchange": "CZCE", "multiplier": 10.0, "margin_rate": 0.10,
           "price_limit": 0.04, "min_tick": 1.0, "commission": {"per_lot": 3.0}},
    "CF": {"name": "棉花", "exchange": "CZCE", "multiplier": 5.0, "margin_rate": 0.10,
           "price_limit": 0.04, "min_tick": 5.0, "commission": {"per_lot": 4.0}},
    "TA": {"name": "PTA", "exchange": "CZCE", "multiplier": 5.0, "margin_rate": 0.10,
           "price_limit": 0.04, "min_tick": 2.0, "commission": {"per_lot": 3.0}},
    "MA": {"name": "甲醇", "exchange": "CZCE", "multiplier": 10.0, "margin_rate": 0.10,
           "price_limit": 0.05, "min_tick": 1.0, "commission": {"per_lot": 2.0}},

    # ---------------- 上海国际能源交易中心 INE ----------------
    "sc": {"name": "原油", "exchange": "INE", "multiplier": 1000.0, "margin_rate": 0.10,
           "price_limit": 0.08, "min_tick": 0.1, "commission": {"per_lot": 20.0}},

    # ---------------- 广期所 GFEX ----------------
    "si": {"name": "工业硅", "exchange": "GFEX", "multiplier": 5.0, "margin_rate": 0.10,
           "price_limit": 0.08, "min_tick": 5.0, "commission": {"per_lot": 5.0}},
    "lc": {"name": "碳酸锂", "exchange": "GFEX", "multiplier": 1.0, "margin_rate": 0.10,
           "price_limit": 0.10, "min_tick": 50.0, "commission": {"per_lot": 5.0}},
}


class SpecNotFound(Exception):
    """品种规格未找到。"""


@dataclass(frozen=True)
class FutureSpec:
    """单一期货品种的解析结果。"""

    code: str
    name: str
    exchange: str
    multiplier: float
    margin_rate: float
    price_limit: float
    min_tick: float
    commission: dict

    @property
    def exchange_name(self) -> str:
        return EXCHANGE_NAMES.get(self.exchange, self.exchange)

    def to_dict(self) -> dict:
        return {
            "code": self.code,
            "name": self.name,
            "exchange": self.exchange,
            "exchange_name": self.exchange_name,
            "multiplier": self.multiplier,
            "margin_rate": self.margin_rate,
            "price_limit": self.price_limit,
            "min_tick": self.min_tick,
            "commission": self.commission,
        }


def resolve_spec(symbol: str) -> FutureSpec:
    """从期货合约符号解析品种规格。

    ``IF2409`` / ``cu2501`` / ``sc2501`` -> 取前置字母（去数字与 ``.交易所`` 后缀）；
    纯字母 ``IC`` 原样查表。找不到抛 ``SpecNotFound``。
    """
    raw = (symbol or "").strip()
    if not raw:
        raise SpecNotFound("合约符号为空")
    # 去掉可能的 .交易所 后缀（如 IF2409.CFFEX）
    head = raw.split(".")[0]
    m = re.match(r"^([A-Za-z]+)", head)
    if not m:
        raise SpecNotFound(f"无法从 {symbol!r} 解析品种代码")
    code = m.group(1)
    # 大小写不敏感查表：规格表混合使用大写（指数/国债 IF/IH/T）与小写（商品 cu/al/m）键
    spec = FUTURES_SPEC.get(code) or FUTURES_SPEC.get(code.upper()) or FUTURES_SPEC.get(code.lower())
    if spec is None:
        raise SpecNotFound(f"未知期货品种：{code}（来自 {symbol!r}）")
    # 以规格表中实际存储的键作为规范品种代码
    canon = code if code in FUTURES_SPEC else (code.upper() if code.upper() in FUTURES_SPEC else code.lower())
    return FutureSpec(code=canon, **spec)


def list_specs() -> list:
    """返回全部品种规格列表（供前端下拉）。"""
    out = []
    for code, spec in FUTURES_SPEC.items():
        d = {"code": code, **spec}
        d["exchange_name"] = EXCHANGE_NAMES.get(spec["exchange"], spec["exchange"])
        out.append(d)
    return out


def contract_value(symbol: str, price: float) -> float:
    """单手持仓合约价值 = 乘数 × 价格。"""
    spec = resolve_spec(symbol)
    return spec.multiplier * float(price)


def margin_required(symbol: str, price: float, qty: int, rate_override: Optional[float] = None) -> float:
    """持仓保证金 = 合约价值 × 手数 × 保证金率。

    ``rate_override`` 可覆盖规格中的保证金率（如券商加收）。
    """
    spec = resolve_spec(symbol)
    rate = rate_override if rate_override is not None else spec.margin_rate
    return spec.multiplier * float(price) * int(qty) * float(rate)


def limit_price(symbol: str, prev_close: float, direction: str = "up") -> float:
    """计算涨跌停价（按昨结算 ± 幅度，对齐最小变动价位）。

    ``direction`` 为 ``"up"``（涨停）或 ``"down"``（跌停）。
    """
    spec = resolve_spec(symbol)
    factor = 1.0 + spec.price_limit if direction == "up" else 1.0 - spec.price_limit
    raw = float(prev_close) * factor
    tick = spec.min_tick
    # 向下取整到最小变动价位（国内期货涨跌停价按最小价位取整）
    stepped = int(raw / tick) * tick if tick > 0 else raw
    # 避免浮点尾差，四舍五入到合理小数位
    decimals = _tick_decimals(tick)
    return round(stepped, decimals)


def commission(symbol: str, price: float, qty: int) -> float:
    """计算手续费：按手固定或按成交额比例（双边按一次单边计，下单时买/卖各一次）。"""
    spec = resolve_spec(symbol)
    model = spec.commission or {}
    if "per_lot" in model:
        return float(model["per_lot"]) * int(qty)
    if "rate" in model:
        notional = spec.multiplier * float(price) * int(qty)
        return notional * float(model["rate"])
    return 0.0


def compute_futures(symbol: str, price: float, qty: int,
                    prev_close: Optional[float] = None,
                    margin_rate: Optional[float] = None) -> dict:
    """一站式计算：规格 + 合约价值 + 保证金 + 涨跌停价 + 手续费。"""
    spec = resolve_spec(symbol)
    pc = float(prev_close) if prev_close is not None else None
    return {
        "symbol": symbol,
        "spec": spec.to_dict(),
        "contract_value_per_lot": round(contract_value(symbol, price), 4),
        "total_contract_value": round(contract_value(symbol, price) * int(qty), 4),
        "margin_rate": margin_rate if margin_rate is not None else spec.margin_rate,
        "margin_required": round(margin_required(symbol, price, qty, margin_rate), 4),
        "commission": round(commission(symbol, price, qty), 4),
        "limit_up": round(limit_price(symbol, pc, "up"), 6) if pc is not None else None,
        "limit_down": round(limit_price(symbol, pc, "down"), 6) if pc is not None else None,
    }


def _tick_decimals(tick: float) -> int:
    """最小变动价位的小数位数（用于取整后保留合理精度）。"""
    s = repr(tick)
    if "." in s:
        return len(s.split(".")[1])
    return 0
