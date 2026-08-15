"""合成行情生成器（V20，无凭证）。

在缺少真实行情源时，用几何布朗运动（GBM）或带状态转移（regime）的
随机游走生成逼真的日线价格序列，供回测 / 前向模拟使用。

- ``generate_symbol``：单标的合成日线（OHLCV）
- ``generate_universe``：多标的（可设相关性近似：同漂移 + 独立噪声）
"""

from __future__ import annotations

import datetime as dt
import math
import random
from typing import List, Optional

from .models import Bar

TRADING_DAYS = 252


def _business_days(start: str, end: str) -> List[str]:
    s = dt.date.fromisoformat(start)
    e = dt.date.fromisoformat(end)
    out = []
    cur = s
    while cur <= e:
        if cur.weekday() < 5:  # 周一~周五
            out.append(cur.isoformat())
        cur += dt.timedelta(days=1)
    return out


def generate_symbol(
    symbol: str,
    start: str,
    end: str,
    initial_price: float = 100.0,
    mu_annual: float = 0.08,
    sigma_annual: float = 0.20,
    seed: Optional[int] = None,
    regime: bool = False,
) -> List[Bar]:
    """生成单标的合成日线（GBM）。

    - 普通模式：固定年化漂移 mu 与波动 sigma 的几何布朗运动。
    - regime 模式：漂移在若干区间随机切换（牛/震荡/熊），更贴近真实。
    """
    rng = random.Random(seed)
    dates = _business_days(start, end)
    if not dates:
        return []
    dt_daily = 1.0 / TRADING_DAYS
    bars: List[Bar] = []

    if regime:
        regimes = [
            (0.30, 0.25),   # 牛市：高漂移、高波动
            (0.00, 0.15),   # 震荡：零漂移
            (-0.20, 0.30),  # 熊市：负漂移、高波动
        ]
        cur_mu, cur_sigma = regimes[0]
        days_in_regime = 0
        regime_len = rng.randint(20, 60)
    else:
        cur_mu, cur_sigma = mu_annual, sigma_annual

    price = float(initial_price)
    for i, d in enumerate(dates):
        if regime:
            if days_in_regime >= regime_len:
                cur_mu, cur_sigma = rng.choice(regimes)
                days_in_regime = 0
                regime_len = rng.randint(20, 60)
            days_in_regime += 1
        z = rng.gauss(0.0, 1.0)
        drift = (cur_mu - 0.5 * cur_sigma ** 2) * dt_daily
        diff = cur_sigma * math.sqrt(dt_daily) * z
        price *= math.exp(drift + diff)
        price = max(price, 0.01)
        close = round(price, 4)
        # 简单 OHLC：以收盘为中心加小幅扰动
        intra = max(close * 0.005, 0.01)
        o = round(close * (1 + rng.uniform(-0.003, 0.003)), 4)
        high = round(max(o, close) + rng.uniform(0, intra), 4)
        low = round(min(o, close) - rng.uniform(0, intra), 4)
        vol = int(rng.uniform(5e5, 2e6))
        bars.append(Bar(
            symbol=symbol, date=d, open=o, high=high, low=low, close=close, volume=vol,
        ))
    return bars


def generate_universe(
    symbols: List[str],
    start: str,
    end: str,
    initial_prices: Optional[dict] = None,
    mu_annual: float = 0.08,
    sigma_annual: float = 0.20,
    seed: Optional[int] = None,
    regime: bool = False,
) -> dict:
    """生成多个标的的合成日线，返回 {symbol: [Bar]}。

    各标的共享相同的漂移/波动参数（近似正相关），但噪声独立。
    """
    out = {}
    base_seed = seed if seed is not None else 12345
    for i, sym in enumerate(symbols):
        s = generate_symbol(
            sym, start, end,
            initial_price=float((initial_prices or {}).get(sym, 100.0)),
            mu_annual=mu_annual, sigma_annual=sigma_annual,
            seed=base_seed + i * 1009, regime=regime,
        )
        out[sym] = s
    return out
