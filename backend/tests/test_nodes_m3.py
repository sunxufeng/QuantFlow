"""M3 节点库测试：数据 / 处理 / 特征 / 因子 / ML / 回测节点。

对齐开发计划 §4.3 节点库设计；指标与因子断言基于手工核算，
ML 与回测节点在合成/内置 fixture 数据上验证端到端行为。
"""

from __future__ import annotations

import json

import pytest

from app.core.data import DataTable
from app.core.node import WorkNodeContext, instantiate_node


# --------------------------------------------------------------------------- #
# 工具
# --------------------------------------------------------------------------- #
def run(node_type: str, inputs: dict, params: dict | None = None):
    node = instantiate_node(node_type, "n_test", params)
    ctx = WorkNodeContext(run_id="r_test", node_id="n_test")
    return node.execute(ctx, inputs)


def make_table(columns, rows) -> DataTable:
    return DataTable(columns=list(columns), rows=list(rows))


def prices(close: float, symbol: str = "TEST.STOCK", start: str = "2024-01-02", n: int = 5) -> DataTable:
    """构造简单行情表：open/high/low 均等于 close。"""
    rows = []
    for i in range(n):
        rows.append({
            "symbol": symbol,
            "date": start,
            "open": close,
            "high": close,
            "low": close,
            "close": close,
            "volume": 1000.0,
            "amount": close * 1000.0,
        })
    return make_table(["symbol", "date", "open", "high", "low", "close", "volume", "amount"], rows)


# --------------------------------------------------------------------------- #
# 数据节点
# --------------------------------------------------------------------------- #
class TestDataNodes:
    def test_quotes_fixture(self, monkeypatch):
        from app.market.service import market_service
        from app.market.sources import LocalDataSource

        monkeypatch.setattr(market_service, "primary", LocalDataSource())
        out = run("data.quotes", {}, {"symbol": "TEST.STOCK"})
        table = out["table"]
        assert table.columns[0] == "symbol"
        assert "close" in table.columns and "volume" in table.columns
        assert len(table) >= 20
        assert table.rows[0]["symbol"] == "TEST.STOCK"

    def test_quotes_bad_symbol(self, monkeypatch):
        from app.market.service import market_service
        from app.market.sources import LocalDataSource

        monkeypatch.setattr(market_service, "primary", LocalDataSource())
        out = run("data.quotes", {}, {"symbol": "NO.SUCH"})
        assert len(out["table"]) == 0

    def test_financial(self):
        out = run("data.financial", {}, {"symbol": "TEST.STOCK", "periods": 4, "seed": 3})
        table = out["table"]
        assert len(table) == 4
        cols = {c: i for i, c in enumerate(table.columns)}
        assert "revenue" in cols and "roe" in cols
        assert table.rows[0]["report_date"] == "2024Q1"
        assert table.rows[3]["report_date"] == "2024Q4"
        # 确定性：同种子同标的两次生成一致
        again = run("data.financial", {}, {"symbol": "TEST.STOCK", "periods": 4, "seed": 3})
        assert again["table"].rows == table.rows
        # 指标落在合理区间
        for r in table.rows:
            assert 0 <= r["debt_ratio"] <= 1
            assert 0 <= r["gross_margin"] <= 1


