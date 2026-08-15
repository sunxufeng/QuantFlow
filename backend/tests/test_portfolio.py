"""V1.2 组合回测测试：多腿合并净值、配置占比、绩效指标、API 端点。

合并逻辑通过「独立运行各腿 + 逐日求和」精确对照，防止口径回归。
"""

from __future__ import annotations

from typing import Any, Dict

import pytest

from app.backtest import BacktestEngine, PortfolioBacktest
from app.backtest.engine import EquityPoint
from app.backtest.strategies import STRATEGY_REGISTRY
from app.market.models import Instrument
from app.market.service import market_service


START = "2024-01-02"
END = "2024-01-29"


def _instruments(leg: Dict[str, Any]) -> Dict[str, Instrument]:
    out = {}
    for sym in leg["symbols"]:
        at = leg["asset_types"].get(sym, "stock")
        out[sym] = Instrument(
            symbol=sym, name="t", market=at, exchange="" if at == "fund" else "SH"
        )
    return out


def _run_leg(leg: Dict[str, Any], initial: float, start: str, end: str) -> Any:
    data = {sym: market_service.bars(sym, start, end) for sym in leg["symbols"]}
    eng = BacktestEngine(
        STRATEGY_REGISTRY[leg["strategy"]](leg["params"]),
        data, initial_cash=initial, instruments=_instruments(leg),
    )
    return eng.run()


def _point_at(result, date: str, allocated: float) -> EquityPoint:
    """前向填充取某腿在指定日期的净值（非交易日沿用上一交易日；早于首交易日用分配资金）。

    与组合回测引擎的 _leg_value_series 口径一致（修复 end 落在最后交易日之后净值被重置为
    分配资金的异常），同时保持「组合净值 == 各腿独立运行净值之前向填充求和」的核心不变量。
    """
    nav = {p.date: p.total_value for p in result.equity_curve}
    if date in nav:
        return EquityPoint(date=date, cash=allocated, market_value=nav[date], total_value=nav[date], daily_return=0.0)
    cand = [d for d in nav if d <= date]
    if cand:
        v = nav[max(cand)]
        return EquityPoint(date=date, cash=allocated, market_value=v, total_value=v, daily_return=0.0)
    return EquityPoint(date=date, cash=allocated, market_value=allocated, total_value=allocated, daily_return=0.0)


FUND_LEG = {
    "strategy": "fund_dingtou",
    "params": {"amount": 2000, "redeem_on_last_day": True},
    "symbols": ["TEST.FUND"],
    "asset_types": {"TEST.FUND": "fund"},
    "weight": 1.0,
}
STOCK_LEG = {
    "strategy": "buy_hold",
    "params": {},
    "symbols": ["TEST.STOCK"],
    "asset_types": {"TEST.STOCK": "stock"},
    "weight": 1.0,
}


