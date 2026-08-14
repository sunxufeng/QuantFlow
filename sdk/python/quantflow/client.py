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

    # ---- V5.0 行情缓存 / 数据源管理 ----
    def market_cache(self) -> Dict:
        """行情缓存与数据源快照（V5.0）：数据源模式、缓存后端、各标的中继情况。"""
        return self._request("GET", "/market/cache")

    def market_refresh(
        self,
        symbols: Optional[List[str]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
    ) -> Dict:
        """强制从数据源重新拉取并落库（V5.0）。tushare 源需显式指定 symbols。"""
        payload: Dict[str, Any] = {}
        if symbols is not None:
            payload["symbols"] = symbols
        if start is not None:
            payload["start"] = start
        if end is not None:
            payload["end"] = end
        return self._request("POST", "/market/cache/refresh", json=payload or None)

    # ---- V6.0 模拟交易账户（paper，纯本地） ----
    def trading_account(self) -> Dict:
        """账户概览（V6.0）：初始资金（可配置）、当前现金/权益与持仓/挂单数。"""
        return self._request("GET", "/trading/account")

    def trading_reset(self, initial_cash: Optional[float] = None) -> Dict:
        """重置模拟账户；initial_cash 可指定新的账户初始资金并持久化（V6.0）。"""
        payload: Dict[str, Any] = {}
        if initial_cash is not None:
            payload["initial_cash"] = initial_cash
        return self._request("DELETE", "/trading/reset", json=payload or None)

    # ---- V6.1 系统设置 + 用户偏好 ----
    def settings(self) -> Dict:
        """读取系统信息与当前用户偏好（V6.1）：版本/数据源/缓存后端/券商 + 偏好。"""
        return self._request("GET", "/settings")

    def update_settings(
        self,
        default_view: Optional[str] = None,
        theme: Optional[str] = None,
        preferred_data_source: Optional[str] = None,
    ) -> Dict:
        """更新当前用户偏好（V6.1，部分字段合并）。"""
        payload: Dict[str, Any] = {}
        if default_view is not None:
            payload["default_view"] = default_view
        if theme is not None:
            payload["theme"] = theme
        if preferred_data_source is not None:
            payload["preferred_data_source"] = preferred_data_source
        return self._request("PUT", "/settings", json=payload or None)

    # ---- V6.2 批量导出中心 ----
    def export_data(self, resource: str, format: str = "json") -> Dict:
        """批量导出（V6.2）：resource=factors|templates|backtests，format=csv|json。

        JSON 格式返回解析后的 dict；CSV 格式返回带 BOM 的文本（便于 Excel）。
        """
        return self._request("GET", "/export", params={"resource": resource, "format": format})

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

    def export_backtest(self, run_id: str, format: str = "csv") -> bytes:
        """导出回测报告（csv / json），返回文件字节。"""
        resp = self._client.get(
            f"{self.base_url}/api/backtest/reports/{run_id}/export",
            params={"format": format},
            headers={"Authorization": f"Bearer {self.token}"} if self.token else {},
        )
        if resp.status_code >= 400:
            raise QuantFlowError(resp.status_code, resp.text)
        return resp.content

    # ------------------------------------------------------------------ #
    # 预警规则引擎（V2.3）
    # ------------------------------------------------------------------ #
    def list_alerts(self) -> Dict:
        return self._request("GET", "/alerts")

    def create_alert(
        self,
        name: str,
        symbol: str,
        threshold: float,
        *,
        metric: str = "price",
        operator: str = ">",
        cooldown_minutes: int = 60,
        enabled: bool = True,
    ) -> Dict:
        return self._request(
            "POST",
            "/alerts",
            json={
                "name": name,
                "symbol": symbol,
                "metric": metric,
                "operator": operator,
                "threshold": threshold,
                "cooldown_minutes": cooldown_minutes,
                "enabled": enabled,
            },
        )

    def delete_alert(self, alert_id: str) -> Dict:
        return self._request("DELETE", f"/alerts/{alert_id}")

    def evaluate_alerts(self) -> Dict:
        return self._request("POST", "/alerts/evaluate")

    # ------------------------------------------------------------------ #
    # 自选股 / 行情看板（V2.4）
    # ------------------------------------------------------------------ #
    def get_watchlist(self) -> Dict:
        return self._request("GET", "/market/watchlist")

    def add_watchlist(self, symbol: str) -> Dict:
        return self._request("POST", f"/market/watchlist?symbol={symbol}")

    def remove_watchlist(self, symbol: str) -> Dict:
        return self._request("DELETE", f"/market/watchlist/{symbol}")

    def get_quotes(self, symbols: List[str]) -> Dict:
        return self._request("GET", f"/market/quotes?symbols={','.join(symbols)}")

    def list_backtests(self) -> Dict:
        return self._request("GET", "/backtest/reports")

    # ---- V2.8 回测对比与排行榜 ----
    def compare_backtests(self, ids: List[str]) -> Dict:
        return self._request("GET", "/backtest/compare", params={"ids": ",".join(ids)})

    def backtest_leaderboard(self, metric: str = "sharpe", order: str = "desc") -> Dict:
        return self._request(
            "GET", "/backtest/leaderboard", params={"metric": metric, "order": order}
        )

    def optimize_backtest(
        self,
        symbols: List[str],
        strategy: str,
        grid: Dict[str, List[object]],
        *,
        fixed_params: Optional[Dict[str, object]] = None,
        start: str = "2024-01-01",
        end: str = "2024-12-31",
        initial_cash: float = 100000,
        asset_types: Optional[Dict[str, str]] = None,
        multipliers: Optional[Dict[str, float]] = None,
        interval: str = "daily",
        objective: str = "sharpe",
        top_n: int = 10,
        max_combos: int = 200,
    ) -> Dict:
        """回测参数优化（V2.1）：网格搜索并按目标排序返回 Top-N。"""
        return self._request(
            "POST",
            "/backtest/optimize",
            json={
                "symbols": symbols,
                "strategy": strategy,
                "grid": grid,
                "fixed_params": fixed_params or {},
                "start": start,
                "end": end,
                "initial_cash": initial_cash,
                "asset_types": asset_types or {},
                "multipliers": multipliers or {},
                "interval": interval,
                "objective": objective,
                "top_n": top_n,
                "max_combos": max_combos,
            },
        )

    def multifactor_backtest(
        self,
        symbol: str,
        factors: List[Dict[str, object]],
        *,
        start: str = "2024-01-01",
        end: str = "2024-12-31",
        threshold: float = 0.0,
        initial_cash: float = 1_000_000.0,
    ) -> Dict:
        """多因子组合回测闭环（V4.2）：多因子按权重合成为综合信号并回测。"""
        return self._request(
            "POST",
            "/factors/research/multifactor",
            json={
                "symbol": symbol,
                "factors": factors,
                "start": start,
                "end": end,
                "threshold": threshold,
                "initial_cash": initial_cash,
            },
        )

    # ------------------------------------------------------------------ #
    # 健康检查
    # ------------------------------------------------------------------ #
    def health(self) -> Dict:
        resp = self._client.get(f"{self.base_url}/api/health")
        if resp.status_code >= 400:
            raise QuantFlowError(resp.status_code, resp.text)
        return resp.json()

    # ------------------------------------------------------------------ #
    # 因子库与分析（V1.1 N3）
    # ------------------------------------------------------------------ #
    def list_factors(self, category: Optional[str] = None) -> Dict:
        params = {"category": category} if category else None
        return self._request("GET", "/factors/library", params=params)

    def create_factor(
        self,
        name: str,
        expression: str,
        category: str = "自定义",
        description: str = "",
        params: Optional[Dict] = None,
    ) -> Dict:
        return self._request(
            "POST",
            "/factors/library",
            json={
                "name": name,
                "expression": expression,
                "category": category,
                "description": description,
                "params": params or {},
            },
        )

    def get_factor(self, factor_id: str) -> Dict:
        return self._request("GET", f"/factors/library/{factor_id}")

    def update_factor(self, factor_id: str, **kwargs) -> Dict:
        return self._request("PUT", f"/factors/library/{factor_id}", json=kwargs)

    def delete_factor(self, factor_id: str) -> None:
        self._request("DELETE", f"/factors/library/{factor_id}")

    def analyze_factor(self, payload: Dict) -> Dict:
        return self._request("POST", "/factors/analyze", json=payload)

    # ---- V2.5 因子评分 ----
    def factor_scoring_catalog(self) -> Dict:
        return self._request("GET", "/factors/scoring/catalog")

    def score_factors(
        self,
        symbols: List[str],
        factors: Optional[List[Dict]] = None,
        start: Optional[str] = None,
        end: Optional[str] = None,
        method: str = "rank",
    ) -> Dict:
        payload: Dict[str, object] = {"symbols": symbols, "method": method}
        if factors is not None:
            payload["factors"] = factors
        if start is not None:
            payload["start"] = start
        if end is not None:
            payload["end"] = end
        return self._request("POST", "/factors/scoring/score", json=payload)

    # ---- V2.9 因子研究（相关性矩阵 + IC/IR）----
    def factor_correlation_matrix(
        self,
        symbols: Optional[List[str]] = None,
        start: str = "2000-01-01",
        end: str = "2100-01-01",
        window: int = 10,
    ) -> Dict:
        params = {"start": start, "end": end, "window": window}
        if symbols:
            params["symbols"] = ",".join(symbols)
        return self._request("GET", "/factors/research/matrix", params=params)

    def factor_ic_analysis(
        self,
        symbols: Optional[List[str]] = None,
        start: str = "2000-01-01",
        end: str = "2100-01-01",
        window: int = 10,
        forward: int = 1,
    ) -> Dict:
        params = {"start": start, "end": end, "window": window, "forward": forward}
        if symbols:
            params["symbols"] = ",".join(symbols)
        return self._request("GET", "/factors/research/ic", params=params)

    def factor_ranking(
        self,
        symbols: Optional[List[str]] = None,
        start: str = "2000-01-01",
        end: str = "2100-01-01",
        window: int = 10,
        forward: int = 1,
        metric: str = "mean_ic",
        order: str = "desc",
    ) -> Dict:
        """因子排行榜（V3.2）：按 IC/IR 指标对所有内置因子排序。"""
        params = {
            "start": start,
            "end": end,
            "window": window,
            "forward": forward,
            "metric": metric,
            "order": order,
        }
        if symbols:
            params["symbols"] = ",".join(symbols)
        return self._request("GET", "/factors/research/ranking", params=params)

    # ---- V2.7 预警自动评估调度 ----
    def get_alert_scheduler(self) -> Dict:
        return self._request("GET", "/alerts/scheduler")

    def trigger_alert_scheduler(self) -> Dict:
        return self._request("POST", "/alerts/scheduler/trigger")

    # ---- V3.3 多 LLM 路由 ----
    def get_llm_status(self) -> Dict:
        """LLM provider 状态（含多模型路由链 chain）。"""
        return self._request("GET", "/llm/status")

    # ---- V3.4 批量生成并对比回测 ----
    def batch_generate_compare(
        self, prompts: List[str], use_llm: bool = True
    ) -> Dict:
        """对多个自然语言策略批量生成并运行回测，返回可对比的指标与净值曲线。"""
        return self._request(
            "POST",
            "/workflows/batch-generate-compare",
            json={"prompts": prompts, "use_llm": use_llm},
        )

    # ------------------------------------------------------------------ #
    # 工作流与运行（M3 / V1.1 N2）
    # ------------------------------------------------------------------ #
    def list_nodes(self) -> List[Dict]:
        return self._request("GET", "/nodes")

    def list_workflows(self, project_id: Optional[str] = None, scope: str = "all") -> List[Dict]:
        params: Dict[str, Any] = {"scope": scope}
        if project_id:
            params["project_id"] = project_id
        return self._request("GET", "/workflows", params=params)

    def create_workflow(self, name: str, nodes: List[Dict], edges: List[Dict], **kwargs) -> Dict:
        return self._request(
            "POST",
            "/workflows",
            json={"name": name, "nodes": nodes, "edges": edges, **kwargs},
        )

    def get_workflow(self, workflow_id: str) -> Dict:
        return self._request("GET", f"/workflows/{workflow_id}")

    def update_workflow(self, workflow_id: str, name: str, nodes: List[Dict], edges: List[Dict], **kwargs) -> Dict:
        return self._request(
            "PUT",
            f"/workflows/{workflow_id}",
            json={"name": name, "nodes": nodes, "edges": edges, **kwargs},
        )

    def delete_workflow(self, workflow_id: str) -> None:
        self._request("DELETE", f"/workflows/{workflow_id}")

    def export_workflow(self, workflow_id: str) -> Dict:
        return self._request("GET", f"/workflows/{workflow_id}/export")

    def validate_workflow(self, nodes: List[Dict], edges: List[Dict]) -> Dict:
        return self._request(
            "POST", "/workflows/validate", json={"nodes": nodes, "edges": edges}
        )

    # ---- V3.0 AI 策略工作台：自然语言生成工作流 ----
    def generate_workflow(self, prompt: str, use_llm: bool = True) -> Dict:
        return self._request(
            "POST", "/workflows/generate", json={"prompt": prompt, "use_llm": use_llm}
        )

    def list_workflow_versions(self, workflow_id: str) -> List[Dict]:
        return self._request("GET", f"/workflows/{workflow_id}/versions")

    def create_workflow_version(self, workflow_id: str, label: str = "") -> Dict:
        return self._request(
            "POST", f"/workflows/{workflow_id}/versions", json={"label": label}
        )

    def restore_workflow_version(self, workflow_id: str, version: int) -> Dict:
        return self._request(
            "POST", f"/workflows/{workflow_id}/versions/{version}/restore"
        )

    def submit_run(self, workflow_id: str) -> Dict:
        return self._request("POST", "/runs", json={"workflow_id": workflow_id})

    # ---- V3.1 个人工作流模板库 ----
    def list_my_templates(self) -> List[Dict]:
        return self._request("GET", "/workflows/templates/mine")

    def save_template(
        self,
        name: str,
        nodes: List[Dict],
        edges: List[Dict],
        description: str = "",
        tags: Optional[List[str]] = None,
    ) -> Dict:
        return self._request(
            "POST",
            "/workflows/templates",
            json={
                "name": name,
                "description": description,
                "nodes": nodes,
                "edges": edges,
                "tags": tags or [],
            },
        )

    def get_template(self, template_id: str) -> Dict:
        return self._request("GET", f"/workflows/templates/{template_id}")

    def delete_template(self, template_id: str) -> None:
        self._request("DELETE", f"/workflows/templates/{template_id}")

    def list_runs(self) -> List[Dict]:
        return self._request("GET", "/runs")

    def get_run(self, run_id: str) -> Dict:
        return self._request("GET", f"/runs/{run_id}")

    # ------------------------------------------------------------------ #
    # LLM 策略助手（V1.1 N1）
    # ------------------------------------------------------------------ #
    def llm_status(self) -> Dict:
        return self._request("GET", "/llm/status")

    def llm_config(self) -> Dict:
        return self._request("GET", "/llm/config")

    def set_llm_config(self, payload: Dict) -> Dict:
        return self._request("PUT", "/llm/config", json=payload)

    def test_llm_config(self) -> Dict:
        return self._request("POST", "/llm/config/test")

    def llm_assist(self, prompt: str, context: Optional[Dict] = None) -> Dict:
        return self._request(
            "POST", "/llm/assist", json={"prompt": prompt, "context": context or {}}
        )

    # ------------------------------------------------------------------ #
    # 交易（V1.8 / V2.0）
    # ------------------------------------------------------------------ #
    def trading_summary(self) -> Dict:
        return self._request("GET", "/trading/summary")

    def trading_analytics(self) -> Dict:
        return self._request("GET", "/trading/analytics")

    def trading_positions(self) -> List[Dict]:
        return self._request("GET", "/trading/positions")

    def trading_orders(self) -> List[Dict]:
        return self._request("GET", "/trading/orders")

    def submit_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        qty: float,
        price: Optional[float] = None,
    ) -> Dict:
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": type_,
            "qty": qty,
        }
        if price is not None:
            payload["price"] = price
        return self._request("POST", "/trading/orders", json=payload)

    def cancel_order(self, order_id: str) -> Dict:
        return self._request("POST", f"/trading/orders/{order_id}/cancel")

    def simulate_trading(self, price_overrides: Optional[Dict[str, float]] = None) -> List[str]:
        return self._request(
            "POST", "/trading/simulate", json={"price_overrides": price_overrides or {}}
        )

    def reset_trading(self) -> Dict:
        return self._request("DELETE", "/trading/reset")

    def trading_mode(self) -> Dict:
        return self._request("GET", "/trading/mode")

    def live_trading_status(self) -> Dict:
        return self._request("GET", "/trading/live/status")

    def submit_live_order(
        self,
        symbol: str,
        side: str,
        type_: str,
        qty: float,
        price: Optional[float] = None,
    ) -> Dict:
        payload: Dict[str, Any] = {
            "symbol": symbol,
            "side": side,
            "type": type_,
            "qty": qty,
        }
        if price is not None:
            payload["price"] = price
        return self._request("POST", "/trading/live/orders", json=payload)
