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


class TestPortfolioAttribution:
    """V12 绩效归因：各腿累计贡献之和精确等于组合总收益（再平衡前后均成立）。"""

    def _report(self, rebalance: str) -> Dict[str, Any]:
        legs = [{**FUND_LEG, "weight": 0.5}, {**STOCK_LEG, "weight": 0.5}]
        return PortfolioBacktest(
            legs, initial_cash=200_000, start=START, end=END, rebalance=rebalance
        ).run()

    def test_leg_curves_shape(self):
        report = self._report("none")
        assert "leg_curves" in report
        assert len(report["leg_curves"]) == 2
        n_days = len(report["calendar"])
        for lc in report["leg_curves"]:
            assert len(lc["series"]) == n_days
            assert lc["series"][0]["date"] == report["calendar"][0]

    def test_attribution_sum_equals_total_return_buyhold(self):
        report = self._report("none")
        contrib_sum = sum(b["final_contrib"] for b in report["attribution"]["by_leg"])
        assert contrib_sum == pytest.approx(report["metrics"]["total_return"], abs=1e-4)
        assert report["attribution"]["total_return"] == pytest.approx(
            report["metrics"]["total_return"], abs=1e-6
        )

    def test_attribution_sum_equals_total_return_rebalanced(self):
        # 再平衡下用真实权重还原的归因仍应精确求和到总收益
        report = self._report("M")
        contrib_sum = sum(b["final_contrib"] for b in report["attribution"]["by_leg"])
        assert contrib_sum == pytest.approx(report["metrics"]["total_return"], abs=1e-4)

    def test_attribution_exposed_via_api(self, client):
        resp = client.post(
            "/api/backtest/portfolio",
            json={
                "legs": [{**FUND_LEG, "weight": 0.5}, {**STOCK_LEG, "weight": 0.5}],
                "initial_cash": 200_000,
                "start": START,
                "end": END,
                "rebalance": "none",
            },
        )
        d = resp.json()
        assert "attribution" in d
        assert "leg_curves" in d
        assert len(d["attribution"]["by_leg"]) == 2


class TestPortfolioRiskDecomposition:
    """V13 组合风险分解：各腿风险贡献（年化）之和精确等于组合年化波动。"""

    def _report(self, rebalance: str) -> Dict[str, Any]:
        legs = [{**FUND_LEG, "weight": 0.5}, {**STOCK_LEG, "weight": 0.5}]
        return PortfolioBacktest(
            legs, initial_cash=200_000, start=START, end=END, rebalance=rebalance
        ).run()

    def test_risk_decomposition_shape(self):
        rd = self._report("none")["risk_decomposition"]
        assert "portfolio_vol_annual" in rd
        assert len(rd["per_leg_vol_annual"]) == 2
        assert len(rd["risk_contrib_annual"]) == 2
        assert len(rd["risk_contrib_pct"]) == 2
        assert len(rd["correlation"]) == 2 and len(rd["correlation"][0]) == 2

    def test_risk_contrib_sum_equals_portfolio_vol(self):
        rd = self._report("none")["risk_decomposition"]
        s = sum(rd["risk_contrib_annual"])
        assert s == pytest.approx(rd["portfolio_vol_annual"], abs=1e-4)

    def test_risk_contrib_pct_sums_to_one(self):
        rd = self._report("M")["risk_decomposition"]
        assert sum(rd["risk_contrib_pct"]) == pytest.approx(1.0, abs=1e-6)

    def test_correlation_diagonal_is_one(self):
        rd = self._report("none")["risk_decomposition"]
        for i in range(len(rd["correlation"])):
            assert rd["correlation"][i][i] == pytest.approx(1.0, abs=1e-6)

    def test_single_leg_risk_equals_its_vol(self):
        legs = [{**FUND_LEG, "weight": 1.0}]
        rd = PortfolioBacktest(legs, initial_cash=150_000, start=START, end=END).run()["risk_decomposition"]
        assert rd["risk_contrib_pct"] == [1.0]
        assert rd["portfolio_vol_annual"] == pytest.approx(rd["per_leg_vol_annual"][0], abs=1e-6)

    def test_risk_decomposition_exposed_via_api(self, client):
        resp = client.post(
            "/api/backtest/portfolio",
            json={
                "legs": [{**FUND_LEG, "weight": 0.5}, {**STOCK_LEG, "weight": 0.5}],
                "initial_cash": 200_000,
                "start": START,
                "end": END,
                "rebalance": "none",
            },
        )
        d = resp.json()
        assert "risk_decomposition" in d
        assert len(d["risk_decomposition"]["risk_contrib_annual"]) == 2


