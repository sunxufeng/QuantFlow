# QuantFlow · 量化工作流平台（M1 技术预研原型）

对标 PandaAI QuantFlow 的自主实现方案。**M1 阶段目标**：跑通「节点 → 执行 → 结果」最小闭环。

## 已实现能力（M1 原型）

| 模块 | 说明 |
|---|---|
| 插件框架 | `BaseWorkNode` 抽象 + `@work_node` 装饰器 + `PluginRegistry` 注册表，类型系统（number/string/boolean/array/table） |
| DAG 引擎 | 拓扑排序 / 环检测 / 端口存在性与类型校验 / 单输入源约束 / 并发执行 / 失败传播（下游 BLOCKED，独立分支继续） |
| 内置节点 | 8 个：常量、数列、示例表格、加法、乘法、数组求和、数组均值、表格取前 N 行 |
| REST API | 节点列表、工作流 CRUD/校验/运行、JSON 导入导出、健康检查 |
| 工作流存储 | M1 线程安全内存仓储，保存名称、版本、节点、连线、参数与画布坐标；预留 MongoDB 替换边界 |
| 前端画布 | React + Vite + React Flow：节点面板拖拽、端口连线、参数编辑、保存/加载、新建、JSON 导入导出、运行状态着色与结果预览 |

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

### 方式二：Docker Compose

```bash
docker compose up --build
# 前端 http://localhost:8080
```

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
cd backend && .venv/bin/python -m pytest tests/ -q   # 30 个用例
```

覆盖：节点注册/规格/参数解析、DAG 拓扑/环检测/端口校验、执行引擎（线性/菱形并行/失败传播/序列化）、API 层。

## 目录结构

```
quantflow/
├── .github/workflows/     # GitHub Actions CI（backend 单测 / frontend 构建 / Docker 构建）
├── deploy/                # 生产部署：deploy.sh + systemd 单元
├── backend/
│   ├── app/
│   │   ├── core/          # 节点、注册表、DAG、执行器、数据类型、工作流仓储
│   │   ├── nodes/         # 内置节点库（@work_node 注册）
│   │   ├── api/           # workflows.py 路由
│   │   ├── models/        # Pydantic 契约
│   │   ├── config.py
│   │   └── main.py
│   └── tests/             # 30 用例
└── frontend/
    ├── src/               # App.jsx / WorkflowNode.jsx / api.js / styles.css
    ├── server.mjs         # 生产静态服务 + /api 反代（零依赖）
    └── package.json
```

## M1 待办（后续迭代）

- [ ] Mongo/Redis 数据访问层（当前内存态）
- [ ] WebSocket 运行状态实时推送
- [x] 工作流持久化 + JSON 导入导出（M1 内存仓储，MongoDB 持久化后续接入）
- [ ] 基金回测技术方案预研（Q-01 决策：纳入 V1.0）
- [x] GitHub Actions CI（backend 单测 / frontend 构建 / Docker 构建）
- [x] 生产部署脚本与 systemd 单元（deploy/）
