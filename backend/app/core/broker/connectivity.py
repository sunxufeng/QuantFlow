"""券商凭证连通性测试（V1.7）。

不依赖真实凭证即可运行：
- broker=none / 无 api_key → 返回 configured=False，提示待配置；
- broker=simulated → 始终成功（模拟盘，无需外网）；
- 其他券商 → 在凭证齐备时尝试对 base_url 做一次轻量可达性探测，
  凭证未就绪时返回清晰状态，不抛异常（不影响保存）。
"""

from __future__ import annotations

import urllib.request
from typing import Any, Dict


def test_broker_config(cfg: Dict[str, Any]) -> Dict[str, Any]:
    broker = cfg.get("broker", "none")
    api_key = cfg.get("api_key", "")
    base_url = (cfg.get("base_url") or "").strip()

    if broker in (None, "", "none") or not api_key:
        return {
            "ok": False,
            "broker": broker,
            "configured": False,
            "detail": "尚未配置券商凭证（凭证申请中）。配置 API Key 后点击「测试连接」验证。",
        }

    if broker == "simulated":
        return {
            "ok": True,
            "broker": broker,
            "configured": True,
            "detail": "模拟盘模式：无需外部凭证，本地撮合即可运行。",
        }

    # 真实券商：凭证齐备时做可达性探测
    if not base_url:
        return {
            "ok": False,
            "broker": broker,
            "configured": True,
            "detail": "凭证已填写，但缺少 Base URL；补充后重试可达性探测。",
        }

    try:
        url = base_url.rstrip("/") + "/"
        req = urllib.request.Request(
            url,
            method="HEAD",
            headers={"Authorization": f"Bearer {api_key}"},
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            status = resp.status
        return {
            "ok": 200 <= status < 400,
            "broker": broker,
            "configured": True,
            "status": status,
            "detail": f"Base URL 可达（HTTP {status}）。实盘下单接口待凭证就绪后接入。",
        }
    except Exception as exc:  # 网络/证书/超时等均视为不可达，不中断流程
        return {
            "ok": False,
            "broker": broker,
            "configured": True,
            "detail": f"可达性探测失败（不影响保存）：{type(exc).__name__}: {exc}",
        }