# --------------------------------------------------------------------------- #
# V14：基准对比增强 / 参数敏感性 / 组合因子暴露
# --------------------------------------------------------------------------- #
class TestBenchmarkEnhancement:
    def test_metrics_benchmark_alpha_beta_te_ir(self):
        from app.backtest.metrics import PerformanceMetrics
        from app.backtest.engine import EquityPoint

        # 策略与基准完全同收益（含波动）-> beta=1, alpha=0, TE=0, IR=0
        init = 100_000.0
        n = 20
        rets = [0.01 + 0.005 * (i % 2) for i in range(n)]  # 0.01/0.015 交替，有方差
        eq_vals = [init]
        for r in rets:
            eq_vals.append(eq_vals[-1] * (1 + r))
        # equity[i].daily_return 与 benchmark 第 i 段收益对齐（同一收益序列）
        equity = [
            EquityPoint(
                date=f"2024-01-{i+1:02d}", cash=0.0,
                market_value=eq_vals[i + 1], total_value=eq_vals[i + 1],
                daily_return=rets[i],
            )
            for i in range(n)
        ]
        benchmark_values = eq_vals  # 含基准初始值，与策略同源
        m = PerformanceMetrics(equity, init, [], benchmark_values=benchmark_values)
        b = m._compute_attribution()["benchmark"]
        assert b["beta"] == pytest.approx(1.0, abs=1e-6)
        assert b["alpha"] == pytest.approx(0.0, abs=1e-6)
        assert b["tracking_error"] == pytest.approx(0.0, abs=1e-6)
        assert "information_ratio" in b
        assert b["information_ratio"] == pytest.approx(0.0, abs=1e-6)

    def test_run_with_benchmark_exposes_benchmark_block_and_curve(self, client):
        resp = client.post(
            "/api/backtest/run",
            json={
                "strategy": "buy_hold",
                "params": {},
                "symbols": ["TEST.STOCK"],
                "start": START,
                "end": END,
                "benchmark_symbol": "TEST.STOCK",
            },
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()
        bench = d["metrics"]["attribution"]["benchmark"]
        assert set(["benchmark_return", "excess_return", "alpha", "beta",
                    "tracking_error", "information_ratio"]) <= set(bench.keys())
        assert len(d.get("benchmark_curve", [])) >= 2

    def test_run_without_benchmark_has_no_benchmark_block(self, client):
        resp = client.post(
            "/api/backtest/run",
            json={
                "strategy": "buy_hold",
                "params": {},
                "symbols": ["TEST.STOCK"],
                "start": START,
                "end": END,
            },
        )
        d = resp.json()
        assert d.get("benchmark_symbol") is None
        assert d.get("benchmark_curve", []) == []


class TestSensitivity:
    def test_sensitivity_scans_param_and_returns_metric_curve(self, client):
        resp = client.post(
            "/api/backtest/sensitivity",
            json={
                "strategy": "ma_cross",
                "params": {"slow": 20, "symbol": "TEST.STOCK"},
                "param": "fast",
                "values": [3, 5, 8, 10, 15],
                "symbols": ["TEST.STOCK"],
                "start": START,
                "end": END,
                "metric": "total_return",
            },
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert d["param"] == "fast"
        assert d["metric"] == "total_return"
        assert [p["param_value"] for p in d["points"]] == [3, 5, 8, 10, 15]
        # 每个取值都产生了指标（fixture 行情下不会全 None）
        assert all(p["value"] is not None for p in d["points"])

    def test_sensitivity_rejects_unknown_strategy(self, client):
        resp = client.post(
            "/api/backtest/sensitivity",
            json={
                "strategy": "nope",
                "params": {},
                "param": "x",
                "values": [1],
                "symbols": ["TEST.STOCK"],
                "start": START,
                "end": END,
            },
        )
        assert resp.status_code == 422


class TestPortfolioBenchmarkFactor:
    def test_portfolio_benchmark_and_factor_exposure(self, client):
        resp = client.post(
            "/api/backtest/portfolio",
            json={
                "legs": [{**STOCK_LEG, "weight": 0.6}, {**FUND_LEG, "weight": 0.4}],
                "initial_cash": 200_000,
                "start": START,
                "end": END,
                "rebalance": "none",
                "benchmark_symbol": "TEST.STOCK",
            },
        )
        assert resp.status_code == 200, resp.text
        d = resp.json()
        assert len(d.get("benchmark_curve", [])) >= 2
        assert d["benchmark_symbol"] == "TEST.STOCK"
        # 因子暴露结构正确（flat fixture 下因子 IC 可能为 null，仅校验结构）
        fe = d["factor_exposure"]
        assert isinstance(fe, dict)
        assert "factors" in fe and "total_exposure_weight" in fe
        assert isinstance(fe["total_exposure_weight"], (int, float))


class TestFactorExposureAggregation:
    def test_aggregate_factor_exposure_weights_by_leg(self, monkeypatch):
        from app.backtest import portfolio as pf

        def fake_ic(symbols, start, end, window, forward):
            return {
                "factors": ["momentum", "volatility", "sharpe"],
                "results": {
                    "momentum": {"mean_ic": 0.4, "ir": 1.2, "observations": 9},
                    "volatility": {"mean_ic": -0.2, "ir": -0.5, "observations": 9},
                    "sharpe": {"mean_ic": 0.1, "ir": 0.3, "observations": 9},
                },
            }

        monkeypatch.setattr(pf.factor_research, "ic_analysis", fake_ic)

        legs = [
            {"strategy": "buy_hold", "symbols": ["A"], "weight": 1.0},   # sharpe, volatility
            {"strategy": "ma_cross", "symbols": ["B"], "weight": 1.0},   # momentum, mean_reversion
        ]
        out = pf._aggregate_factor_exposure(legs, ["A", "B"], "2024-01-02", "2024-01-29")
        names = {f["factor"] for f in out["factors"]}
        # buy_hold -> sharpe/volatility; ma_cross -> momentum/mean_reversion
        assert "sharpe" in names and "volatility" in names and "momentum" in names
        # 暴露占比归一：各因子暴露权重之和约=1（4 位四舍五入）
        assert out["total_exposure_weight"] == pytest.approx(1.0, abs=1e-3)
        sharpe = next(f for f in out["factors"] if f["factor"] == "sharpe")
        assert sharpe["ic_mean"] == pytest.approx(0.1, abs=1e-6)
        assert sharpe["exposure_weight"] > 0

    def test_aggregate_factor_exposure_no_factors(self):
        from app.backtest import portfolio as pf
        out = pf._aggregate_factor_exposure(
            [{"strategy": "unknown_strat", "symbols": ["A"], "weight": 1.0}],
            ["A"], "2024-01-02", "2024-01-29",
        )
        assert out["factors"] == []
