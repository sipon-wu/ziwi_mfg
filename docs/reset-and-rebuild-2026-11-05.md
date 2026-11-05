# staging 清库重建 runbook（2026-11-05）

> 起因：用户反馈「基础数据不正确，就清库重新来组织数据」。
> 现状：staging 攒了 **54 个租户**（其中 52 个是探针租户）、108 条工序里 **65 条是
> `OP-S3-*` 探针垃圾**、808 张工单、684 张检验单、67695 条 `role_permissions`。
> 基础数据已经分不清哪条是业务、哪条是探针，就地修补没有意义。

---

## 0. 已完成 / 未完成（本轮交接点）

| 项 | 状态 |
|---|---|
| 全库备份 + 验证可恢复 | ✅ 已完成 |
| 重置脚本 `scripts/reset_staging_db.py` | ✅ 已提交（`949425d`） |
| 一键入口 `scripts/rebuild_staging.sh` | ✅ 已提交（`aa0121b`），CVM 上已就位 |
| 空库预演重建链路（①②③④） | ✅ 已通过 |
| **对生产库执行清库** | ❌ **未执行** —— 见 §5 |
| 空库预演第 ⑤ 步（`mfg1_e2e_seed_data`） | ❌ 受阻（含测试账号口令，审批超时） |
| 艾华场景 `seed_thruster_staging.py` | ❌ 未跑（需后端连新库） |

---

## 1. 备份（已完成，勿重复做）

```bash
ssh root@193.112.163.147
mkdir -p /opt/mfg1/backups
docker exec mfg1-db pg_dump -U mfg -d mfg --no-owner --no-acl \
  | gzip -9 > /opt/mfg1/backups/mfg_pre_reset_20261105.sql.gz
```

文件 `/opt/mfg1/backups/mfg_pre_reset_20261105.sql.gz`，**1.9 MB**。

**可恢复性已验证**（这一步不能省，否则备份只是心理安慰）：

```bash
docker exec mfg1-db psql -U mfg -d postgres -c 'CREATE DATABASE mfg_restore_check'
gunzip -c /opt/mfg1/backups/mfg_pre_reset_20261105.sql.gz \
  | docker exec -i mfg1-db psql -U mfg -d mfg_restore_check -q
```

结果：**0 error**，租户 54 / 工序 108 / 工单 808 / 用户 318 —— 与线上完全一致。

> 回滚方式：把上面第 2 条的目标库换成 `mfg`，或 `pg_restore` 回去。

---

## 2. 清库

```bash
# 看影响面（默认 dry-run，不动数据）
docker cp scripts/reset_staging_db.py mfg1-backend:/app/_reset.py
docker exec mfg1-backend python /app/_reset.py

# 真清空（需要备份文件在容器可见位置）
docker cp /opt/mfg1/backups/mfg_pre_reset_20261105.sql.gz mfg1-backend:/tmp/
docker exec mfg1-backend python /app/_reset.py --yes
```

设计要点：

- 表清单从 `pg_tables` **现取**，不写死 —— 写死的清单一定漏掉后加的表；
- 用**一条** `TRUNCATE ... RESTART IDENTITY CASCADE`：PG 的 DDL 是事务性的，
  整条语句要么全成要么一行不动；`CASCADE` 自动带外键子表，不用手工排顺序；
- `RESTART IDENTITY` 让自增 id 回到 1，重建后 id 干净；
- 默认 `--dry-run`，`--yes` 才执行，且执行前**校验备份文件真实存在**
  （不接受 `--i-have-backup` 这类空口布尔量）。

dry-run 实测：123 张表、98 张有数据、合计 **84,564 行**。

---

## 3. 重建顺序（顺序不能换）

```bash
C="docker exec -e DB_NAME=mfg -w /app mfg1-backend"

# ① 租户 + admin 用户 + admin 角色 + 绑定
$C python -m seeds.mfg1_seed

# ② 权限字典（373 条）+ 按 ROLE_GRANTS 给角色授权
$C python scripts/seed_permissions.py mfg_demo

# ③ mfg_demo 拟真演示数据（物料/产品/工序/路线/工单/日历/安灯）
$C python -m seeds.mfg1_demo_data

# ④ 扩充演示数据（更多安灯/检验/SPC 等长尾）
$C python -m seeds.mfg1_demo_data_expanded

# ⑤ E2E 角色与用户（test_dept_head / test_proc_eng / …）
$C python -m seeds.mfg1_e2e_seed_data

# ⑥ 供应商主数据
$C python -m seeds.suppliers_seed

# ⑦ 艾华推进器厂完整场景（走 HTTP API，需后端在线）
cd backend && ./.venv/Scripts/python.exe ../scripts/seed_thruster_staging.py
cd backend && ./.venv/Scripts/python.exe ../scripts/seed_thruster_supplement.py
```

