#!/usr/bin/env bash
#
# heartbeat.ziwi.cn 一键部署脚本
# ------------------------------------------------------------
# 在 CVM (193.112.163.147) 上以 root 运行。
#
# 前置：
#   1. 已将 heartbeat/ 整目录 scp 到 $PROJECT_DIR
#   2. *.ziwi.cn 通配符证书已由 acme.sh 签发并存于 /root/.acme.sh/*.ziwi.cn_ecc/
#      （与 cloud.ziwi.cn 共用，无需重新签发）
#   3. 宿主机已装 docker + docker compose + nginx
#
set -euo pipefail

# ---------- 可配置变量 ----------
PROJECT_DIR="${PROJECT_DIR:-/opt/heartbeat}"
DOMAIN="heartbeat.ziwi.cn"
WILDCARD="*.ziwi.cn"
CERT_DIR="/root/.acme.sh/${WILDCARD}_ecc"
NGINX_CONF_SRC="${PROJECT_DIR}/deploy/nginx/${DOMAIN}.conf"
NGINX_CONF_DST="/etc/nginx/conf.d/${DOMAIN}.conf"

log(){ echo "==> $*"; }

log "[0/8] 前置检查"
command -v docker >/dev/null  || { echo "ERROR: docker 未安装"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose 未安装"; exit 1; }
command -v nginx >/dev/null || { echo "ERROR: nginx 未安装"; exit 1; }
echo "端口占用 (80/443/8091)："
for p in 80 443 8091; do
  if ss -ltn 2>/dev/null | grep -q ":${p} "; then
    echo "  ⚠️  端口 ${p} 已被占用"
  else
    echo "  ✅ ${p} 空闲"
  fi
done

log "[1/8] 代码落盘确认"
[ -d "$PROJECT_DIR" ] || { echo "ERROR: $PROJECT_DIR 不存在，请先 scp heartbeat/ 到该路径"; exit 1; }
cd "$PROJECT_DIR"

log "[2/8] .env 配置"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    已复制 .env.example -> .env，请编辑 HEARTBEAT_API_KEY"
  echo "    ⚠️  请务必修改默认 API Key！"
fi

log "[3/8] 起服编排 (docker compose up -d --build)"
docker compose up -d --build
echo "    等待 heartbeat-backend /health ..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8091/health >/dev/null 2>&1; then
    echo "    heartbeat-backend 健康 ✅"
    break
  fi
  [ "$i" -eq 30 ] && { echo "ERROR: backend 30s 内未就绪，查 docker compose logs"; exit 1; }
  sleep 2
done

log "[4/8] SSL 证书（复用 acme.sh 已签发的 *.ziwi.cn 通配符，不做重签）"
if [ -f "${CERT_DIR}/fullchain.cer" ]; then
  echo "    证书 ${CERT_DIR}/fullchain.cer 已存在，直接复用 ✅"
else
  echo "ERROR: 未找到 ${CERT_DIR}/fullchain.cer。heartbeat.ziwi.cn 依赖共享 *.ziwi.cn 通配符证书。"
  exit 1
fi

log "[5/8] nginx 落盘 + 重载"
cp "$NGINX_CONF_SRC" "$NGINX_CONF_DST"
nginx -t && systemctl reload nginx
echo "    nginx 已加载 ${DOMAIN}"

log "[6/8] 验证（非阻断，失败仅告警）"
echo -n "  /health        : "
curl -fsS "https://${DOMAIN}/health" 2>/dev/null || echo "  ⚠️ 检查 backend"
SOURCE_API_KEY=$(grep HEARTBEAT_API_KEY .env 2>/dev/null | cut -d= -f2 || echo "")
if [ -n "$SOURCE_API_KEY" ]; then
  echo -n "  /api/v1/status : "
  curl -fsS -H "X-Api-Key: ${SOURCE_API_KEY}" "https://${DOMAIN}/api/v1/status" 2>/dev/null | head -c 200 || echo "  ⚠️ 检查 API"
fi
echo

log "[7/8] 监控建议"
echo "    请在 uptime-kuma 添加 https://${DOMAIN}/health 探测 (5min 间隔)"

log "[8/8] 完成 🎉"
echo "    验证：curl -H 'X-Api-Key: <your-key>' https://${DOMAIN}/api/v1/status"
echo "    ⚠️  安全待办：确认 HEARTBEAT_API_KEY 已从默认值修改"
echo "    ⚠️  对接文档：${PROJECT_DIR}/INTEGRATION.md"
