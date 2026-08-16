"""实盘连接器注册与分发（V31）。

按券商设置里的 ``broker`` 字段，返回对应的连接器实例（QMT / CTP / 通用 REST）。
连接器全部「按需激活」：缺少 SDK 或凭证时 ``is_configured()`` 为 False，
``GatewayNotConfigured`` 已由连接器内部统一抛出，调用方无需感知具体券商。
"""

from __future__ import annotations

from typing import Any, Dict, Optional


def get_live_connector(cfg: Dict[str, Any]):
    """根据 broker 配置返回连接器实例；未知/未配置返回 None。"""
    broker = (cfg.get("broker") or "none").lower()
    if broker == "qmt":
        from .qmt import QmtConnector
        return QmtConnector()
    if broker == "ctp":
        from .ctp import CtpConnector
        return CtpConnector()
    if broker in ("virtual", "simulated", "simulated-broker"):
        # V107：虚拟券商——接口等价 CTP/QMT，本地账本撮合，无需凭证/SDK
        from .virtual import VirtualBrokerConnector
        return VirtualBrokerConnector()
    # universal/easytrade/xuntou 为通用 REST 类柜台，无独立连接器类，
    # 由 LiveExecutionGateway 通用实现（凭证齐备即视为可配置），故返回 None。
    return None


def connector_status(cfg: Dict[str, Any]) -> Dict[str, Any]:
    """返回连接器就绪详情，供 live_status 展示。"""
    broker = (cfg.get("broker") or "none").lower()
    conn = get_live_connector(cfg)
    if conn is None:
        return {
            "broker": broker,
            "connector": None,
            "configured": False,
            "message": "未选择实盘券商（none/simulated）",
        }
    try:
        configured = conn.is_configured()
    except Exception:
        configured = False
    return {
        "broker": broker,
        "connector": conn.name,
        "configured": configured,
        "message": "虚拟券商已就绪（本地账本撮合，无需凭证）" if conn.name == "virtual"
        else ("实盘连接器已就绪" if configured else "连接器已识别，但缺少 SDK 或凭证（见券商设置）"),
    }