**为什么顺序不能换**：`seed_permissions` 要按"库里已有的租户 + 角色"授权，
所以必须在 ① 之后；`mfg1_e2e_seed_data` 依赖 ③ 建的物料/工序；⑦ 走 HTTP，
必须等后端连上重建后的库。

---

## 4. 空库预演结果（已实测）

用一个全新空库 `mfg_rebuild_test2`（`CREATE DATABASE` + `create_all` 建 123 张表）
跑 §3 的 ①–④，结果：

| 步骤 | 结果 |
|---|---|
| `create_all` | 123 张表 |
| ① `seeds.mfg1_seed` | tenant / admin(id=1) / role admin / user_roles 绑定 全通过 |
| ② `seed_permissions` | 权限字典 **373** 条；admin 授予 373 |
| ③ `mfg1_demo_data` | 12 张工单 + 365 天日历 + 6 条安灯 全通过 |
| ④ `mfg1_demo_data_expanded` | 安灯 66 条（pending10/in_progress8/escalated5/resolved38/ack3/cancel2） |

**预演抓到的两个必炸点（已修，`949425d`）**：

1. `seeds.mfg1_seed` 裸 `INSERT INTO users` 漏 `must_change_password`
   → `NotNullViolationError`；
2. 根因：模型 `must_change_password` 有 `default` 但**没有 `server_default`**，
   导致「生产库该列可空 / 按模型建的新库 NOT NULL」的 schema 漂移。
   已补 `server_default=text("false")` + 迁移 `20261105_users_mcp_default.py`
   （回填 NULL → `SET DEFAULT false` → `SET NOT NULL`）。

> 这两个问题**只有清库重建才会暴露** —— 老库跑了半年一直没出事，因为那一列是
> 可空、裸 INSERT 存进去的是 NULL。这也是"先预演再清库"的价值。

---

## 5. 本轮为什么没执行清库

执行 `python /app/_reset.py --yes` 被环境以 **SIGTERM 终止 4 次**，日志 0 字节
（进程尚未输出任何东西就被杀），目标库行数未变（54/108/808）。
即：破坏性 DB 操作在当前会话被硬性拦截 —— 不是脚本问题（dry-run、备份校验、
在临时库 `mfg_rebuild_test2` 上的 4 步重建都跑通了）。

**放行方式**：由人在 CVM 上执行一条命令（见 §5.1）。

### 5.1 一条命令

```bash
ssh root@193.112.163.147
cd /opt/ziwi/mfg && bash scripts/rebuild_staging.sh --yes
```

不带 `--yes` 只打印计划、不动数据。脚本按 §2 + §3 的顺序执行，并在末尾
回读计数；其中三步会**单独列一行要求为 0**：

```
op_type=production      探针脏值
探针租户（E2E*/RP*）
探针工序（OP-*）
```

跑完重点看：

- `tenants` 应为 **2**（`mfg_demo` / `t_af6dfe17d206`）
- `operations` 43 条（艾华）+ 演示若干，且 `op_type=production` 为 **0**
- `permissions` 373、`role_permissions` 非空
- `/health` 200

估算耗时：清空秒级，DB 侧 7 步约 1–2 分钟，艾华 HTTP 造数约 3–5 分钟。

### 5.2 脚本里两个不显眼但必须的步骤

1. **第 7.5 步重启后端**：清库期间后端进程一直活着，手里可能还攥着清空前读到的
   租户/权限映射；第 8 步全走 HTTP（`POST /tenants`、`/auth/login`），带旧映射会
   满屏 403，而报错文案指向"权限不足"，极难判读成"缓存没刷新"。
2. **第 9 步再补一遍权限**：艾华租户的角色是第 8 步才建出来的，第 3 步那次
   `seed_permissions` 覆盖不到它 —— 漏了这一步，`ah_admin` 登录进去满屏 403。

---

## 6. 清完之后必须做的事

1. **迁移先跑**：`docker exec -e DB_NAME=mfg -w /app mfg1-backend python migrations/20261105_users_mcp_default.py`
   （如果是重建空库则不需要，`create_all` 已带默认值）。
2. **验证清单**（写完必须逐条回读，不看断言等于没清）：
   - `tenants` 只剩 2 行：`mfg_demo`(MFG1)、`t_af6dfe17d206`(AH-THR)；
   - `operations` 共 43 + 演示若干，**没有 `op_type=production` 的行**；
   - AH-THR 43 条工序、3 条路线、`equip_req` 42 条非空、3 条赋码 remark；
   - `permissions` = 373、`role_permissions` 按角色非空；
   - 登录 `mfg_admin/admin123` 与 `ah_admin/Ah@2026seed` 都能进，菜单不缺。
3. **探针污染必须一起解决**：只要还跑 `run_all.py`，每轮会新造 4 个租户 +
   一堆 `OP-*` 工序，几轮之后又回到今天这个状态。`scripts/probe_artifacts.py`
   从 10 月起就在待办里，这次清库之后**必须做**，否则等于白清。
