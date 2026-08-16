"""V106 适配器目录（接口缝汇总）。

- 市场数据源：fixture / tushare / ctp / qmt / crypto —— 含 panda 多源覆盖的接口缝。
- 券商连接器：paper（模拟撮合，内置）/ live（QMT/CTP/通用 REST，复用 engine.live_status）。

每个条目给出：标识、名称、类别、模式、是否已就绪、所需环境变量、提示。
仅做只读汇总，不建立真实连接；真实连接由各适配器在凭证/SDK 就绪后实现。
"""

from __future__ import annotations

from typing import Any, Dict, List


def _market_sources() -> List[Dict[str, Any]]:
    from ..market.sources import (
        CTPDataSource,
        CryptoDataSource,
        LocalDataSource,
        QMTDataSource,
        TushareDataSource,
    )

    def describe(cls, label: str, note: str) -> Dict[str, Any]:
        inst = cls()
        if isinstance(inst, (CTPDataSource, QMTDataSource, CryptoDataSource)):
            configured = inst._is_configured()
            required_env = list(inst.required_env)
            required_sdk = inst.required_sdk
        else:
            configured = True
            required_env = []
            required_sdk = ""
        return {
            "id": inst.name,
            "name": label,
            "kind": "market",
            "mode": "live" if inst.name != "fixture" else "synthetic",
            "configured": configured,
            "required_env": required_env,
            "required_sdk": required_sdk,
            "note": note,
        }

    return [
        describe(LocalDataSource, "合成测试数据（fixture）",
                 "离线演示与回测基准，从不代表真实行情"),
        describe(TushareDataSource, "Tushare 行情",
                 "商业源；配置 QF_TUSHARE_TOKEN 后可用"),
        describe(CTPDataSource, "CTP 期货行情",
                 "上期技术柜台；需 pyctp + CTP 凭证（接口缝）"),
        describe(QMTDataSource, "QMT / 迅投行情",
                 "miniQMT xt_trader；需 xt_trader + QMT 凭证（接口缝）"),
        describe(CryptoDataSource, "数字货币行情",
                 "交易所 REST/WS；需 ccxt + API Key（接口缝）"),
    ]


def _brokers() -> List[Dict[str, Any]]:
    from ..trading import engine

    out: List[Dict[str, Any]] = [
        {
            "id": "paper",
            "name": "模拟撮合（Paper）",
            "kind": "broker",
            "mode": "paper",
            "configured": True,
            "required_env": [],
            "required_sdk": "",
            "note": "内置模拟撮合引擎，无需任何凭证",
        }
    ]
    live = engine.live_status()
    broker = live.get("broker", "none")
    if broker == "virtual":
        # V107：虚拟券商——功能已就绪，接口等价 CTP/QMT
        out.append(
            {
                "id": "virtual",
                "name": "虚拟券商（Virtual）",
                "kind": "broker",
                "mode": "virtual",
                "configured": True,
                "required_env": [],
                "required_sdk": "",
                "note": live.get("message", "等价 CTP/QMT 接口，本地账本撮合，无需凭证/SDK"),
            }
        )
    elif broker not in ("none", "simulated"):
        out.append(
            {
                "id": "live",
                "name": f"实盘（{broker}）",
                "kind": "broker",
                "mode": "live",
                "configured": bool(live.get("live_capable")),
                "required_env": list(live.get("missing", [])),
                "required_sdk": "",
                "note": live.get("message", ""),
            }
        )
    return out


def list_adapters() -> Dict[str, Any]:
    """返回市场源 + 券商连接器的统一目录。"""
    market = _market_sources()
    brokers = _brokers()
    return {
        "market_sources": market,
        "brokers": brokers,
        "summary": {
            "configured_market": sum(1 for m in market if m["configured"]),
            "total_market": len(market),
            "configured_brokers": sum(1 for b in brokers if b["configured"]),
            "total_brokers": len(brokers),
        },
    }