class TestPortfolioMerge:
    def test_two_leg_combined_equals_independent_sum(self):
        legs = [
            {**FUND_LEG, "weight": 0.5},
            {**STOCK_LEG, "weight": 0.5},
        ]
        initial = 200_000.0
        report = PortfolioBacktest(legs, initial_cash=initial, start=START, end=END).run()

        # 独立运行各腿（按归一化权重分配资金）
        r_fund = _run_leg(FUND_LEG, initial * 0.5, START, END)
        r_stock = _run_leg(STOCK_LEG, initial * 0.5, START, END)

        # 组合曲线每点净值 ≈ 两腿该日净值之和
        for pt in report["equity_curve"]:
            pf = _point_at(r_fund, pt["date"], initial * 0.5)
            ps = _point_at(r_stock, pt["date"], initial * 0.5)
            assert pt["total_value"] == pytest.approx(pf.total_value + ps.total_value, abs=1e-2)

        # 末日组合净值 ≈ 两腿末日净值之和
        last = report["equity_curve"][-1]
        fund_last = r_fund.equity_curve[-1].total_value
        stock_last = r_stock.equity_curve[-1].total_value
        assert last["total_value"] == pytest.approx(fund_last + stock_last, abs=1e-2)

    def test_weights_normalized(self):
        legs = [
            {**FUND_LEG, "weight": 2.0},
            {**STOCK_LEG, "weight": 1.0},
        ]
        report = PortfolioBacktest(legs, initial_cash=300_000, start=START, end=END).run()
        w = [l["weight"] for l in report["legs"]]
        assert sum(w) == pytest.approx(1.0)
        assert w[0] == pytest.approx(2 / 3)
        assert w[1] == pytest.approx(1 / 3)
        assert report["legs"][0]["allocated_cash"] == pytest.approx(200_000)
        assert report["legs"][1]["allocated_cash"] == pytest.approx(100_000)

    def test_first_point_total_equals_independent_sum(self):
        legs = [{**FUND_LEG, "weight": 0.5}, {**STOCK_LEG, "weight": 0.5}]
        initial = 200_000.0
        report = PortfolioBacktest(legs, initial_cash=initial, start=START, end=END).run()
        r_fund = _run_leg(FUND_LEG, initial * 0.5, START, END)
        r_stock = _run_leg(STOCK_LEG, initial * 0.5, START, END)
        first = report["equity_curve"][0]
        pf = _point_at(r_fund, first["date"], initial * 0.5)
        ps = _point_at(r_stock, first["date"], initial * 0.5)
        # 首日组合净值 ≈ 两腿首日净值之和（含交易成本）
        assert first["total_value"] == pytest.approx(pf.total_value + ps.total_value, abs=1e-2)
        # 且不超过初始资金（仅扣交易费）
        assert first["total_value"] <= initial + 1e-6

    def test_allocation_sums_to_one(self):
        legs = [{**FUND_LEG, "weight": 1.0}, {**STOCK_LEG, "weight": 1.0}]
        report = PortfolioBacktest(legs, initial_cash=200_000, start=START, end=END).run()
        total_w = sum(l["weight"] for l in report["legs"])
        assert total_w == pytest.approx(1.0)

    def test_single_leg_equals_weighted_single_run(self):
        legs = [{**FUND_LEG, "weight": 1.0}]
        initial = 150_000.0
        report = PortfolioBacktest(legs, initial_cash=initial, start=START, end=END).run()
        independent = _run_leg(FUND_LEG, initial, START, END)
        assert report["equity_curve"][-1]["total_value"] == pytest.approx(
            independent.equity_curve[-1].total_value, abs=1e-2
        )
        assert report["legs"][0]["final_value"] == pytest.approx(
            independent.equity_curve[-1].total_value, abs=1e-2
        )

    def test_unknown_strategy_raises(self):
        with pytest.raises(Exception):
            PortfolioBacktest(
                [{"strategy": "nope", "symbols": ["TEST.STOCK"], "weight": 1.0}],
                initial_cash=100_000, start=START, end=END,
            ).run()

    def test_empty_legs_raises(self):
        with pytest.raises(Exception):
            PortfolioBacktest([], initial_cash=100_000, start=START, end=END).run()


class TestPortfolioApi:
    def test_run_portfolio_endpoint(self, client):
        resp = client.post(
            "/api/backtest/portfolio",
            json={
                "legs": [
                    {**FUND_LEG, "weight": 0.5},
                    {**STOCK_LEG, "weight": 0.5},
                ],
                "initial_cash": 200_000,
                "start": START,
                "end": END,
                "rebalance": "none",
            },
        )
        assert resp.status_code == 200
        d = resp.json()
        assert d["type"] == "portfolio"
        assert len(d["legs"]) == 2
        assert "equity_curve" in d
        assert "metrics" in d
        assert d["metrics"]["total_return"] is not None
        assert d["initial_cash"] == 200_000

    def test_portfolio_unknown_strategy_422(self, client):
        resp = client.post(
            "/api/backtest/portfolio",
            json={
                "legs": [{"strategy": "nope", "symbols": ["TEST.STOCK"], "weight": 1.0}],
                "initial_cash": 100_000,
                "start": START,
                "end": END,
            },
        )
        assert resp.status_code == 422

    def test_portfolio_rebalance_not_supported_422(self, client):
        resp = client.post(
            "/api/backtest/portfolio",
            json={
                "legs": [{**FUND_LEG, "weight": 1.0}],
                "initial_cash": 100_000,
                "start": START,
                "end": END,
                "rebalance": "monthly",
            },
        )
        assert resp.status_code == 422