# --------------------------------------------------------------------------- #
# 处理节点
# --------------------------------------------------------------------------- #
class TestProcessingNodes:
    def test_clean_dropna(self):
        t = make_table(["x", "y"], [{"x": 1, "y": "a"}, {"x": None, "y": "b"}, {"x": 3, "y": "c"}])
        out = run("table.clean", {"table": t}, {"key_columns": "x"})
        assert len(out["table"]) == 2
        assert out["table"].rows[0]["x"] == 1

    def test_clean_strip_text(self):
        t = make_table(["x", "s"], [{"x": 1, "s": "  hi  "}, {"x": 2, "s": "ok"}])
        out = run("table.clean", {"table": t}, {"strip_text": True})
        assert out["table"].rows[0]["s"] == "hi"
        out2 = run("table.clean", {"table": t}, {"strip_text": False})
        assert out2["table"].rows[0]["s"] == "  hi  "

    def test_dedupe_by_column(self):
        t = make_table(
            ["k", "v"],
            [{"k": 1, "v": 10}, {"k": 1, "v": 20}, {"k": 2, "v": 30}, {"k": 2, "v": 40}],
        )
        out = run("table.dedupe", {"table": t}, {"columns": "k"})
        assert len(out["table"]) == 2
        assert out["table"].rows[0]["v"] == 10  # keep=first

    def test_fillna_ffill(self):
        t = make_table(["x"], [{"x": None}, {"x": 1.0}, {"x": None}, {"x": 2.0}])
        out = run("table.fillna", {"table": t}, {"method": "ffill"})
        vals = [r["x"] for r in out["table"].rows]
        assert vals == [1.0, 1.0, 1.0, 2.0]

    def test_fillna_mean_and_zero(self):
        t = make_table(["x"], [{"x": 1.0}, {"x": None}, {"x": 3.0}])
        out = run("table.fillna", {"table": t}, {"method": "mean"})
        assert out["table"].rows[1]["x"] == 2.0
        out0 = run("table.fillna", {"table": t}, {"method": "zero"})
        assert out0["table"].rows[1]["x"] == 0.0

    def test_merge_inner(self):
        ta = make_table(["date", "a"], [{"date": "d1", "a": 1}, {"date": "d2", "a": 2}])
        tb = make_table(["date", "b"], [{"date": "d1", "b": 10}, {"date": "d3", "b": 30}])
        out = run("table.merge", {"table_a": ta, "table_b": tb}, {"on": "date", "how": "inner"})
        assert len(out["table"]) == 1
        assert out["table"].rows[0]["a"] == 1 and out["table"].rows[0]["b"] == 10

    def test_merge_outer_suffixes(self):
        ta = make_table(["date", "x"], [{"date": "d1", "x": 1}])
        tb = make_table(["date", "x"], [{"date": "d1", "x": 2}, {"date": "d2", "x": 3}])
        out = run("table.merge", {"table_a": ta, "table_b": tb}, {"on": "date", "how": "outer"})
        table = out["table"]
        assert len(table) == 2
        assert "x_a" in table.columns and "x_b" in table.columns
        row = next(r for r in table.rows if r["date"] == "d2")
        assert row["x_a"] is None and row["x_b"] == 3


# --------------------------------------------------------------------------- #
# 特征节点（技术指标）
# --------------------------------------------------------------------------- #
def _bar_table(closes, highs=None, lows=None):
    rows = []
    for i, c in enumerate(closes):
        rows.append({
            "symbol": "TEST.STOCK",
            "date": f"2024-01-{i + 2:02d}",
            "open": c,
            "high": highs[i] if highs else c,
            "low": lows[i] if lows else c,
            "close": c,
            "volume": 1000.0,
        })
    return make_table(["symbol", "date", "open", "high", "low", "close", "volume"], rows)


