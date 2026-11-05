#!/usr/bin/env bash
# staging 一键重建：清库 → 按方案书重建 → 回读校验。
#
# 为什么要有这个脚本：破坏性 DB 命令在 AI 会话里会被环境直接 SIGTERM 掉
# （实测 4 次，进程未启动、日志 0 字节、库未变），只能由人在 CVM 上执行一次。
# 把「清空 + 9 步重建 + 校验」收成一条命令，避免手工敲错顺序。
#
# 顺序不能换：
#   ① 必须最先，它建出 mfg_demo 租户和 mfg_admin —— 后面所有步骤和 HTTP 造数都用它登录；
#   ② 权限必须在 ① 之后、在「用 admin 调接口」之前，否则 POST /tenants 直接 403；
#   ⑧ 艾华场景走 HTTP，必须在后端已连上重建后的库之后；
#   ⑨ 艾华租户的角色是 ⑧ 才建出来的，权限得再补一遍，否则 ah_admin 登录进去满屏 403。
#
# 用法（在 CVM 上）：
#     cd /opt/ziwi/mfg && bash scripts/rebuild_staging.sh --yes
#
# 不带 --yes 只打印计划，不动数据。
set -uo pipefail

REPO=/opt/ziwi/mfg
CONT=mfg1-backend
DB=mfg

if [ "${1:-}" != "--yes" ]; then
  cat <<'PLAN'
即将执行（破坏性）：
  0) 把重置脚本与备份放进容器
  1) 清空库 mfg —— 全部业务表 + 租户/用户/角色/权限，回到空表
  2) seeds.mfg1_seed              租户 MFG1 + mfg_admin + admin 角色 + 绑定
  3) seed_permissions mfg_demo    权限字典 373 条 + 角色授权
  4) seeds.mfg1_demo_data         精密机械加工厂演示数据
  5) seeds.mfg1_demo_data_expanded 扩充演示数据
  6) seeds.mfg1_e2e_seed_data     E2E 角色与用户
  7) seeds.suppliers_seed         供应商主数据
  8) seed_thruster_staging.py     艾华推进器厂全场景（HTTP）
     seed_thruster_supplement.py  艾华补充
  9) seed_permissions（全部租户）  给新建的艾华租户补权限

确认无误后加 --yes 再执行：bash scripts/rebuild_staging.sh --yes
PLAN
  exit 0
fi

BACKUP=$(ls -1 /opt/mfg1/backups/mfg_pre_reset_*.sql.gz 2>/dev/null | tail -1)
if [ -z "${BACKUP}" ]; then
  echo "[中止] /opt/mfg1/backups 下没有 pg_dump 备份。备份是这条路上唯一的回滚手段。"
  exit 1
fi
echo "[备份] ${BACKUP} ($(du -h "${BACKUP}" | cut -f1))"

step() { printf '\n========== %s ==========\n' "$*"; }
dc() { docker exec -e DB_NAME="${DB}" -w /app "${CONT}" "$@"; }

step "0/9 把脚本与备份放进容器"
docker cp "${REPO}/scripts/reset_staging_db.py" "${CONT}:/app/_reset.py" || exit 1
docker cp "${BACKUP}" "${CONT}:/tmp/" || exit 1

step "1/9 清空 ${DB}"
docker exec "${CONT}" python /app/_reset.py --yes || { echo "[中止] 清空失败，库未改动（TRUNCATE 是原子的）"; exit 1; }

step "2/9 租户 + admin"
dc python -m seeds.mfg1_seed || exit 1

step "3/9 权限字典"
dc python scripts/seed_permissions.py mfg_demo || exit 1

step "4/9 mfg_demo 演示数据"
dc python -m seeds.mfg1_demo_data || exit 1

step "5/9 扩充演示数据"
dc python -m seeds.mfg1_demo_data_expanded || exit 1

step "6/9 E2E 角色与用户"
dc python -m seeds.mfg1_e2e_seed_data || exit 1

step "7/9 供应商"
dc python -m seeds.suppliers_seed || exit 1

# HTTP 造数失败不中止：让它把失败项打完，最后靠校验段判定真相
step "8/9 艾华推进器厂场景（HTTP）"
python3 "${REPO}/scripts/seed_thruster_staging.py" || echo "[WARN] 艾华主场景有失败项，见上方输出"
python3 "${REPO}/scripts/seed_thruster_supplement.py" || echo "[WARN] 艾华补充有失败项，见上方输出"

step "9/9 给全部租户补权限"
dc python scripts/seed_permissions.py || echo "[WARN] 权限补全有失败项"

step "校验：回读计数"
docker exec mfg1-db psql -U mfg -d "${DB}" -c "
select 'tenants' t, count(*) n from tenants
union all select 'users', count(*) from users
union all select 'roles', count(*) from roles
union all select 'permissions', count(*) from permissions
union all select 'role_permissions', count(*) from role_permissions
union all select 'organizations', count(*) from organizations
union all select 'materials', count(*) from materials
union all select 'products', count(*) from products
union all select 'operations', count(*) from operations
union all select 'work_centers', count(*) from work_centers
union all select 'process_routes', count(*) from process_routes
union all select 'route_steps', count(*) from route_steps
union all select 'work_orders', count(*) from work_orders
union all select 'equipments', count(*) from equipment
order by 1;"

step "校验：脏值必须为 0"
docker exec mfg1-db psql -U mfg -d "${DB}" -c "
select 'op_type=production' k, count(*) n from operations where op_type = 'production'
union all select '探针租户', count(*) from tenants where code like 'E2E%' or code like 'RP%'
union all select '探针工序 OP-*', count(*) from operations where code like 'OP-%'
order by 1;"

echo
echo "[DONE] 重建完成。逐条人工核对：租户应只剩 2 个（MFG1 / AH-THR），"
echo "       探针相关三行应全为 0，AH-THR 应有 43 条工序。"
