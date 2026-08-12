"""QuantFlow HTTP 客户端（V1.1 N2）。

基于 ``httpx``，支持：
- 用户名/密码登录（JWT）或 API Token 直接鉴权；
- 兼容测试场景：可注入自定义 ``httpx.Client``（如 ASGITransport）。
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

import httpx


class QuantFlowError(Exception):
    """API 调用失败：携带 HTTP 状态码与响应文本。"""

    def __init__(self, status: int, detail: str) -> None:
        super().__init__(f"QuantFlow API {status}: {detail}")
        self.status = status
        self.detail = detail


class QuantFlowClient:
    """QuantFlow 平台 REST 客户端。"""

    def __init__(
        self,
        base_url: str,
        token: Optional[str] = None,
        timeout: float = 30.0,
        _client: Optional[httpx.Client] = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self._token: Optional[str] = token
        self._client = _client or httpx.Client(base_url=self.base_url, timeout=timeout)

    # ------------------------------------------------------------------ #
    # 鉴权
    # ------------------------------------------------------------------ #
    def _headers(self) -> Dict[str, str]:
        headers = {"Accept": "application/json"}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def _request(
        self,
        method: str,
        path: str,
        *,
        json: Optional[Any] = None,
        params: Optional[Dict[str, Any]] = None,
    ) -> Any:
        resp = self._client.request(
            method,
            f"/api{path}",
            json=json,
            params=params,
            headers=self._headers(),
        )
        if resp.status_code == 204:
            return None
        if resp.status_code >= 400:
            raise QuantFlowError(resp.status_code, resp.text)
        if not resp.content:
            return None
        return resp.json()

    def login(self, username: str, password: str) -> Dict:
        data = self._request(
            "POST", "/auth/login", json={"username": username, "password": password}
        )
        self._token = data["token"]
        return data["user"]

    def register(self, username: str, password: str) -> Dict:
        data = self._request(
            "POST", "/auth/register", json={"username": username, "password": password}
        )
        self._token = data["token"]
        return data["user"]

    def set_token(self, token: str) -> None:
        self._token = token

    # ------------------------------------------------------------------ #
    # API Token 管理（N2）
    # ------------------------------------------------------------------ #
    def create_token(self, name: str, scopes: Optional[List[str]] = None) -> Dict:
        return self._request(
            "POST", "/tokens", json={"name": name, "scopes": scopes or ["*"]}
        )

    def list_tokens(self) -> List[Dict]:
        return self._request("GET", "/tokens")

    def revoke_token(self, prefix: str) -> None:
        self._request("DELETE", f"/tokens/{prefix}")

    # ------------------------------------------------------------------ #
    # 行情（M2）
    # ------------------------------------------------------------------ #
    def instruments(self) -> Dict:
        return self._request("GET", "/market/instruments")

    def bars(
        self,
        symbol: str,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Dict:
        params: Dict[str, Any] = {"symbol": symbol}
        if start:
            params["start"] = start
        if end:
            params["end"] = end
        return self._request("GET", "/market/bars", params=params)

    def sync_status(self) -> Dict:
        return self._request("GET", "/market/sync/status")

    def sync_now(self) -> Dict:
        return self._request("POST", "/market/sync")

    # ------------------------------------------------------------------ #
    # 项目（M4）
    # ------------------------------------------------------------------ #
    def list_projects(self) -> List[Dict]:
        return self._request("GET", "/projects")

    def create_project(self, name: str, description: str = "") -> Dict:
        return self._request(
            "POST", "/projects", json={"name": name, "description": description}
        )

    # ------------------------------------------------------------------ #
    # 回测（M2）
    # ------------------------------------------------------------------ #
    def strategies(self) -> Dict:
        return self._request("GET", "/backtest/strategies")

    def run_backtest(
        self,
        symbols: List[str],
        strategy: str,
        initial_cash: float = 100000,
        start: str = "2024-01-01",
        end: str = "2024-12-31",
    ) -> Dict:
        """运行回测，返回完整报告（含 run_id）。"""
        return self._request(
            "POST",
            "/backtest/run",
            json={
                "symbols": symbols,
                "strategy": strategy,
                "initial_cash": initial_cash,
                "start": start,
                "end": end,
            },
        )

    def get_backtest(self, run_id: str) -> Dict:
        return self._request("GET", f"/backtest/reports/{run_id}")

    def list_backtests(self) -> Dict:
        return self._request("GET", "/backtest/reports")

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #
    def health(self) -> Dict:
        resp = self._client.get(f"{self.base_url}/api/health")
        if resp.status_code >= 400:
            raise QuantFlowError(resp.status_code, resp.text)
        return resp.json()
