#!/usr/bin/env bash
#
# 环境漂移检查（修路计划③）
# 比对 CVM 实际运行版本 vs GitHub origin/main tip；不一致即告警（默认退出码 1）。
# 双保险（可选）：比对前端 index.html 引用的 chunk hash 是否仍被部署目录引用。
#
# 环境变量：
#   SCKEY   Server酱 SendKey；设置后不一致会自动推送告警
# 用法：./deploy/check_drift.sh
set -uo pipefail

REPO_DIR="/opt/ziwi/mfg"
cd "$REPO_DIR"

GITHUB_TIP=$(git ls-remote origin main | awk '{print $1}')
DEPLOYED=$(git rev-parse HEAD)

echo "github main tip : $GITHUB_TIP"
echo "deployed HEAD   : $DEPLOYED"

if [ "$GITHUB_TIP" != "$DEPLOYED" ]; then
  MSG="[DRIFT] mfg1 staging 落后 main: deployed=$DEPLOYED github=$GITHUB_TIP"
  echo "$MSG"
  if [ -n "${SCKEY:-}" ]; then
    curl -s -G "https://sctapi.ftqq.com/${SCKEY}.send" \
      --data-urlencode "title=mfg1 环境漂移告警" \
      --data-urlencode "desp=$MSG" || true
  fi
  exit 1
else
  echo "OK: staging == main ($(git rev-parse --short HEAD))"
fi