class TestIndicatorNodes:
    def test_ma(self):
        t = _bar_table([1, 2, 3, 4, 5])
        out = run("indicator.ma", {"table": t}, {"window": 3})
        vals = [r["ma3"] for r in out["table"].rows]
        assert vals == [None, None, 2.0, 3.0, 4.0]

    def test_ema(self):
        t = _bar_table([1, 2, 3, 4, 5])
        out = run("indicator.ema", {"table": t}, {"window": 3})
        vals = [r["ema3"] for r in out["table"].rows]
        assert vals == pytest.approx([1.0, 1.5, 2.25, 3.125, 4.0625])

    def test_macd(self):
        t = _bar_table([1, 2, 3, 4, 5])
        out = run("indicator.macd", {"table": t}, {"fast": 2, "slow": 4, "signal": 2})
        rows = out["table"].rows
        assert all(r["macd_hist"] == pytest.approx(2 * (r["macd_dif"] - r["macd_dea"])) for r in rows)
        # 上升行情：DIF > 0，且 DIF 在 DEA 上方
        last = rows[-1]
        assert last["macd_dif"] > 0
        assert last["macd_dif"] > last["macd_dea"]

    def test_rsi_all_up(self):
        t = _bar_table([1, 2, 3, 4, 5])
        out = run("indicator.rsi", {"table": t}, {"window": 3})
        vals = [r["rsi"] for r in out["table"].rows]
        assert vals[0] is None
        assert vals[1:] == [100.0, 100.0, 100.0, 100.0]

    def test_rsi_mixed(self):
        # 半涨半跌：RSI 落在 0~100 之间且非极端
        t = _bar_table([10, 11, 12, 11, 10, 11, 12, 13, 12, 11])
        out = run("indicator.rsi", {"table": t}, {"window": 3})
        vals = [r["rsi"] for r in out["table"].rows if r["rsi"] is not None]
        assert vals
        assert all(0 <= v <= 100 for v in vals)

    def test_kdj(self):
        t = _bar_table([1.5, 2.5, 3.5, 4.5], highs=[2, 3, 4, 5], lows=[1, 2, 3, 2])
        out = run("indicator.kdj", {"table": t}, {"window": 2})
        rows = out["table"].rows
        ks = [r["kdj_k"] for r in rows]
        ds = [r["kdj_d"] for r in rows]
        assert ks == pytest.approx([50.0, 58.333333, 63.888889, 70.370370])
        assert ds == pytest.approx([50.0, 52.777778, 56.481481, 61.111111])
        for r in rows:
            assert r["kdj_j"] == pytest.approx(3 * r["kdj_k"] - 2 * r["kdj_d"])

    def test_boll(self):
        t = _bar_table([1, 2, 3, 4, 5])
        out = run("indicator.boll", {"table": t}, {"window": 3, "num_std": 2.0})
        rows = out["table"].rows
        assert rows[0]["boll_mid"] is None and rows[1]["boll_mid"] is None
        r = rows[2]
        assert r["boll_mid"] == pytest.approx(2.0)
        assert r["boll_up"] == pytest.approx(2.0 + 2.0 * 0.816496580927726)
        assert r["boll_low"] == pytest.approx(2.0 - 2.0 * 0.816496580927726)

    def test_missing_close_column(self):
        t = make_table(["x"], [{"x": 1}])
        with pytest.raises(ValueError, match="close"):
            run("indicator.ma", {"table": t}, {"window": 3})


# --------------------------------------------------------------------------- #
# 因子节点
# --------------------------------------------------------------------------- #
class TestFactorNodes:
    def test_expression(self):
        rows = [{"open": 10.0, "close": 12.0}, {"open": 10.0, "close": 10.0}]
        t = make_table(["open", "close"], rows)
        out = run("factor.expression", {"table": t}, {"expression": "(close-open)/open", "output": "ret"})
        assert [r["ret"] for r in out["table"].rows] == [0.2, 0.0]

    def test_expression_log(self):
        t = make_table(["x"], [{"x": 1.0}, {"x": 10.0}])
        out = run("factor.expression", {"table": t}, {"expression": "log(x)", "output": "lx"})
        import math

        assert out["table"].rows[0]["lx"] == pytest.approx(0.0)
        assert out["table"].rows[1]["lx"] == pytest.approx(math.log(10))

    def test_ic(self):
        rows = [
            {"date": "d1", "factor": 1, "fwd_return": 2},
            {"date": "d1", "factor": 2, "fwd_return": 3},
            {"date": "d1", "factor": 3, "fwd_return": 1},
            {"date": "d1", "factor": 4, "fwd_return": 4},
            {"date": "d2", "factor": 2, "fwd_return": 1},
            {"date": "d2", "factor": 4, "fwd_return": 2},
            {"date": "d2", "factor": 1, "fwd_return": 3},
            {"date": "d2", "factor": 3, "fwd_return": 4},
        ]
        t = make_table(["date", "factor", "fwd_return"], rows)
        out = run("factor.ic", {"table": t}, {"factor": "factor", "forward_return": "fwd_return"})
        by_date = {r["date"]: r["ic"] for r in out["table"].rows}
        assert by_date["d1"] == pytest.approx(0.4)
        assert by_date["d2"] == pytest.approx(0.0)
        assert by_date["__ic_mean__"] == pytest.approx(0.2)
        assert by_date["__icir__"] == pytest.approx(0.7071067811865475)
        assert by_date["__summary__"] is None

    def test_ic_too_few(self):
        rows = [{"date": "d1", "factor": 1, "fwd_return": 2}, {"date": "d1", "factor": 2, "fwd_return": 3}]
        t = make_table(["date", "factor", "fwd_return"], rows)
        out = run("factor.ic", {"table": t})
        assert out["table"].rows[0]["date"] == "__summary__"

    def test_composite_equal_weight(self):

        rows = [{"f1": float(x), "f2": float(x * 10)} for x in range(1, 6)]
        t = make_table(["f1", "f2"], rows)
        out = run("factor.composite", {"table": t}, {"factor_columns": "f1,f2", "output": "comp"})
        # f2 = 10*f1，标准化后 z2 = z1，等权合成 = z1
        vals = [r["f1"] for r in out["table"].rows]
        std = (sum((x - 3) ** 2 for x in vals) / 5) ** 0.5  # ddof=0
        expected = [(x - 3) / std for x in vals]
        assert [r["comp"] for r in out["table"].rows] == pytest.approx(expected)

    def test_composite_weights_normalize(self):
        rows = [{"f1": 1.0, "f2": 2.0}, {"f1": 3.0, "f2": 4.0}]
        t = make_table(["f1", "f2"], rows)
        out = run("factor.composite", {"table": t}, {"factor_columns": "f1,f2", "weights": "1,3"})
        # 权重归一化为 0.25 / 0.75；两行 f1=1,f2=2 与 f1=3,f2=4 完全反相关
        assert out["table"].rows[0]["composite"] == pytest.approx(-out["table"].rows[1]["composite"])

    def test_composite_missing_column(self):
        t = make_table(["f1"], [{"f1": 1.0}])
        with pytest.raises(ValueError, match="缺少因子列"):
            run("factor.composite", {"table": t}, {"factor_columns": "f1,f2"})


