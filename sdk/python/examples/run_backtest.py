"""QuantFlow SDK 示例：脚本化跑通回测全流程（V1.1 N2）。

用法：
    export QF_BASE_URL=http://localhost:8080
    python examples/run_backtest.py

也可使用 API Token 免登录：
    export QF_TOKEN=qf.<prefix>.<secret>
    python examples/run_backtest.py
"""

from __future__ import annotations

import os

from quantflow import QuantFlowClient


def main() -> None:
    base_url = os.getenv("QF_BASE_URL", "http://localhost:8080")
    client = QuantFlowClient(base_url)

    token = os.getenv("QF_TOKEN")
    if token:
        client.set_token(token)
        print("使用 API Token 鉴权")
    else:
        # 演示环境：首次注册即用；生产请用已有账号登录或下发 API Token
        user = os.getenv("QF_USER", "demo")
        pwd = os.getenv("QF_PASSWORD", "Test1234")
        try:
            client.login(user, pwd)
        except Exception:
            client.register(user, pwd)
        print(f"登录成功：{user}")

    # 1) 查看可用标的与策略
    inst = client.instruments()
    print(f"可用标的 {inst['total']} 个：{[i['symbol'] for i in inst['items']]}")
    strategies = client.strategies()
    print(f"内置策略：{[s['name'] for s in strategies['items']]}")

    # 2) 取一段行情
    bars = client.bars("TEST.STOCK", start="2024-01-01", end="2024-02-01")
    print(f"TEST.STOCK 行情 {bars['count']} 条")

    # 3) 运行回测
    report = client.run_backtest(
        symbols=["TEST.STOCK"],
        strategy="buy_hold",
        initial_cash=100000,
        start="2024-01-01",
        end="2024-12-31",
    )
    print(f"回测完成 run_id={report['run_id']}")
    print("指标：", report["metrics"])

    # 4) 通过 run_id 取回报告
    again = client.get_backtest(report["run_id"])
    assert again["run_id"] == report["run_id"]
    print("报告可取回 ✅")


if __name__ == "__main__":
    main()
