#!/usr/bin/env bash
#
# mfg 预发布部署对齐脚本（固化 2026-07-12 实战验证过的步骤）
# 用途：把 git 源码同步到 CVM 运行副本并安全重建 backend 容器。
# 设计约束（来自踩坑）：
#   - 运行容器 mfg1-backend 基于 deploy/backend/（compose 内 build context=./backend），
#     不是 git 跟踪的 backend/；git pull 只更新 backend/，必须 rsync 到 deploy/backend/ 才生效。
#   - 绝不能动 mfg1-db（数据卷 mfg_pgdata），只用 --no-deps 重建 backend。
#   - container_name 固定 mfg1-backend，up 前需先 rm 旧容器避免撞名。
# 用法：在 CVM 上 /opt/ziwi/mfg 目录执行 ./deploy.sh
set -euo pipefail

REPO_DIR="/opt/ziwi/mfg"
cd "$REPO_DIR"

echo "[1/5] 清理可能挡 git pull 的游离迁移文件（已知 blocker，幂等）"
rm -f backend/migrations/add_work_order_status_logs_tenant_id.sql || true

echo "[2/5] 拉取 origin/main（仅更新 backend/ 源码；CVM 上 backend/ 是纯部署目标，勿直接改）"
git checkout -- . || true
git pull --ff-only

echo "[3/5] rsync backend/ -> deploy/backend/（保留 deploy 的优化 Dockerfile）"
rsync -a --exclude=Dockerfile --exclude=.git backend/ deploy/backend/

echo "[4/5] 重建 mfg1-backend（不碰 mfg1-db）"
cd deploy
docker rm -f mfg1-backend 2>/dev/null || true
docker compose up -d --no-deps --build mfg-backend

echo "[5/5] 等待健康 + 轻量验证"
sleep 12
docker ps --filter name=mfg1-backend --format "{{.Names}} | {{.Status}}"
curl -s -o /dev/null -w "health: %{http_code}\n" http://localhost:8092/health || echo "health check skipped/failed"
echo "DEPLOY DONE"