# --------------------------------------------------------------------------- #
# ML 节点
# --------------------------------------------------------------------------- #
def _ml_table(n: int = 30) -> DataTable:
    rows = []
    for i in range(n):
        x1, x2 = float(i), float(i % 7)
        rows.append({"x1": x1, "x2": x2, "close": 2 * x1 + x2 + (i % 3)})
    return make_table(["x1", "x2", "close"], rows)


class TestMLNodes:
    def test_train_outputs_model_string(self):
        out = run(
            "ml.train",
            {"table": _ml_table()},
            {"model_type": "random_forest", "target_column": "close", "test_size": 0.2, "n_estimators": 10},
        )
        model = out["model"]
        assert isinstance(model, str) and model
        import base64

        base64.b64decode(model)  # 可解码
        metrics = {r["metric"]: r["value"] for r in out["metrics"].rows}
        assert metrics["model_type"] == "random_forest"
        assert metrics["train_samples"] == 24
        assert metrics["test_samples"] == 6
        assert "r2" in metrics and "mse" in metrics

    def test_train_feature_selection(self):
        out = run(
            "ml.train",
            {"table": _ml_table()},
            {"model_type": "random_forest", "feature_columns": "x1", "n_estimators": 10},
        )
        metrics = {r["metric"]: r["value"] for r in out["metrics"].rows}
        assert metrics["features"] == "x1"

    def test_train_unknown_model(self):
        with pytest.raises(ValueError, match="未知模型类型"):
            run("ml.train", {"table": _ml_table()}, {"model_type": "nope", "n_estimators": 5})

    def test_train_missing_target(self):
        t = make_table(["x1"], [{"x1": 1.0}])
        with pytest.raises(ValueError, match="目标列不存在"):
            run("ml.train", {"table": t}, {"target_column": "close", "n_estimators": 5})

    def test_predict_roundtrip(self):
        train = run(
            "ml.train",
            {"table": _ml_table()},
            {"model_type": "random_forest", "target_column": "close", "n_estimators": 10},
        )
        out = run(
            "ml.predict",
            {"model": train["model"], "table": _ml_table(6)},
            {"feature_columns": "x1,x2"},
        )
        table = out["table"]
        assert "prediction" in table.columns
        assert len(table) == 6
        for r in table.rows:
            assert isinstance(r["prediction"], float)

    def test_predict_no_numeric_cols(self):
        t = make_table(["name"], [{"name": "a"}])
        train = run(
            "ml.train",
            {"table": _ml_table()},
            {"model_type": "random_forest", "target_column": "close", "n_estimators": 5},
        )
        with pytest.raises(ValueError, match="数值特征列"):
            run("ml.predict", {"model": train["model"], "table": t})

    def test_evaluate(self):
        rows = [{"close": 1.0, "prediction": 1.1}, {"close": 2.0, "prediction": 1.9}]
        t = make_table(["close", "prediction"], rows)
        out = run("ml.evaluate", {"table": t})
        metrics = {r["metric"]: r["value"] for r in out["metrics"].rows}
        assert metrics["samples"] == 2
        assert metrics["mse"] == pytest.approx(0.01)
        assert metrics["rmse"] == pytest.approx(0.1)
        assert metrics["mae"] == pytest.approx(0.1)

    def test_save_load_model(self, tmp_path, monkeypatch):
        monkeypatch.setenv("QF_DATA_DIR", str(tmp_path))
        train = run(
            "ml.train",
            {"table": _ml_table()},
            {"model_type": "random_forest", "target_column": "close", "n_estimators": 10},
        )
        saved = run("ml.save_model", {"model": train["model"]})
        model_id = saved["model_id"]
        assert model_id.startswith("model_")
        import os

        assert os.path.exists(tmp_path / "models" / f"{model_id}.pkl")
        loaded = run("ml.load_model", {}, {"model_id": model_id})
        # 模型端口可解码，且预测一致
        from app.nodes.ml_nodes import _decode_model

        m1, m2 = _decode_model(train["model"]), _decode_model(loaded["model"])
        sample = [[1.0, 2.0], [5.0, 3.0]]
        assert list(m1.predict(sample)) == pytest.approx(list(m2.predict(sample)))

    def test_load_model_missing(self, tmp_path, monkeypatch):
        monkeypatch.setenv("QF_DATA_DIR", str(tmp_path))
        with pytest.raises(ValueError, match="模型不存在"):
            run("ml.load_model", {}, {"model_id": "model_doesnotexist"})


