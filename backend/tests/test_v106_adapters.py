"""V106 适配器目录（市场数据源接口缝 + 券商连接器汇总）。

仅验证「接口缝」契约：外部源在未配置时抛 DataSourceError 并列出所需凭证；
统一目录能汇总市场源与券商（含 panda 多源覆盖）；API 鉴权与结构正确。
"""
import os

import pytest

from app.market.sources import (
    CTPDataSource,
    CryptoDataSource,
    DataSourceError,
    LocalDataSource,
    MarketDataSource,
    QMTDataSource,
    TushareDataSource,
    available_data_sources,
    default_data_source,
)
from app.adapters import list_adapters


# ---------------- 市场数据源接口缝 ----------------
def test_external_sources_raise_when_unconfigured():
    for cls in (CTPDataSource, QMTDataSource, CryptoDataSource):
        src = cls()
        assert isinstance(src, MarketDataSource)
        # 沙箱未配置凭证/SDK -> fetch 必须抛 DataSourceError（接口缝，不假装可用）
        with pytest.raises(DataSourceError):
            src.fetch_daily("TEST.FUTURE", "2024-01-01", "2024-02-01")
        with pytest.raises(DataSourceError):
            src.symbols()


def test_external_sources_is_configured_false(monkeypatch):
    # 清除相关环境变量，确认 _is_configured 为 False
    for v in ("QF_CTP_USER", "QF_QMT_ACCOUNT", "QF_CRYPTO_EXCHANGE",
              "QF_CRYPTO_API_KEY", "QF_CRYPTO_SECRET", "QF_QMT_PATH"):
        monkeypatch.delenv(v, raising=False)
    assert CTPDataSource()._is_configured() is False
    assert QMTDataSource()._is_configured() is False
    assert CryptoDataSource()._is_configured() is False


def _call(provider):
    prev = os.environ.get("QF_MARKET_PROVIDER")
    os.environ["QF_MARKET_PROVIDER"] = provider
    try:
        return default_data_source()
    finally:
        if prev is None:
            os.environ.pop("QF_MARKET_PROVIDER", None)
        else:
            os.environ["QF_MARKET_PROVIDER"] = prev


def test_default_data_source_maps_providers():
    assert isinstance(_call("fixture"), LocalDataSource)
    assert isinstance(_call("tushare"), TushareDataSource)
    assert isinstance(_call("ctp"), CTPDataSource)
    assert isinstance(_call("qmt"), QMTDataSource)
    assert isinstance(_call("crypto"), CryptoDataSource)


def test_available_data_sources_includes_seams():
    names = available_data_sources()
    for n in ("fixture", "tushare", "ctp", "qmt", "crypto"):
        assert n in names


# ---------------- 统一适配器目录 ----------------
def test_list_adapters_structure():
    cat = list_adapters()
    assert set(cat.keys()) >= {"market_sources", "brokers", "summary"}
    ids = {m["id"] for m in cat["market_sources"]}
    assert {"fixture", "tushare", "ctp", "qmt", "crypto"} <= ids
    # 市场源至少含一个就绪项（fixture）
    assert any(m["configured"] for m in cat["market_sources"])
    # 券商必含 paper
    broker_ids = {b["id"] for b in cat["brokers"]}
    assert "paper" in broker_ids
    # 汇总计数一致
    s = cat["summary"]
    assert s["total_market"] == len(cat["market_sources"])
    assert s["total_brokers"] == len(cat["brokers"])


# ---------------- API ----------------
def test_adapters_requires_auth(anon_client):
    r = anon_client.get("/api/adapters")
    assert r.status_code == 401


def test_adapters_ok(client):
    r = client.get("/api/adapters")
    assert r.status_code == 200
    data = r.json()
    assert "market_sources" in data and "brokers" in data
    assert any(m["id"] == "crypto" for m in data["market_sources"])
