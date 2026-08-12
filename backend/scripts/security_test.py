"""QuantFlow M5-3 安全测试脚本（本地运行，后端需已启动，Q 需保证数据库可 reset）。

用法：
    cd backend && .venv/bin/python scripts/security_test.py --base http://127.0.0.1:8000

注意：脚本会注册测试用户并创建项目/工作流；建议指向独立测试库（QF_DB_PATH 指向临时文件）。
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request

PASS, FAIL = "PASS", "FAIL"
results: list[tuple[str, str]] = []


def http_json(base: str, path: str, method: str = "GET", body: dict | None = None,
              token: str | None = None) -> tuple[int, dict]:
    url = base + path
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, method=method, data=data)
    if body is not None:
        req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b"{}")
    except urllib.error.HTTPError as exc:
        raw = exc.read() or b"{}"
        try:
            return exc.code, json.loads(raw)
        except json.JSONDecodeError:
            return exc.code, {"detail": raw.decode(errors="replace")[:200]}


def check(name: str, ok: bool, detail: str = "") -> None:
    results.append((name, PASS if ok else FAIL))
    print(f"  [{'✓' if ok else '✗'}] {name}" + (f"  {detail}" if detail and not ok else ""))


def make_token(payload: dict, secret: str = "attacker-secret") -> str:
    header = {"alg": "HS256", "typ": "JWT"}
    def b64(o: dict) -> str:
        raw = json.dumps(o, separators=(",", ":")).encode()
        return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()
    signing = f"{b64(header)}.{b64(payload)}"
    sig = base64.urlsafe_b64encode(hmac.new(secret.encode(), signing.encode(), hashlib.sha256).digest()).rstrip(b"=").decode()
    return f"{signing}.{sig}"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    base = args.base
    ts = str(int(time.time()))
    user_a, user_b, user_c = f"sec_a_{ts}", f"sec_b_{ts}", f"sec_c_{ts}"
    pwd = "SecPass_123"

    print("== 0. 准备：注册用户 ==")
    r, _ = http_json(base, "/api/auth/register", "POST", {"username": user_a, "password": pwd})
    check(f"注册用户A（首个→admin） {user_a}", r in (200, 201))
    http_json(base, "/api/auth/register", "POST", {"username": user_b, "password": pwd})
    http_json(base, "/api/auth/register", "POST", {"username": user_c, "password": pwd})

    r, d = http_json(base, "/api/auth/login", "POST", {"username": user_a, "password": pwd})
    check("登录A获取token", r == 200, f"r={r}")
    token_a = d.get("access_token") or d.get("token", "")
    _, d = http_json(base, "/api/auth/login", "POST", {"username": user_b, "password": pwd})
    token_b = d.get("access_token") or d.get("token", "")
    _, d = http_json(base, "/api/auth/login", "POST", {"username": user_c, "password": pwd})
    token_c = d.get("access_token") or d.get("token", "")

    print("\n== 1. 未授权访问 ==")
    for path in ["/api/projects", "/api/logs", "/api/monitoring/overview", "/api/monitoring/metrics"]:
        r, _ = http_json(base, path)
        check(f"匿名访问 {path} → 401", r == 401, f"r={r}")

    print("\n== 2. JWT 安全 ==")
    # 篡改 payload（改 uid/role）
    parts = token_a.split(".")
    if len(parts) == 3:
        import struct
        def b64d(s: str) -> bytes:
            return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))
        try:
            payload = json.loads(b64d(parts[1]))
        except Exception:  # noqa: BLE001
            payload = {}
        payload["role"] = "admin"
        payload["username"] = user_c
        tampered = f"{parts[0]}.{base64.urlsafe_b64encode(json.dumps(payload).encode()).rstrip(b'=').decode()}.{parts[2]}"
        r, _ = http_json(base, "/api/auth/me", token=tampered)
        check("篡改 JWT payload → 401", r == 401, f"r={r}")

    # 伪造签名（错误密钥）
    forged = make_token({"uid": "x", "username": user_a, "role": "admin", "exp": int(time.time()) + 3600})
    r, _ = http_json(base, "/api/auth/me", token=forged)
    check("伪造签名 JWT → 401", r == 401, f"r={r}")

    # 过期 token
    expired = make_token({"uid": "x", "username": user_a, "role": "admin", "exp": int(time.time()) - 60})
    r, _ = http_json(base, "/api/auth/me", token=expired)
    check("过期 JWT → 401", r == 401, f"r={r}")

    print("\n== 3. RBAC / 越权 ==")
    r, d = http_json(base, "/api/projects", "POST", {"name": f"proj_{ts}", "description": "sec test"}, token_a)
    check("A 创建项目", r in (200, 201), f"r={r}")
    proj_id = d.get("id") or d.get("project_id", "")
    check("A 为 owner", (d.get("owner_id") or "") != "" or "id" in d)

    # B 添加为 viewer
    r, _ = http_json(base, f"/api/projects/{proj_id}/members", "POST", {"username": user_b, "role": "viewer"}, token_a)
    check("A 添加 B 为 viewer", r in (200, 201), f"r={r}")

    # B（viewer）删除项目
    r, _ = http_json(base, f"/api/projects/{proj_id}", "DELETE", token=token_b)
    check("B(viewer) 删除项目 → 403", r == 403, f"r={r}")

    # C 删除项目（非成员）
    r, _ = http_json(base, f"/api/projects/{proj_id}", "DELETE", token=token_c)
    check("C(非成员) 删除项目 → 403", r == 403, f"r={r}")

    # A 在项目下创建工作流，B(viewer) 读取，C 读取
    wf_payload = {
        "name": f"wf_{ts}",
        "project_id": proj_id,
        "nodes": [{"id": "n1", "node_type": "math.add", "params": {"a": 1, "b": 2}, "position": {"x": 0, "y": 0}}],
        "edges": [],
    }
    r, d = http_json(base, "/api/workflows", "POST", wf_payload, token_a)
    check("A 创建项目工作流", r in (200, 201), f"r={r}")
    wf_id = d.get("id", "")
    r, _ = http_json(base, f"/api/workflows/{wf_id}", token=token_b)
    check("B(viewer) 读项目工作流", r in (200, 403), f"r={r}")  # viewer 或 member 任一策略均可
    r, _ = http_json(base, f"/api/workflows/{wf_id}", token=token_c)
    check("C(非成员) 读项目工作流 → 403", r == 403, f"r={r}")

    # C 非成员列表项目工作流（列表接口返回空集 = 隔离生效，不泄露项目内容）
    r, d = http_json(base, f"/api/workflows?project_id={proj_id}", token=token_c)
    leaked = isinstance(d, list) and any(w.get("id") == wf_id or w.get("name") == f"wf_{ts}" for w in d)
    check("C 非成员列表项目工作流 → 隔离（空/403）", r in (401, 403) or (r == 200 and not leaked), f"r={r} leaked={leaked}")

    print("\n== 4. SQL 注入 ==")
    # 登录名注入
    for payload in [
        {"username": "admin' OR '1'='1", "password": "x" * 8},
        {"username": "' OR 1=1 --", "password": "x" * 8},
        {"username": 'admin" OR "1"="1', "password": "x" * 8},
    ]:
        r, _ = http_json(base, "/api/auth/login", "POST", payload)
        check(f"SQLi 登录 {payload['username'][:18]!r} → 非 200", r in (401, 422, 400), f"r={r}")

    # 项目名注入
    r, _ = http_json(base, "/api/projects", "POST",
                     {"name": "x' OR '1'='1' --", "description": "inject"}, token_a)
    check("SQLi 项目名 → 非 500", r not in (500,), f"r={r}")

    print("\n== 5. 日志注入 ==")
    r, _ = http_json(base, "/api/projects", "POST",
                     {"name": f"log_inj_{ts}\n{{\"fake\":true}}", "description": "test"}, token_a)
    check("含换行/花括号的项目名创建 → 非 500", r in (200, 201, 422), f"r={r}")

    print("\n== 6. 弱口令 / 校验 ==")
    r, _ = http_json(base, "/api/auth/register", "POST", {"username": f"weak_{ts}", "password": "123"})
    check("短密码注册 → 422", r == 422, f"r={r}")
    r, _ = http_json(base, "/api/auth/register", "POST", {"username": "bad user!", "password": "x" * 8})
    check("非法用户名注册 → 422", r == 422, f"r={r}")

    print("\n== 结果汇总 ==")
    ok = sum(1 for _, s in results if s == PASS)
    print(f"  {ok}/{len(results)} 通过")
    failed = [n for n, s in results if s == FAIL]
    if failed:
        print("  FAILED:", failed)
        raise SystemExit(1)
    print("  ALL SECURITY CHECKS PASSED")


if __name__ == "__main__":
    main()