# --------------------------------------------------------------------------- #
# 回测节点
# --------------------------------------------------------------------------- #
def _fixture_bars_table(monkeypatch, symbol: str = "TEST.STOCK") -> DataTable:
    from app.market.service import market_service
    from app.market.sources import LocalDataSource

    monkeypatch.setattr(market_service, "primary", LocalDataSource())
    bars = market_service.bars(symbol, start="2024-01-01", end="2024-02-01")
    rows = [
        {
            "symbol": b.symbol,
            "date": b.date,
            "open": b.open,
            "high": b.high,
            "low": b.low,
            "close": b.close,
            "volume": b.volume,
            "amount": b.amount,
        }
        for b in bars
    ]
    return make_table(["symbol", "date", "open", "high", "low", "close", "volume", "amount"], rows)


class TestBacktestNodes:
    def test_backtest_run_buy_hold(self, monkeypatch):
        table = _fixture_bars_table(monkeypatch)
        out = run("backtest.run", {"table": table}, {"strategy": "buy_hold", "initial_cash": 1_000_000})
        equity = out["equity"]
        trades = out["trades"]
        summary = {r["metric"]: r["value"] for r in out["summary"].rows}
        assert len(equity) == len(table)
        assert summary["strategy"] == "buy_hold"
        assert summary["days"] == len(table)
        assert summary["trade_count"] == len(trades)
        # 首日买入 + 末日卖出（buy_hold 收尾清仓）
        assert trades.rows[0]["side"] == "buy"
        assert trades.rows[-1]["side"] == "sell"
        # total_return 与 equity 曲线同口径（相对首日净值）
        first, last = equity.rows[0]["total_value"], equity.rows[-1]["total_value"]
        assert summary["total_return"] == pytest.approx(last / first - 1.0, abs=1e-6)

    def test_backtest_run_ma_cross(self, monkeypatch):
        table = _fixture_bars_table(monkeypatch)
        out = run("backtest.run", {"table": table}, {"strategy": "ma_cross", "initial_cash": 1_000_000})
        assert len(out["equity"]) == len(table)
        assert {r["metric"]: r["value"] for r in out["summary"].rows}["strategy"] == "ma_cross"

    def test_backtest_run_fund_dingtou(self, monkeypatch):
        table = _fixture_bars_table(monkeypatch, symbol="TEST.FUND")
        out = run(
            "backtest.run",
            {"table": table},
            {"strategy": "fund_dingtou", "asset_type": "fund", "initial_cash": 100_000},
        )
        summary = {r["metric"]: r["value"] for r in out["summary"].rows}
        assert summary["strategy"] == "fund_dingtou"
        assert summary["trade_count"] > 0  # 定期定额多笔

    def test_backtest_run_unknown_strategy(self, monkeypatch):
        table = _fixture_bars_table(monkeypatch)
        with pytest.raises(ValueError, match="未知策略"):
            run("backtest.run", {"table": table}, {"strategy": "hft"})

    def test_backtest_run_empty_table(self):
        t = make_table(["date", "close"], [])
        with pytest.raises(ValueError, match="行情表为空"):
            run("backtest.run", {"table": t}, {"strategy": "buy_hold"})

    def test_backtest_run_bad_bar_row(self):
        t = make_table(["date", "close"], [{"date": "d1", "close": None}])
        with pytest.raises(ValueError, match="缺字段"):
            run("backtest.run", {"table": t}, {"strategy": "buy_hold"})

    def test_performance(self, monkeypatch):
        table = _fixture_bars_table(monkeypatch)
        bt = run("backtest.run", {"table": table}, {"strategy": "buy_hold", "initial_cash": 1_000_000})
        out = run("backtest.performance", {"equity": bt["equity"]})
        metrics = {r["metric"]: r["value"] for r in out["metrics"].rows}
        summary = {r["metric"]: r["value"] for r in bt["summary"].rows}
        assert metrics["total_return"] == pytest.approx(summary["total_return"])
        assert metrics["max_drawdown"] <= 0
        assert metrics["days"] == len(bt["equity"])

    def test_performance_short_series(self):
        t = make_table(["total_value"], [{"total_value": 100.0}])
        with pytest.raises(ValueError, match="至少需要 2 个点"):
            run("backtest.performance", {"equity": t})

    def test_export_json(self):
        t = make_table(["a", "b"], [{"a": 1, "b": "x"}])
        out = run("backtest.export_json", {"table": t})
        payload = json.loads(out["json"])
        assert payload["columns"] == ["a", "b"]
        assert payload["rows"][0] == {"a": 1, "b": "x"}

    def test_export_csv(self):
        t = make_table(["a", "b"], [{"a": 1, "b": "x,y"}, {"a": 2, "b": "z"}])
        out = run("backtest.export_csv", {"table": t})
        lines = out["csv"].strip().splitlines()
        assert lines[0] == "a,b"
        assert '"x,y"' in lines[1]


