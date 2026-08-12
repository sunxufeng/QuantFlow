"""QuantFlow Python SDK（V1.1 N2：API 代码式调用）。

通过 API Token 或用户名/密码登录后，可在脚本中完成：
注册/登录、创建项目、查询标的与行情、运行回测并取回报告。

示例::

    from quantflow import QuantFlowClient

    client = QuantFlowClient("http://localhost:8080")
    client.login("me", "Test1234")
    report = client.run_backtest(
        symbols=["TEST.STOCK"], strategy="buy_hold",
        initial_cash=100000, start="2024-01-01", end="2024-12-31",
    )
    print(report["metrics"])
"""

from __future__ import annotations

from .client import QuantFlowClient, QuantFlowError

__all__ = ["QuantFlowClient", "QuantFlowError"]
__version__ = "0.1.0"
