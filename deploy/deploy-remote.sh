#!/bin/bash
# QuantFlow 增量远程部署（仅同步应用代码，不重装 venv / 不重跑 npm ci）
# 适用：依赖未变更、仅 app 代码/前端构建产物更新时，快速热更到生产主机。
# 前置：本机已可免密 SSH 到 $QF_HOST；前端已本地 `npm run build` 生成 dist。
#
# 用法：
#   bash deploy/deploy-remote.sh            # 部署后端+前端并重启
#   bash deploy/deploy-remote.sh --skip-frontend
#   bash deploy/deploy-remote.sh --skip-backend
#
# 环境变量：
#   QF_HOST        (默认 116.62.188.165)
#   QF_SSH_USER    (默认 root)
#   QF_DIR         (默认 /opt/quantflow/QuantFlow)
#   QF_FE_PORT     (默认 8080，用于 health 探测)
set -euo pipefail

QF_HOST="${QF_HOST:-116.62.188.165}"
QF_SSH_USER="${QF_SSH_USER:-root}"
QF_DIR="${QF_DIR:-/opt/quantflow/QuantFlow}"
QF_FE_PORT="${QF_FE_PORT:-8080}"
REPO_DIR="$(cd "$(dirname "$0")/.." && pwd)"

SKIP_BACKEND=0
SKIP_FRONTEND=0
for a in "$@"; do
  case "$a" in
    --skip-backend) SKIP_BACKEND=1 ;;
    --skip-frontend) SKIP_FRONTEND=1 ;;
  esac
done

SSH="ssh -o StrictHostKeyChecking=no -o ConnectTimeout=15 -o BatchMode=yes ${QF_SSH_USER}@${QF_HOST}"

echo "==> 检测主机可达性 ${QF_SSH_USER}@${QF_HOST}"
if ! $SSH 'echo OK' >/dev/null 2>&1; then
  echo "❌ 主机不可达（SSH 超时 / 网络抖动）。请稍后重试或确认网络。" >&2
  exit 3
fi
echo "✅ 主机可达"

if [[ "$SKIP_BACKEND" != "1" ]]; then
  echo "==> [1] 同步后端 app/ 到 $QF_DIR/backend"
  tar czf - --exclude='__pycache__' -C "$REPO_DIR/backend" app \
    | $SSH "mkdir -p $QF_DIR/backend && cd $QF_DIR/backend && tar xzf -"
  echo "✅ 后端同步完成"
fi

if [[ "$SKIP_FRONTEND" != "1" ]]; then
  echo "==> [2] 同步前端 src/ + dist/ 到 $QF_DIR/frontend"
  if [[ ! -d "$REPO_DIR/frontend/dist" ]]; then
    echo "⚠️  未找到 frontend/dist，请先在本地执行 npm run build" >&2
    exit 4
  fi
  tar czf - --exclude='node_modules' -C "$REPO_DIR/frontend" src dist server.mjs \
    | $SSH "mkdir -p $QF_DIR/frontend && cd $QF_DIR/frontend && rm -rf dist && tar xzf -"
  echo "✅ 前端同步完成（已清理旧 dist 残留的陈旧 bundle）"
fi

echo "==> [3] 重启服务"
$SSH "systemctl restart quantflow.service quantflow-frontend.service"
echo "✅ 服务已重启"

echo "==> [4] 探测健康端点 /api/health"
HEALTH=""
for i in $(seq 1 10); do
  HEALTH="$($SSH "curl -fsS http://127.0.0.1:${QF_FE_PORT}/api/health" 2>/dev/null || true)"
  [[ -n "$HEALTH" ]] && break
  sleep 1
done
if [[ -z "$HEALTH" ]]; then
  echo "⚠️  健康探测失败，请登录主机检查日志：journalctl -u quantflow.service -u quantflow-frontend.service" >&2
  exit 5
fi
echo "✅ 健康检查通过：$HEALTH"
