"""交易成本模型（M2 回测引擎）。

对标开发计划 §4.2：手续费 / 印花税 / 过户费 / 滑点，配置存于
``cost_rate.json``（内置默认，支持自定义路径覆盖）。

A 股规则：
- 佣金：双边，默认万 2.5，最低 5 元
- 印花税：卖出单边，0.05%（2023-08 起）
- 过户费：双边，0.001%（沪市，2022-04 起统一）
- 滑点：按成交价比例（买入上浮 / 卖出下浮），默认 0
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from typing import Optional


def _default_rates() -> dict:
    return {
        "commission_rate": 0.00025,   # 佣金万 2.5
        "commission_min": 5.0,        # 最低佣金（元）
        "stamp_tax_rate": 0.0005,     # 印花税（卖出）
        "transfer_fee_rate": 0.00001, # 过户费（双边）
        "slippage": 0.0,              # 滑点比例（双边方向）
        "subscription_fee_rate": 0.0015,  # 场外基金申购费（前端，默认 0.15% 一折）
        "redemption_fee_rate": 0.005,     # 场外基金赎回费（默认 0.5%，阶梯为空时回退）
        "futures_commission_per_lot": 3.0,  # 期货每手手续费（元/手）
        "futures_margin_rate": 0.10,        # 期货初始保证金比例
        "futures_maintenance_ratio": 0.75,  # 期货维持保证金 / 初始保证金
    }


@dataclass(frozen=True)
class CostRates:
    commission_rate: float = 0.00025
    commission_min: float = 5.0
    stamp_tax_rate: float = 0.0005
    transfer_fee_rate: float = 0.00001
    slippage: float = 0.0
    subscription_fee_rate: float = 0.0015
    redemption_fee_rate: float = 0.005
    # 赎回费阶梯：(最短持有天数, 费率) 升序；持有期 >= 该天数适用对应费率。
    # 默认等效于统一 0.5%（任何持有期均命中 (0, 0.005)），保证向后兼容。
    redemption_fee_tiers: tuple = ((0, 0.005),)
    # 期货（V1.3）：按手手续费、保证金比例、维持保证金比例（相对初始保证金）
    futures_commission_per_lot: float = 3.0       # 每手固定手续费（元/手）
    futures_margin_rate: float = 0.10             # 初始保证金比例
    futures_maintenance_ratio: float = 0.75       # 维持保证金 / 初始保证金
    # 期货（V1.3）：按手手续费、保证金比例、维持保证金比例（相对初始保证金）
    futures_commission_per_lot: float = 3.0       # 每手固定手续费（元/手）
    futures_margin_rate: float = 0.10             # 初始保证金比例
    futures_maintenance_ratio: float = 0.75       # 维持保证金 / 初始保证金

    @classmethod
    def from_dict(cls, data: dict) -> "CostRates":
        base = _default_rates()
        base.update({k: float(v) for k, v in data.items() if k in base})
        tiers = cls._default_tiers()
        if "redemption_fee_tiers" in data:
            raw = data["redemption_fee_tiers"]
            tiers = tuple((int(t[0]), float(t[1])) for t in raw)
        return cls(
            commission_rate=base["commission_rate"],
            commission_min=base["commission_min"],
            stamp_tax_rate=base["stamp_tax_rate"],
            transfer_fee_rate=base["transfer_fee_rate"],
            slippage=base["slippage"],
            subscription_fee_rate=base["subscription_fee_rate"],
            redemption_fee_rate=base["redemption_fee_rate"],
            redemption_fee_tiers=tiers,
            futures_commission_per_lot=base["futures_commission_per_lot"],
            futures_margin_rate=base["futures_margin_rate"],
            futures_maintenance_ratio=base["futures_maintenance_ratio"],
        )

    @staticmethod
    def _default_tiers() -> tuple:
        return ((0, 0.005),)

    def to_dict(self) -> dict:
        return {
            "commission_rate": self.commission_rate,
            "commission_min": self.commission_min,
            "stamp_tax_rate": self.stamp_tax_rate,
            "transfer_fee_rate": self.transfer_fee_rate,
            "slippage": self.slippage,
            "subscription_fee_rate": self.subscription_fee_rate,
            "redemption_fee_rate": self.redemption_fee_rate,
            "redemption_fee_tiers": [list(t) for t in self.redemption_fee_tiers],
            "futures_commission_per_lot": self.futures_commission_per_lot,
            "futures_margin_rate": self.futures_margin_rate,
            "futures_maintenance_ratio": self.futures_maintenance_ratio,
        }


def resolve_redemption_fee_rate(tiers: tuple, holding_days: int) -> float:
    """按持有期（自然日）从阶梯中解析赎回费率；空阶梯回退 0。

    ``tiers`` 须按 (min_holding_days, rate) 升序；取满足条件的最大档。
    """
    if not tiers:
        return 0.0
    rate = tiers[0][1]
    for min_days, r in tiers:
        if holding_days >= min_days:
            rate = r
        else:
            break
    return rate


def load_cost_rates(path: Optional[str] = None) -> CostRates:
    """加载成本配置；未指定路径时先查 QF_COST_RATE_JSON，否则用内置默认。"""
    if path is None:
        path = os.getenv("QF_COST_RATE_JSON", "")
    if not path or not os.path.exists(path):
        return CostRates()
    with open(path, encoding="utf-8") as f:
        return CostRates.from_dict(json.load(f))


class CostCalculator:
    """按 A 股规则计算单笔交易成本与成交价。"""

    def __init__(self, rates: Optional[CostRates] = None) -> None:
        self.rates = rates or CostRates()

    def execution_price(self, price: float, is_buy: bool) -> float:
        """含滑点的执行价：买入上浮、卖出下浮。"""
        s = self.rates.slippage
        return price * (1 + s) if is_buy else price * (1 - s)

    def transaction_costs(
        self, price: float, shares: int, is_buy: bool
    ) -> dict:
        """计算一笔交易的成本明细。price 为执行价，shares 为成交股数。"""
        notional = price * shares
        commission = max(notional * self.rates.commission_rate, self.rates.commission_min)
        stamp_tax = notional * self.rates.stamp_tax_rate if not is_buy else 0.0
        transfer_fee = notional * self.rates.transfer_fee_rate
        total = commission + stamp_tax + transfer_fee
        return {
            "notional": round(notional, 4),
            "commission": round(commission, 4),
            "stamp_tax": round(stamp_tax, 4),
            "transfer_fee": round(transfer_fee, 4),
            "total": round(total, 4),
        }
