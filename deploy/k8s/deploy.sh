#!/usr/bin/env bash
# QuantFlow K8s 部署辅助脚本
#
# 前置：
#   1. kubectl 已配置目标集群上下文（kubectl cluster-info 可用）
#   2. 镜像已构建并推送到集群可访问的 registry；
#      本地 kind / minikube 可直接用 :latest（imagePullPolicy: IfNotPresent）
#   3. 生产环境先覆盖 Secret：
#        kubectl -n quantflow create secret generic quantflow-secret \
#          --from-literal=QF_SECRET_KEY="$(openssl rand -hex 32)" \
#          --dry-run=client -o yaml | kubectl apply -f -
#
# 用法：
#   ./deploy.sh build      # 构建 backend / frontend 镜像（本地/CI 用）
#   ./deploy.sh apply      # kubectl apply -k . （默认）
#   ./deploy.sh status     # 查看 quantflow 命名空间资源
#   ./deploy.sh delete     # 删除整个 quantflow 命名空间

set -euo pipefail

DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

REGISTRY="${QUANTFLOW_REGISTRY:-}"   # 留空则仅打本地 tag

build_images() {
  echo ">> 构建 backend 镜像"
  docker build -t "${REGISTRY:-}quantflow-backend:latest" ../backend
  echo ">> 构建 frontend 镜像"
  docker build -t "${REGISTRY:-}quantflow-frontend:latest" ../frontend
  if [[ -n "$REGISTRY" ]]; then
    docker push "${REGISTRY}quantflow-backend:latest"
    docker push "${REGISTRY}quantflow-frontend:latest"
  fi
}

case "${1:-apply}" in
  build) build_images ;;
  apply)
    kubectl apply -k .
    echo ">> 已提交资源，等待就绪："
    kubectl -n quantflow rollout status deployment/quantflow-backend --timeout=120s || true
    kubectl -n quantflow rollout status deployment/quantflow-worker --timeout=120s || true
    kubectl -n quantflow rollout status deployment/quantflow-frontend --timeout=120s || true
    ;;
  status) kubectl -n quantflow get all ;;
  delete) kubectl delete namespace quantflow ;;
  *)
    echo "用法: $0 [build|apply|status|delete]"
    exit 1
    ;;
esac
