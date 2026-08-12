"""N5 通知模块测试：渠道发送 / 服务持久化 / API 鉴权与配置。

用 monkeypatch 替换 httpx.post，避免真实外发网络请求。
"""

import base64
import hashlib
import hmac

import httpx
import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.notifications import channels
from app.notifications.base import NotificationMessage
from app.notifications.service import notification_service

client = TestClient(app)


# --------------------------------------------------------------------------- #
# 渠道发送（monkeypatch httpx.post）
# --------------------------------------------------------------------------- #
def test_webhook_channel_send(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=10.0):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    ch = channels.WebhookChannel(name="wh", config={"url": "https://example.com/hook"})
    ch.send(NotificationMessage(title="t", content="c", level="success", fields={"run_id": "r1"}))
    assert captured["url"] == "https://example.com/hook"
    assert captured["json"]["title"] == "t"
    assert captured["json"]["fields"]["run_id"] == "r1"


def test_webhook_channel_non_2xx_raises(monkeypatch):
    def fake_post(url, json=None, timeout=10.0):
        return httpx.Response(500, text="boom")

    monkeypatch.setattr(httpx, "post", fake_post)
    ch = channels.WebhookChannel(name="wh", config={"url": "https://example.com/hook"})
    with pytest.raises(RuntimeError):
        ch.send(NotificationMessage(title="t", content="c"))


def test_feishu_channel_sign(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=10.0):
        captured["url"] = url
        captured["json"] = json
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    secret = "mysecret"
    ch = channels.FeishuChannel(name="fs", config={"webhook": "https://feishu/hook", "secret": secret})
    ch.send(NotificationMessage(title="运行成功", content="ok"))
    body = captured["json"]
    assert body["msg_type"] == "text"
    assert "timestamp" in body and "sign" in body
    # 复算签名校验
    string_to_sign = f"{body['timestamp']}\n{secret}"
    expected = base64.b64encode(
        hmac.new(secret.encode(), string_to_sign.encode(), hashlib.sha256).digest()
    ).decode()
    assert body["sign"] == expected


def test_feishu_channel_without_secret(monkeypatch):
    captured = {}

    def fake_post(url, json=None, timeout=10.0):
        captured["json"] = json
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    ch = channels.FeishuChannel(name="fs", config={"webhook": "https://feishu/hook"})
    ch.send(NotificationMessage(title="t", content="c"))
    assert "sign" not in captured["json"]


def test_build_channel_unknown():
    with pytest.raises(ValueError, match="未知通知渠道"):
        channels.build_channel("telegram", "x", {})


# --------------------------------------------------------------------------- #
# 服务持久化 + 触发
# --------------------------------------------------------------------------- #
def _register(username, password="secret123"):
    return client.post(
        "/api/auth/register", json={"username": username, "password": password}
    ).json()["token"]


def _auth(username, password="secret123"):
    return {"Authorization": f"Bearer {_register(username, password)}"}


def test_service_configure_list_remove(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=10.0):
        calls.append(json)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)

    rec = notification_service.configure("webhook", "ci", {"url": "https://x/h"})
    assert rec["id"]
    assert notification_service.get(rec["id"])["type"] == "webhook"
    # 触发运行完成通知（应调用 webhook）
    notification_service.notify_run_finished(rec["id"], "测试流", "SUCCEEDED")
    assert len(calls) == 1
    assert calls[0]["level"] == "success"
    # 删除
    assert notification_service.remove(rec["id"]) is True
    assert notification_service.get(rec["id"]) is None


def test_notify_skips_disabled(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=10.0):
        calls.append(json)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    rec = notification_service.configure("webhook", "ci2", {"url": "https://x/h"})
    notification_service.set_enabled(rec["id"], False)
    notification_service.notify_run_finished(rec["id"], "流", "SUCCEEDED")
    assert len(calls) == 0  # 禁用渠道不发送


# --------------------------------------------------------------------------- #
# API 鉴权与配置
# --------------------------------------------------------------------------- #
def test_notifications_require_auth():
    assert client.get("/api/notifications").status_code == 401
    assert client.post("/api/notifications", json={"type": "webhook", "name": "x", "config": {}}).status_code == 401


def test_api_configure_list_test_delete(monkeypatch):
    calls = []

    def fake_post(url, json=None, timeout=10.0):
        calls.append(json)
        return httpx.Response(200)

    monkeypatch.setattr(httpx, "post", fake_post)
    headers = _auth("ntf_user1")

    # 配置
    resp = client.post(
        "/api/notifications",
        json={"type": "webhook", "name": "ci", "config": {"url": "https://x/h"}},
        headers=headers,
    )
    assert resp.status_code == 201
    cid = resp.json()["id"]

    # 列表
    listing = client.get("/api/notifications", headers=headers).json()
    assert any(c["id"] == cid for c in listing)

    # 测试发送
    t = client.post(f"/api/notifications/{cid}/test", headers=headers)
    assert t.status_code == 202
    assert len(calls) == 1

    # 删除
    d = client.delete(f"/api/notifications/{cid}", headers=headers)
    assert d.status_code == 204
    assert client.get("/api/notifications", headers=headers).json() == []


def test_api_configure_invalid_type():
    headers = _auth("ntf_user2")
    resp = client.post(
        "/api/notifications",
        json={"type": "telegram", "name": "x", "config": {}},
        headers=headers,
    )
    assert resp.status_code == 400
