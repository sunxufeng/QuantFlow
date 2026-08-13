"""N3 独立因子分析库单测：stats / transform / analyzer。

覆盖与既有 factor.ic / factor.composite 节点一致的口径（IC=0.4、ICIR=0.7071）。
"""


import pandas as pd
import pytest

from app.factors import (
    FactorAnalyzer,
    composite_factors,
    expression_factor,
    ic_decay,
    ic_series,
    ic_summary,
    rank_ic,
    winsorize,
    zscore,
)


# --------------------------------------------------------------------------- #
# 与 factor.ic 节点一致的已知数据
# --------------------------------------------------------------------------- #
def _ic_table():
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
    return pd.DataFrame(rows)


def test_rank_ic_known_value():
    df = _ic_table()
    d1 = df[df.date == "d1"]
    assert rank_ic(d1["factor"], d1["fwd_return"]) == pytest.approx(0.4)
    d2 = df[df.date == "d2"]
    assert rank_ic(d2["factor"], d2["fwd_return"]) == pytest.approx(0.0)


def test_rank_ic_too_few_returns_none():
    s = pd.Series([1.0, 2.0])
    r = pd.Series([2.0, 1.0])
    assert rank_ic(s, r) is None


def test_ic_series_per_date():
    df = _ic_table()
    series = ic_series(df, "factor", "fwd_return", "date")
    by_date = {d: ic for d, ic in series}
    assert by_date["d1"] == pytest.approx(0.4)
    assert by_date["d2"] == pytest.approx(0.0)


def test_ic_summary_ir_and_t():
    summary = ic_summary([0.4, 0.0])
    assert summary["mean"] == pytest.approx(0.2)
    assert summary["ir"] == pytest.approx(0.7071067811865475)
    assert summary["n"] == 2
    assert summary["t_stat"] == pytest.approx(1.0)
    assert summary["pct_positive"] == pytest.approx(0.5)


def test_ic_summary_empty():
    summary = ic_summary([])
    assert summary["n"] == 0
    assert summary["mean"] is None
    assert summary["ir"] is None


def test_ic_decay_requires_date():
    df = _ic_table().drop(columns=["date"])
    assert ic_decay(df, "factor", "fwd_return", None, 3) == []


def test_ic_decay_returns_lags():
    df = _ic_table()
    decay = ic_decay(df, "factor", "fwd_return", "date", 2)
    assert [d["lag"] for d in decay] == [1, 2]
    for d in decay:
        assert "ic" in d


# --------------------------------------------------------------------------- #
# transform
# --------------------------------------------------------------------------- #
def test_zscore_ddof0_matches_node():
    vals = [float(x) for x in range(1, 6)]
    s = pd.Series(vals)
    std = (sum((x - 3) ** 2 for x in vals) / 5) ** 0.5  # ddof=0
    expected = [(x - 3) / std for x in vals]
    assert list(zscore(s)) == pytest.approx(expected)


def test_composite_equal_weight_matches_node():
    rows = [{"f1": float(x), "f2": float(x * 10)} for x in range(1, 6)]
    df = pd.DataFrame(rows)
    out = composite_factors(df, ["f1", "f2"])
    std = (sum((x - 3) ** 2 for x in range(1, 6)) / 5) ** 0.5
    expected = [(x - 3) / std for x in range(1, 6)]
    assert list(out) == pytest.approx(expected)


def test_composite_weights_normalize():
    df = pd.DataFrame([{"f1": 1.0, "f2": 2.0}, {"f1": 3.0, "f2": 4.0}])
    out = composite_factors(df, ["f1", "f2"], [1, 3])
    # 完全反相关，归一化权重 0.25/0.75 → 两行互为相反数
    assert out.iloc[0] == pytest.approx(-out.iloc[1])


def test_composite_missing_column():
    df = pd.DataFrame([{"f1": 1.0}])
    with pytest.raises(ValueError, match="至少需要一个因子列"):
        composite_factors(df, [])


def test_winsorize_clips():
    s = pd.Series([0.0, 1.0, 2.0, 3.0, 100.0])
    w = winsorize(s, 0.2)
    # 上界被截断到 0.8 分位（≈22.4），不再出现 100 极端值
    assert w.max() == pytest.approx(s.quantile(0.8))
    assert w.max() < 100


def test_expression_factor():
    df = pd.DataFrame([{"open": 10.0, "close": 12.0}, {"open": 10.0, "close": 10.0}])
    out = expression_factor(df, "(close-open)/open", "ret")
    assert list(out["ret"]) == pytest.approx([0.2, 0.0])


# --------------------------------------------------------------------------- #
# analyzer integration
# --------------------------------------------------------------------------- #
def test_analyzer_structure():
    df = _ic_table()
    report = FactorAnalyzer().analyze(df, "factor", "fwd_return", "date", n_quantiles=4, max_lag=2)
    assert report["ic"]["mean"] == pytest.approx(0.2)
    assert report["ic"]["ir"] == pytest.approx(0.7071067811865475)
    assert len(report["ic_decay"]) == 2
    assert "by_quantile" in report["quantile_returns"]
    assert report["quantile_returns"]["long_short"] is not None


def test_analyzer_no_date_single_cross_section():
    df = _ic_table().drop(columns=["date"])
    report = FactorAnalyzer().analyze(df, "factor", "fwd_return", None)
    assert report["ic"]["n"] >= 1
    # 无时间维度 → 自相关为空
    assert report["factor_autocorrelation"] is None
