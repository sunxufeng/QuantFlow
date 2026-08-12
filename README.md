# QuantFlow · 量化工作流平台

对标 PandaAI QuantFlow 的**自主实现方案**（全部代码自研，避开上游 GPL 传染）。

**里程碑进度**：M1 最小闭环 ✅ → M2 数据/回测/执行引擎 ✅ → M3 节点库与前端编辑器 ✅ → M4 业务能力（用户/RBAC/项目/日志/监控/Docker）✅ → M5 测试与发布（进行中）

## 已实现能力

| 模块 | 说明 |
|---|---|
| 插件框架 | `BaseWorkNode` 抽象 + `@work_node` 装饰器 + `PluginRegistry` 注册表，类型系统（number/string/boolean/array/table/...） |
| DAG 引擎 | 拓扑排序 / 环检测 / 端口存在性与类型校验 / 单输入源约束 / 并发执行 / 失败传播（下游 BLOCKED，独立分支继续） |
| 节点库（M3） | 24 类节点：数据源（行情/表格）、处理（转换/去重/合并）、特征（移动平均/RSI/布林带）、因子、ML（LinearRegression/DecisionTree/...）、回测入口 |
| 回测引擎（M2） | 股票账户（T+1/涨跌停/停牌/佣金/滑点）+ 基金账户（T+1 确认/申购费/定投），绩效报告（年化/回撤/夏普/换手） |
| 数据层（M2） | 多数据源（tushare / fixture 内置样例）+ 内存缓存 + 冷启动自动初始化 |
| 执行引擎（M2） | 运行实例持久化 + WebSocket 状态实时推送（节点级状态/输出预览） |
| 业务能力（M4） | 用户注册/登录（PBKDF2 + JWT）、RBAC（admin/user/viewer）、项目与成员管理（owner/admin/member/viewer）、结构化日志查询、监控指标（Prometheus 格式） |
| 前端 | React + Vite + React Flow：节点面板（搜索/分组）、属性面板（schema 表单校验）、画布（类型校验/撤销重做）、运行可视化（WS 实时着色）、K线图表页、工作流管理（列表/重命名/JSON 导入导出）、登录/项目切换/监控页 |
| 测试 | 210 个 pytest 用例 + 前端生产构建，GitHub Actions CI（backend 单测 / frontend 构建 / Docker 构建） |

## 快速启动

### 方式一：本地开发

```bash
# 后端（端口 8000）
cd backend
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/uvicorn app.main:app --reload --port 8000

# 前端（端口 5173，/api 代理到 8000）
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 ，点击「示例工作流」→「运行」即可看到最小闭环结果。

### 方式二：Docker Compose（推荐快速体验）

```bash
cd quantflow
docker compose -f deploy/docker-compose.yml up -d --build
# 前端 http://localhost:8080  （/api/* 由 nginx 反代到后端容器）
```

- 后端镜像：python:3.13-slim，uvicorn 监听 :8000，默认 `QF_MARKET_PROVIDER=fixture`（无需 tushare token）
- 前端镜像：node:20 多阶段构建 → nginx 静态托管 + `/api` 反代
- SQLite 数据库持久化到 named volume `quantflow-data`，`docker compose down` 不清数据；`down -v` 清空
- 生产注意：务必用 `QF_SECRET_KEY` 覆盖默认密钥，例如 `QF_SECRET_KEY=$(openssl rand -hex 32) docker compose up -d`
- 首个注册用户自动成为管理员（admin）

### 方式三：生产部署（systemd + venv + Node 静态服务）

国内服务器拉 Docker Hub 镜像常受阻，实际生产采用「venv 直跑后端 + Node 静态服务」方案，已上线 `https://acqw.areteailab.com`：

```bash
cd quantflow
sudo bash deploy/deploy.sh        # 安装到 /opt/quantflow/QuantFlow 并注册 systemd
# 覆盖默认值：QF_DIR / QF_BACKEND_PORT=8100 / QF_FRONTEND_PORT=8080
```

systemd 单元（`deploy/systemd/`）：
- `quantflow.service` — uvicorn 监听 `127.0.0.1:8100`（后端）
- `quantflow-frontend.service` — `node server.mjs` 监听 `0.0.0.0:8080`，静态托管前端并反代 `/api/*` 到后端

对外域名建议用 Nginx Proxy Manager 反代 443（HTTPS 证书 acme.sh DNS-01 + 自动续期），示例：`acqw.areteailab.com → http://172.17.0.1:8080`。

## 测试

```bash
cd backend && .venv/bin/python -m pytest tests/ -q   # 210 个用例
```

覆盖：节点注册/规格/参数解析、DAG 拓扑/环检测/端口校验、执行引擎（线性/菱形并行/失败传播/序列化）、回测引擎（股票 T+1/涨跌停/停牌 + 基金 T+1 确认/费用/定投）、数据层、REST API、用户/JWT/RBAC（test_auth）、项目与成员权限（test_projects）、结构化日志（test_logs）、监控接口（test_monitoring）。

## 目录结构

```
quantflow/
├── .github/workflows/     # GitHub Actions CI（backend 单测 / frontend 构建 / Docker 构建）
├── deploy/                # 生产部署：deploy.sh + systemd 单元 + docker-compose.yml
├── backend/
│   ├── app/
│   │   ├── core/          # 节点、注册表、DAG、执行器、数据类型、工作流/运行仓储
│   │   │                  # + db.py（SQLite）/ security.py（PBKDF2+JWT）/ users.py / projects.py / auth.py
│   │   │                  # + logging_store.py（RingBuffer 结构化日志）
│   │   ├── nodes/         # 内置节点库（@work_node 注册，24 类）
│   │   ├── backtest/      # 回测引擎：股票/基金账户、策略、绩效、报告
│   │   ├── market/        # 数据层：多数据源（tushare/fixture）、缓存
│   │   ├── api/           # workflows / backtest / market / runs / auth / projects / logs / monitoring 路由
│   │   ├── models/        # Pydantic 契约
│   │   ├── config.py
│   │   └── main.py
│   ├── Dockerfile
│   └── tests/             # 210 用例
└── frontend/
    ├── src/               # App.jsx / WorkflowNode.jsx / api.js / AuthModal.jsx / Monitoring.jsx / styles.css
    ├── server.mjs         # 生产静态服务 + /api 反代（零依赖）
    ├── Dockerfile         # 多阶段构建 → nginx
    ├── nginx.conf
    └── package.json
```

## 里程碑清单

- [x] M1 最小闭环：插件框架 + DAG 引擎 + 内置节点 + REST API + 前端画布 Demo
- [x] M2 数据/回测/执行：多数据源与缓存、股票+基金回测引擎、运行持久化与 WS 推送
- [x] M3 节点库与编辑器：24 类节点、节点面板/属性面板/运行可视化/撤销重做/K线图
- [x] M4 业务能力：用户体系（PBKDF2+JWT+RBAC）、项目与成员、结构化日志、监控、前端联动、Docker Compose
- [ ] M5 测试与发布：全量回归、压测、安全测试、文档打包、V1.0 Release
