#!/usr/bin/env bash
#
# cloud.ziwi.cn 一键部署脚本 (Phase 1)
# 整理自 cloud/deploy/runbook.md —— 由主理人齐活林编排。
# 在 CVM (193.112.163.147) 上以 root 运行。
#
# 前置：
#   1. 已将 cloud/ 整目录 scp 到 $PROJECT_DIR
#   2. *.ziwi.cn 通配符证书已由 acme.sh 签发并存于 /root/.acme.sh/*.ziwi.cn_ecc/
#      （多团队共用，cloud.ziwi.cn 直接复用，无需重新签发；严禁对他人证书账户做 --force 重签）
#   3. 宿主机已装 docker + docker compose + nginx
#
set -euo pipefail

# ---------- 可配置变量 ----------
PROJECT_DIR="${PROJECT_DIR:-/opt/cloud-idp}"
DOMAIN="cloud.ziwi.cn"
WILDCARD="*.ziwi.cn"
CERT_DIR="/root/.acme.sh/${WILDCARD}_ecc"
NGINX_CONF_SRC="${PROJECT_DIR}/deploy/nginx/${DOMAIN}.conf"
NGINX_CONF_DST="/etc/nginx/sites-available/${DOMAIN}"
NGINX_CONF_LINK="/etc/nginx/sites-enabled/${DOMAIN}"
BACKUP_DIR="/var/backups/cloud-idp/$(date +%Y%m%d-%H%M%S)"

log(){ echo "==> $*"; }

log "[0/11] 前置检查"
command -v docker >/dev/null  || { echo "ERROR: docker 未安装"; exit 1; }
docker compose version >/dev/null 2>&1 || { echo "ERROR: docker compose 未安装"; exit 1; }
command -v nginx >/dev/null || { echo "ERROR: nginx 未安装"; exit 1; }
echo "内存:"; free -h | awk 'NR==2{print "  "$0}'
echo "端口占用 (80/443/8090/3000/5433)："
for p in 80 443 8090 3000 5433; do
  if ss -ltn 2>/dev/null | grep -q ":${p} "; then echo "  ⚠️  端口 ${p} 已被占用（须与 school 栈确认不冲突）"; else echo "  ✅ ${p} 空闲"; fi
done

log "[1/11] 代码落盘确认"
[ -d "$PROJECT_DIR" ] || { echo "ERROR: $PROJECT_DIR 不存在，请先 scp cloud/ 到该路径"; exit 1; }
cd "$PROJECT_DIR"

log "[2/11] .env 配置"
if [ ! -f .env ]; then
  cp .env.example .env
  echo "    已复制 .env.example -> .env（DATABASE_URL/CORS 已预填，可按需改）"
fi

log "[3/11] DNSPod 密钥检查 (acme.sh --dns dns_dp 需要)"
if [ -n "${DP_Id:-}" ] && [ -n "${DP_Key:-}" ]; then
  export DP_Id DP_Key
  echo "    检测到 DP_Id / DP_Key 环境变量 ✅"
elif [ -f "/root/.acme.sh/account.conf" ]; then
  echo "    未设 DP_Id/DP_Key，但 acme.sh 已有账户，将复用（school 同源密钥）"
else
  echo "ERROR: 未设置 DP_Id/DP_Key 且 acme.sh 无账户。"
  echo "       请先： export DP_Id='...' ; export DP_Key='...'  (腾讯云 DNSPod API)"
  echo "       注：你说'腾讯云密钥还没修改'——若沿用 school 现用账户，请先确保 acme.sh 账户已配置。"
  exit 1
fi

log "[4/11] 起服编排 (docker compose up -d --build)"
docker compose up -d --build
echo "    等待 backend /health ..."
for i in $(seq 1 30); do
  if curl -fsS http://127.0.0.1:8090/health >/dev/null 2>&1; then echo "    backend 健康 ✅"; break; fi
  [ "$i" -eq 30 ] && { echo "ERROR: backend 30s 内未就绪，查 docker compose logs backend"; exit 1; }
  sleep 2
done

log "[5/11] SSL 证书（复用 acme.sh 已签发的 *.ziwi.cn 通配符，不做重签）"
if [ -f "${CERT_DIR}/fullchain.cer" ]; then
  echo "    证书 ${CERT_DIR}/fullchain.cer 已存在，直接复用 ✅"
else
  echo "ERROR: 未找到 ${CERT_DIR}/fullchain.cer。cloud.ziwi.cn 依赖共享 *.ziwi.cn 通配符证书，"
  echo "       请勿自行 --force 重签（会扰动 school/ecms 共用的 acme.sh 账户）。请先确认证书状态。"
  exit 1
fi

log "[6/11] nginx 落盘 + 重载"
cp "$NGINX_CONF_SRC" "$NGINX_CONF_DST"
ln -sf "$NGINX_CONF_DST" "$NGINX_CONF_LINK"
nginx -t && systemctl reload nginx
echo "    nginx 已加载 ${DOMAIN}"

log "[7/11] 验证（非阻断，失败仅告警）"
echo -n "  前端 /        : "; curl -IsS "https://${DOMAIN}/" 2>/dev/null | head -n 1 || echo "  ⚠️ 检查 nginx"
echo -n "  backend /health: "; curl -fsS "https://${DOMAIN}/health" 2>/dev/null || echo "  ⚠️ 检查 backend"
echo -n "  公钥接口      : "; curl -fsS "https://${DOMAIN}/api/v1/auth/public-key" 2>/dev/null | head -c 120 || echo "  ⚠️ 检查 /api/v1/auth/public-key"
echo

log "[8/11] 密钥备份 (cloud_keys 卷)"
mkdir -p "$BACKUP_DIR"
docker run --rm -v cloud_keys:/keys -v "$BACKUP_DIR":/backup alpine sh -c \
  'apk add --no-cache tar >/dev/null 2>&1; tar czf /backup/cloud_keys.tar.gz -C /keys .' \
  && echo "    已备份至 ${BACKUP_DIR}/cloud_keys.tar.gz" \
  || echo "  ⚠️  cloud_keys 备份失败，请手动 docker volume inspect cloud_keys"

log "[9/11] 监控建议"
echo "    请在 uptime-kuma 添加 https://${DOMAIN}/health 探测"

log "[10/11] 回滚提示"
echo "    服务回滚: docker compose down && docker compose up -d --build <上一版镜像>"
echo "    nginx 回滚: cp ${NGINX_CONF_DST}.bak ${NGINX_CONF_DST} && systemctl reload nginx"

log "[11/11] 完成 🎉"
echo "    访问 https://${DOMAIN}/ 验证登录 / 注册"
echo "    ⚠️ 安全待办：① 轮换腾讯云密钥（§11 风险项）② compose 中 CLOUD_CORS_ORIGINS=* 建议收紧为 https://${DOMAIN}"
