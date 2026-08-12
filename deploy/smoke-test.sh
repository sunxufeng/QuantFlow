#!/bin/bash
# QuantFlow Compose 冒烟验证（默认 18080 端口，可用 QF_PORT 覆盖）
# 用法：QF_PORT=18080 docker compose -f deploy/docker-compose.yml up -d && bash deploy/smoke-test.sh
B="http://127.0.0.1:${QF_PORT:-18080}"
PASS=0; FAIL=0
chk() { local name="$1" expect="$2" got="$3"; if [ "$got" = "$expect" ]; then PASS=$((PASS+1)); echo "  ✅ $name ($got)"; else FAIL=$((FAIL+1)); echo "  ❌ $name expect=$expect got=$got"; fi; }

echo "== [1] 前端页面 =="
chk "frontend index" "200" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/)"

echo "== [2] 后端健康检查（经 nginx 反代） =="
H=$(curl -s -m 10 $B/api/health)
chk "health status=ok" "ok" "$(echo "$H" | python3 -c "import sys,json;print(json.load(sys.stdin)['status'])" 2>/dev/null)"
chk "health version=1.0.0" "1.0.0" "$(echo "$H" | python3 -c "import sys,json;print(json.load(sys.stdin)['version'])" 2>/dev/null)"

echo "== [3] 未认证访问应 401 =="
chk "auth/me 无 token" "401" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/api/auth/me)"
chk "projects 无 token" "401" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/api/projects)"

echo "== [4] 注册/登录/项目 =="
U="smoke_$(date +%s)"
R=$(curl -s -m 10 -X POST $B/api/auth/register -H 'Content-Type: application/json' -d "{\"username\":\"$U\",\"password\":\"Test1234\"}")
TOKEN=$(echo "$R" | python3 -c "import sys,json;print(json.load(sys.stdin).get('token',''))" 2>/dev/null)
chk "register 拿到 token" "1" "$([ -n "$TOKEN" ] && echo 1 || echo 0)"
chk "me 接口" "200" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/api/auth/me -H "Authorization: Bearer $TOKEN")"
P=$(curl -s -m 10 -X POST $B/api/projects -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"name":"smoke-proj"}')
PID=$(echo "$P" | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
chk "创建项目" "1" "$([ -n "$PID" ] && echo 1 || echo 0)"

echo "== [5] 节点与回测 =="
chk "nodes 接口" "200" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/api/nodes -H "Authorization: Bearer $TOKEN")"
chk "backtest strategies" "200" "$(curl -s -o /dev/null -w '%{http_code}' -m 10 $B/api/backtest/strategies -H "Authorization: Bearer $TOKEN")"
BR=$(curl -s -m 60 -X POST $B/api/backtest/run -H "Authorization: Bearer $TOKEN" -H 'Content-Type: application/json' -d '{"symbols":["TEST.STOCK"],"strategy":"buy_hold","initial_cash":100000,"start":"2024-01-01","end":"2024-12-31"}')
chk "回测运行" "1" "$(echo "$BR" | python3 -c "import sys,json;d=json.load(sys.stdin);print(1 if d.get('run_id') else 0)" 2>/dev/null)"

echo ""
echo "==== 结果：PASS=$PASS FAIL=$FAIL ===="
[ "$FAIL" = "0" ]
