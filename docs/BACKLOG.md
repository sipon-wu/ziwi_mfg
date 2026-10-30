# 未闭项备忘（BACKLOG）

> **这是唯一的未闭项台账。** 所有"发现了但本轮不做"的东西都往这里记一条，
> 做完划掉并写上 commit。不要在别处另开清单 —— 双台账必乱。
>
> 维护规则：
> - 新增项写清「现象 / 影响 / 一行根因 / 验收方式」，否则三个月后没人看得懂
> - 状态只有三种：`待拍板` / `已排期` / `已闭`
> - 已闭项保留在表里不删（留痕），只改状态 + 补 commit
>
> 最后更新：2026-11-01

---

## 一、待拍板

| # | 项 | 现象 | 影响 | 一行根因 | 验收方式 |
|---|---|---|---|---|---|
| B-7 | **`wms_realistic_e2e.py` 硬编码 staging id** | 脚本里 `WID = 45`、`MID = 115`、`order_id = 34` 是 staging 上的真实 id | 指向本地库跑时，登录/建单都能过（SQLite 无外键约束），于是**静默造出一批 material_id/warehouse_id 指向不存在记录的孤儿单**，然后卡在库存断言上 | 脚本为 staging 一次性验证写的，没做靶场自举 | 改成"先按编码查/建物料与仓库，再拿 id"，或加前置校验：id 不存在直接退出并提示"本脚本仅限 staging" |
| B-8 | **9 个种子角色里只有 `admin` 带 `is_system=1`** | 其余 8 个（`department_head` / `inspector` / `quality_engineer` …）界面上「删除」按钮可点 | 客户可以把平台预置的角色删掉；`seed_permissions.py` 按 code 授权，删掉后重跑种子只会报 "unmatched_roles"，不会自动重建 | 早期 `roles` 表只有 admin 标了 `is_system`，后续加角色时没有统一约定 | 二选一：①把 8 个种子角色统一标 `is_system=1`；②在 `seed_permissions.py` 里补"角色不存在则按内置定义重建" |


## 二、已排期

（无）

## 三、已闭

| # | 项 | commit | 备注 |
|---|---|---|---|
| C-1 | 工单状态可任意跳 | 前序 | 状态机 `WORK_ORDER_TRANSITIONS` |
| C-2 | 报工入参无断言 | 前序 | `output_qty + scrap_qty > 0` |
| C-3 | SPC 判异只飘红不开 NCR | `2873fdf` | `get_by_source` 幂等 |
| C-4 | 完工件数不进库存 | `e966db4` | 完工自动建生产入库单 |
| C-5 | 单号可重复（6 张单） | `f40880c` / `ebfed04` | `doc_no.py` + 6 处唯一约束 |
| C-6 | 删角色留孤儿 | 前序 | 删前先清 `user_roles`/`role_permissions`（**当时并没有"有成员则拒绝"，见 C-20**） |
| C-7 | 试产转量产只翻状态位 | `a9f6411` | 一并建 BOM 快照 + 成品档案 |
| C-8 | 页内动作不受权限约束 | `76a877c` | `v-perm` 按钮门 |
| C-9 | 成品无物料档案 → 完工入库恒 skipped | `a335402` | `material_sync.py` 幂等补建 |
| C-10 | 建单不回 id / 完工结果不可见 | `b98c283` | `utils/error.ts` + 结果弹窗 |
| C-11 | 权限只记日志不阻断 | `a20b2ef` | `PERMISSION_ENFORCE` 默认 true |
| C-12 | **参数化路由完全绕过权限** | `a20b2ef` | `_RouteMatcher` 模板正则；394 条路由逐条验证 |
| C-13 | **子表组织归属**（原 B-2） | 本批 | 3 张子表补 `org_id` + 登记白名单 + 迁移回填；派生 repo 统一 `inherit_context_from` |
| C-14 | **种子用户全在根节点、数据范围无法验证**（原 B-3） | 本批 | 新增 `demo_ws1_leader` 挂真实部门；`verify_permissions.py` 增加"严格小于 admin"断言 |
| C-15 | **deploy.sh 只跑一个迁移** | 本批 | 改为按文件名全量循环执行；此前 20261028 之后的 6 个迁移从未在 staging 执行过 |
| C-16 | **`SCOPE_FALLBACK = SCOPE_ALL`**（原 B-4） | 本批 | 收紧为 `DEPT` + 启动自检点名未配合法 scope 的角色 |
| C-17 | **`issue_orders.department_id` 被当组织列**（原 B-5） | 本批 | 拆出 `ORG_AUTO_OWNED_TABLES`：只有 `org_id` 系统列才自动补；业务列由 `create_issue_order` 显式赋默认值 |
| C-18 | **`warehouse_repo.py` 死代码**（原 B-6） | 本批 | 确认零引用后 `git rm`；15 个同名类与 `wms_repo` 重复，删掉消除"改一处漏一处" |
| C-19 | **角色增删改界面**（原 B-1） | 本批 | 左侧「+ 新建」、头部「编辑/删除」、成员区「+ 添加成员」，三处都过权限门（`canCreate`/`canUpdate`/`canDelete`/`canAddMember`）；编码创建后禁改（`/^[a-z][a-z0-9_]{1,39}$/`） |
| C-20 | **`roles.code` 无唯一约束** | 本批 | 做 C-19 时为"编码重复该给人话"写断言才发现：同编码能建出 N 个角色，`get_by_code()` 随机命中 → 权限时有时无且不报错。三层防护：模型 `UniqueConstraint(tenant_id, code)` + 服务层前置查重 + 接口层 `ValueError→400`；迁移 `20261101_roles_code_unique.py` 去重并补索引 |
| C-21 | **有成员的角色可被删除，成员权限被静默摘掉** | 本批 | `RoleService.delete` 只拦 `is_system`，不查成员；`RoleRepository.delete` 连 `user_roles` 一起清 → "删一个角色，悄悄摘掉一批人的权限"。补 `count_users()` 前置检查，返回 409 + "还有 N 名成员，请先移出" |
| C-22 | **`GET /roles/{id}/users` 返回全租户用户** | 本批 | `JOIN user_roles ur ON ur.role_id = :role_id` 少了 `ur.user_id = u.id` → `users × user_roles` 笛卡尔积。1 名成员的临时角色在界面上显示 11 人（=全租户用户数），任意角色点开都是全员。补 JOIN 条件 + 一条跑生产 SQL 的回归测试 |

---

## 四、只记录、不打算做（明确排除）

写在这里是为了以后有人提起来时能一句话回答"为什么不做"。

| 项 | 为什么不做 |
|---|---|
| 数据库层 RLS（PostgreSQL Row Level Security） | 应用层 `ORG_SCOPED_TABLES` + `tenant_id` 注入已覆盖；RLS 要求连接级 set_config，与 async 连接池/多租户混用风险高于收益 |
| `inspection_result.spec_value` 改数值型 | 实测存的是区间描述（`39.95~40.05`、`0~1.6`），不是单值，改类型会丢信息 |
| 报工工时按小时自动折算（`labor_hours` 由上下班打卡算） | 需要考勤模块，属 Phase 3；当前手工填 |
