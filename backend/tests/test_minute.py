"""分钟级行情与回测（V1.2）。

覆盖：
- fixture 合成分钟线（确定性、聚合回日线）
- 引擎分钟级回测（时间轴按 datetime 推进、净值曲线逐根）
- 频率一致性校验（混合频率 / 基金分钟级 报错）
- 数据服务与 API 的 interval 透传
"""

from __future__ import annotations

from collections import defaultdict

import pytest
from fastapi.testclient import TestClient

from app.api import backtest as backtest_api
from app.backtest.engine import BacktestEngine, BacktestError
from app.backtest.strategies import STRATEGY_REGISTRY
from app.main import app
from app.market.models import INTERVAL_MINUTE, Instrument
from app.market.service import MarketService
from app.market.sources import LocalDataSource

SRC = LocalDataSource()
START, END = "2024-01-02", "2024-01-29"
BARS_PER_DAY = len(LocalDataSource.MINUTE_SESSION)


# --------------------------------------------------------------------------- #
# fixture 合成分钟线
# --------------------------------------------------------------------------- #
class TestMinuteFixture:
    def test_minute_shape(self):
        bars = SRC.fetch_minute("TEST.STOCK", START, END)
        daily = SRC.fetch_daily("TEST.STOCK", START, END)
        assert len(bars) == len(daily) * BARS_PER_DAY
        assert all(b.interval == INTERVAL_MINUTE for b in bars)
        assert all(b.datetime and b.datetime.startswith("2024-01-") for b in bars)
        # 同标的同日 10 根，datetime 唯一且升序
        dts = [b.datetime for b in bars]
        assert dts == sorted(dts)
        assert len(set(dts)) == len(dts)

    def test_minute_last_close_equals_daily(self):
        daily = SRC.fetch_daily("TEST.STOCK", START, END)
        daily_close = {b.date: b.close for b in daily}
        minute = SRC.fetch_minute("TEST.STOCK", START, END)
        last = {}
        for b in minute:
            last[b.date] = b.close  # 后写覆盖，保留当日末根
        assert set(last) == set(daily_close)
        for d, c in daily_close.items():
            assert last[d] == pytest.approx(c, rel=1e-6)

    def test_minute_deterministic(self):
        a = SRC.fetch_minute("TEST.STOCK", START, END)
        b = SRC.fetch_minute("TEST.STOCK", START, END)
        assert [x.to_dict() for x in a] == [x.to_dict() for x in b]


# --------------------------------------------------------------------------- #
# 引擎分钟级回测
# --------------------------------------------------------------------------- #
class TestMinuteEngine:
    def _minute_data(self, symbol="TEST.STOCK"):
        return {symbol: SRC.fetch_minute(symbol, START, END)}

    def test_buy_hold_minute_curve_length(self):
        data = self._minute_data()
        result = BacktestEngine(
            STRATEGY_REGISTRY["buy_hold"]({"shares": 1000}), data
        ).run()
        assert len(result.equity_curve) == len(data["TEST.STOCK"])
        # 首点 datetime 形如 2024-01-02 09:30:00
        assert result.equity_curve[0].date == "2024-01-02 09:30:00"
        # 买入 + 末根卖出
        assert len(result.trades) == 2

    def test_ma_cross_minute_runs(self):
        data = self._minute_data()
        result = BacktestEngine(
            STRATEGY_REGISTRY["ma_cross"]({"fast": 5, "slow": 20}), data
        ).run()
        assert len(result.equity_curve) == len(data["TEST.STOCK"])
        # 净值曲线单调有值
        assert all(
            p.total_value > 0 for p in result.equity_curve
        )

    def test_mixed_interval_raises(self):
        daily = SRC.fetch_daily("TEST.STOCK", START, START)
        minute = SRC.fetch_minute("TEST.STOCK", START, START)
        with pytest.raises(BacktestError):
            BacktestEngine(
                STRATEGY_REGISTRY["buy_hold"]({}), {"A.SH": daily + minute}
            ).run()

    def test_fund_minute_raises(self):
        data = {"TEST.FUND": SRC.fetch_minute("TEST.FUND", START, END)}
        instruments = {
            "TEST.FUND": Instrument("TEST.FUND", "fund", exchange="", market="fund")
        }
        with pytest.raises(BacktestError):
            BacktestEngine(
                STRATEGY_REGISTRY["buy_hold"]({}), data, instruments=instruments
            ).run()


# --------------------------------------------------------------------------- #
# 数据服务 interval 透传
# --------------------------------------------------------------------------- #
class TestMinuteService:
    def test_service_minute(self):
        svc = MarketService(primary=LocalDataSource())
        bars = svc.bars("TEST.STOCK", START, END, interval="minute")
        assert len(bars) == 20 * BARS_PER_DAY
        assert all(b.interval == INTERVAL_MINUTE for b in bars)
        # 缓存命中：第二次调用返回同等数据
        bars2 = svc.bars("TEST.STOCK", START, END, interval="minute")
        assert [b.to_dict() for b in bars] == [b.to_dict() for b in bars2]


# --------------------------------------------------------------------------- #
# API：interval 透传
# --------------------------------------------------------------------------- #
@pytest.fixture(autouse=True)
def _fake_market(monkeypatch, tmp_path):
    def fake_bars(symbol, start=None, end=None, interval="daily", use_cache=True):
        s, e = start or "2024-01-01", end or "2024-02-01"
        if interval == "minute":
            return SRC.fetch_minute(symbol, s, e)
        return SRC.fetch_daily(symbol, s, e)

    monkeypatch.setattr(backtest_api.market_service, "bars", fake_bars)
    monkeypatch.setattr(
        backtest_api, "report_store", backtest_api.BacktestReportStore(report_dir=str(tmp_path))
    )


class TestRunMinuteApi:
    def setup_method(self):
        self.client = TestClient(app)

    def test_run_minute(self):
        resp = self.client.post("/api/backtest/run", json={
            "strategy": "buy_hold",
            "params": {"shares": 1000},
            "symbols": ["TEST.STOCK"],
            "start": START,
            "end": END,
            "interval": "minute",
        })
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert len(body["equity_curve"]) == 20 * BARS_PER_DAY
        assert body["equity_curve"][0]["date"] == "2024-01-02 09:30:00"

    def test_invalid_interval_rejected(self):
        resp = self.client.post("/api/backtest/run", json={
            "strategy": "buy_hold",
            "params": {},
            "symbols": ["TEST.STOCK"],
            "start": START,
            "end": END,
            "interval": "hourly",
        })
        assert resp.status_code == 422
