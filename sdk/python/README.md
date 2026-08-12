# QuantFlow Python SDK

QuantFlow 量化工作流平台的官方 Python 客户端（V1.1 N2：API 代码式调用）。

通过 SDK 可在脚本/Notebook 中完成：注册/登录、API Token 管理、查询标的和行情、
创建项目、运行回测并取回报告。

## 安装

```bash
cd sdk/python
pip install -e .
```

## 快速开始

```python
from quantflow import QuantFlowClient

client = QuantFlowClient("http://localhost:8080")
client.login("demo", "Test1234")

report = client.run_backtest(
    symbols=["TEST.STOCK"],
    strategy="buy_hold",
    initial_cash=100000,
    start="2024-01-01",
    end="2024-12-31",
)
print(report["metrics"])

# 通过 run_id 取回报告
print(client.get_backtest(report["run_id"]))
```

## API Token（推荐用于脚本/服务）

登录后在平台创建 Token，脚本中直接携带，免去账号密码：

```python
client = QuantFlowClient("http://localhost:8080", token="qf.<prefix>.<secret>")
report = client.run_backtest(...)
```

也可在代码中管理 Token：

```python
created = client.create_token("ci-runner", scopes=["*"])
print("一次性明文 token：", created["token"])

for t in client.list_tokens():
    print(t["prefix"], t["name"], "revoked=" + str(t["revoked"]))

client.revoke_token(created["prefix"])
```

## 环境变量

- `QF_BASE_URL`：平台地址，默认 `http://localhost:8080`
- `QF_TOKEN`：API Token（设置后免登录）
- `QF_USER` / `QF_PASSWORD`：账号密码（未设置 Token 时）

## 测试

```bash
pip install -e ".[test]"
pytest
```

测试通过 FastAPI `ASGITransport` 在进程内驱动后端，无需启动服务器。