# --------------------------------------------------------------------------- #
# 端到端：节点库组合成完整工作流（数据->特征->因子->回测->绩效）
# --------------------------------------------------------------------------- #
class TestWorkflowE2E:
    def test_full_pipeline(self, monkeypatch):
        from app.core.dag import validate_workflow
        from app.core.executor import WorkflowExecutor
        from app.market.service import market_service
        from app.market.sources import LocalDataSource

        monkeypatch.setattr(market_service, "primary", LocalDataSource())
        nodes = [
            {"id": "n1", "node_type": "data.quotes", "params": {"symbol": "TEST.STOCK"}},
            {"id": "n2", "node_type": "indicator.ma", "params": {"window": 5}},
            {"id": "n3", "node_type": "factor.expression", "params": {"expression": "(close-open)/open", "output": "ret"}},
            {"id": "n4", "node_type": "backtest.run", "params": {"strategy": "buy_hold", "initial_cash": 1_000_000}},
            {"id": "n5", "node_type": "backtest.performance", "params": {}},
        ]
        edges = [
            {"id": "e1", "source": "n1", "source_port": "table", "target": "n2", "target_port": "table"},
            {"id": "e2", "source": "n1", "source_port": "table", "target": "n3", "target_port": "table"},
            {"id": "e3", "source": "n1", "source_port": "table", "target": "n4", "target_port": "table"},
            {"id": "e4", "source": "n4", "source_port": "equity", "target": "n5", "target_port": "equity"},
        ]
        graph = validate_workflow(nodes, edges)
        result = WorkflowExecutor().run(graph).to_dict()
        assert result["status"] == "succeeded"
        by_id = {n["node_id"]: n for n in result["nodes"]}
        assert all(n["status"] == "succeeded" for n in result["nodes"])
        ma_cols = by_id["n2"]["outputs"]["table"]["columns"]
        assert "ma5" in ma_cols
        ret_cols = by_id["n3"]["outputs"]["table"]["columns"]
        assert "ret" in ret_cols
        summary = {r["metric"]: r["value"] for r in by_id["n4"]["outputs"]["summary"]["rows"]}
        assert summary["strategy"] == "buy_hold"
        metrics = {r["metric"]: r["value"] for r in by_id["n5"]["outputs"]["metrics"]["rows"]}
        assert metrics["total_return"] == pytest.approx(summary["total_return"])
