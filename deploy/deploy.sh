#!/bin/bash
# QuantFlow 生产部署脚本（Debian/Ubuntu + systemd）
# 用法：sudo bash deploy/deploy.sh
# 默认部署目录 /opt/quantflow/QuantFlow，可通过 QF_DIR 覆盖
set -euo pipefail

QF_DIR="${QF_DIR:-/opt/quantflow/QuantFlow}"
QF_BACKEND_PORT="${QF_BACKEND_PORT:-8100}"
QF_FRONTEND_PORT="${QF_FRONTEND_PORT:-8080}"
QF_CORS_ORIGINS="${QF_CORS_ORIGINS:-http://localhost:${QF_FRONTEND_PORT}}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "==> [1/5] 同步代码到 $QF_DIR"
mkdir -p "$QF_DIR"
rsync -a --delete \
  --exclude backend/.venv --exclude backend/.pytest_cache \
  --exclude frontend/node_modules --exclude frontend/dist \
  "$REPO_DIR/" "$QF_DIR/"

echo "==> [2/5] 安装后端依赖（venv + uvicorn :$QF_BACKEND_PORT）"
cd "$QF_DIR/backend"
python3 -m venv .venv
.venv/bin/pip install --no-cache-dir -r requirements.txt

echo "==> [3/5] 构建前端（node 静态服务 :$QF_FRONTEND_PORT）"
cd "$QF_DIR/frontend"
npm ci --no-audit --no-fund
npm run build

echo "==> [4/5] 安装 systemd 单元"
sed -e "s|WorkingDirectory=.*|WorkingDirectory=$QF_DIR/backend|" \
    -e "s|ExecStart=.*|ExecStart=$QF_DIR/backend/.venv/bin/uvicorn app.main:app --host 127.0.0.1 --port $QF_BACKEND_PORT|" \
    -e "s|QF_CORS_ORIGINS=.*|QF_CORS_ORIGINS=$QF_CORS_ORIGINS|" \
    deploy/systemd/quantflow.service > /etc/systemd/system/quantflow.service
sed -e "s|WorkingDirectory=.*|WorkingDirectory=$QF_DIR/frontend|" \
    -e "s|ExecStart=.*|ExecStart=/usr/bin/node $QF_DIR/frontend/server.mjs|" \
    deploy/systemd/quantflow-frontend.service > /etc/systemd/system/quantflow-frontend.service
systemctl daemon-reload

echo "==> [5/5] 启动服务"
systemctl enable --now quantflow.service quantflow-frontend.service
systemctl restart quantflow-frontend.service
systemctl restart quantflow.service

echo "==> 完成：前端 http://<host>:${QF_FRONTEND_PORT}  （/api 反代到 :${QF_BACKEND_PORT}）"
