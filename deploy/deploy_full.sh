#!/usr/bin/env bash
#
# mfg 全量追平部署脚本（修路计划①）
# 一条命令把 CVM 上的 mfg1 追平到 origin/main：backend + frontend + ai-gateway + nginx
#
# 设计约束（来自踩坑，务必遵守）：
#   - 运行容器 mfg1-backend 基于 deploy/backend/（compose build context=./backend），
#     git pull 只更新 backend/，必须 rsync 到 deploy/backend/ 才生效。
#   - 绝不碰 mfg1-db 数据卷 mfg_pgdata；只用 --no-deps 重建 backend。
#   - nginx 1.18 的 HTTP/2 会间歇丢 POST body，已禁 h2，重启必须 restart 而非 reload。
#   - E1 ai-gateway 必须桥接到 mfg1_default 网络；且 backend 容器内访问网关要用
#     容器名，默认 AI_GATEWAY_URL=localhost:8100 在容器内无效。
#   - 关键顺序：docker restart 不会重新读取 env_file，因此 AI_GATEWAY_URL 必须在
#     重建 mfg1-backend 之前写进 deploy/backend/.env（rsync 会覆盖该文件，故先 rsync 再改 env 再重建）。
#   - 前端：历史是「本地 vite build → 同步到 /opt/mfg1/frontend」。本脚本假定
#     frontend/dist 已存在于 REPO_DIR（部署前需先把本地构建的 dist scp 到此），仅负责 rsync。
#
# 前置（协同铁律）：已在 ziwi-integration-contracts 做 pull+diff 确认无新约定。
# 用法：在 CVM 上 /opt/ziwi/mfg 目录执行  ./deploy/deploy_full.sh
set -euo pipefail

REPO_DIR="/opt/ziwi/mfg"
FRONTEND_DEST="/opt/mfg1/frontend"
cd "$REPO_DIR"

echo "[1/7] 清理可能挡 git pull 的游离迁移文件（幂等）"
rm -f backend/migrations/add_work_order_status_logs_tenant_id.sql || true

echo "[2/7] 拉取 origin/main（仅更新源码；CVM 上 backend/ 是纯部署目标，勿直接改）"
git checkout -- . || true
git pull --ff-only

echo "[3/7] rsync backend/ -> deploy/backend/（保留优化 Dockerfile；会覆盖 deploy/backend/.env）"
rsync -a --exclude=Dockerfile --exclude=.git backend/ deploy/backend/

echo "[4/7] 修正运行配置：AI_GATEWAY_URL 指向网关容器（默认 localhost:8100 在容器内无效）"
ENV_FILE="deploy/backend/.env"
if [ -f "$ENV_FILE" ]; then
  if grep -q "^AI_GATEWAY_URL=" "$ENV_FILE"; then
    sed -i 's#^AI_GATEWAY_URL=.*#AI_GATEWAY_URL=http://ziwi-ai-gateway:8100#' "$ENV_FILE"
  else
    printf '\nAI_GATEWAY_URL=http://ziwi-ai-gateway:8100\n' >> "$ENV_FILE"
  fi
  echo "    AI_GATEWAY_URL=http://ziwi-ai-gateway:8100"
else
  echo "    ⚠ $ENV_FILE 不存在，Copilot 将走降级链路"
fi

echo "[5/7] 重建 mfg1-backend（读取最新 env；不碰 mfg1-db）"
cd deploy
docker rm -f mfg1-backend 2>/dev/null || true
docker compose up -d --no-deps --build mfg-backend
docker network connect mfg1_default mfg1-backend 2>/dev/null || true
docker restart mfg1-backend 2>/dev/null
cd "$REPO_DIR"

echo "[6/7] 部署 ai-gateway（E1）+ 桥接 mfg1_default 网络"
docker compose -f ai-gateway/docker-compose.ai.yml up -d
docker network connect mfg1_default ziwi-ai-gateway 2>/dev/null || true

echo "[7/7] 同步前端 dist -> $FRONTEND_DEST（含 index.html）+ 重启 nginx（h2 坑必须 restart）"
rsync -a --delete frontend/dist/ "$FRONTEND_DEST/"
systemctl restart nginx

echo "=== 健康 + 漂移自检 ==="
sleep 10
docker ps --filter name=mfg1-backend --format "{{.Names}} | {{.Status}}"
curl -s -o /dev/null -w "backend health: %{http_code}\n" http://localhost:8092/health || echo "health skipped"
echo "DEPLOY DONE; deployed commit: $(git rev-parse HEAD)"
