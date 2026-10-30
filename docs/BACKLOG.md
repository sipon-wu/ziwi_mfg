# 未闭项备忘（BACKLOG）

> **这是唯一的未闭项台账。** 所有"发现了但本轮不做"的东西都往这里记一条，
> 做完划掉并写上 commit。不要在别处另开清单 —— 双台账必乱。
>
> 维护规则：
> - 新增项写清「现象 / 影响 / 一行根因 / 验收方式」，否则三个月后没人看得懂
> - 状态只有三种：`待拍板` / `已排期` / `已闭`
> - 已闭项保留在表里不删（留痕），只改状态 + 补 commit
>
> 最后更新：2026-10-30

---

## 一、待拍板

| # | 项 | 现象 | 影响 | 一行根因 | 验收方式 |
|---|---|---|---|---|---|
| B-1 | **角色增删改界面** | 「系统管理 → 角色权限」只能给**已有**角色勾权限，不能新建角色、不能改名、不能删角色 | 客户上线时角色清单是死的（9 个种子角色），任何组织差异都得改代码/改库 | 只做了 `role_permission`（授权）页，没做 `role` 本身的 CRUD 页；后端 `RoleService` 有 create/update/delete，但 `delete` 之外的界面缺失 | 界面能新建「仓库主管」并配权，新角色用户登录即生效；删角色时 `user_roles` 有引用返回 409 |
| B-4 | **`SCOPE_FALLBACK = SCOPE_ALL`** | 角色 `scope` 为空/非法时退回 `ALL` | 配错一个角色就静默放开全公司数据，且没有任何日志 | `constants/modules.py:127` 有意选的宽松兜底 | 改为 `DEPT` 兜底并打 WARN；或至少在启动时校验所有角色 scope 合法 |
| B-5 | **`issue_orders.department_id` 被当成组织列** | 白名单里 `issue_orders → department_id`（领用部门），而 `_inject_org_owner` 会在 INSERT 未显式带该列时写入**创建人主组织** | 二车间的人替一车间开领料单，若前端没传 `department_id` 会被静默写成二车间 | 为了不加冗余列而复用了业务列，语义被混淆 | 领料单 `department_id` 必须由调用方显式给；`_inject_org_owner` 对 `department_id` 这类"业务列复用"应跳过注入 |
| B-6 | **`warehouse_repo.py` 疑似死代码** | 该文件里有第二套 `InventoryTransactionRepository` / `InventoryRepository`，与 `wms_repo.py` 重复；除注释外无任何 import | 两套同名类长期并存，改一处漏一处（本次加 org_id 就要同时看两个文件） | 早期仓储模块拆分未收尾 | 确认无引用后删除；删前用 `pytest` + 全模块回归兜底 |

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
| C-6 | 删角色留孤儿 | 前序 | 删前查 `user_roles` |
| C-7 | 试产转量产只翻状态位 | `a9f6411` | 一并建 BOM 快照 + 成品档案 |
| C-8 | 页内动作不受权限约束 | `76a877c` | `v-perm` 按钮门 |
| C-9 | 成品无物料档案 → 完工入库恒 skipped | `a335402` | `material_sync.py` 幂等补建 |
| C-10 | 建单不回 id / 完工结果不可见 | `b98c283` | `utils/error.ts` + 结果弹窗 |
| C-11 | 权限只记日志不阻断 | `a20b2ef` | `PERMISSION_ENFORCE` 默认 true |
| C-12 | **参数化路由完全绕过权限** | `a20b2ef` | `_RouteMatcher` 模板正则；394 条路由逐条验证 |
| C-13 | **子表组织归属**（原 B-2） | 本批 | 3 张子表补 `org_id` + 登记白名单 + 迁移回填；派生 repo 统一 `inherit_context_from` |
| C-14 | **种子用户全在根节点、数据范围无法验证**（原 B-3） | 本批 | 新增 `demo_ws1_leader` 挂真实部门；`verify_permissions.py` 增加"严格小于 admin"断言 |
| C-15 | **deploy.sh 只跑一个迁移** | 本批 | 改为按文件名全量循环执行；此前 20261028 之后的 6 个迁移从未在 staging 执行过 |

---

## 四、只记录、不打算做（明确排除）

写在这里是为了以后有人提起来时能一句话回答"为什么不做"。

| 项 | 为什么不做 |
|---|---|
| 数据库层 RLS（PostgreSQL Row Level Security） | 应用层 `ORG_SCOPED_TABLES` + `tenant_id` 注入已覆盖；RLS 要求连接级 set_config，与 async 连接池/多租户混用风险高于收益 |
| `inspection_result.spec_value` 改数值型 | 实测存的是区间描述（`39.95~40.05`、`0~1.6`），不是单值，改类型会丢信息 |
| 报工工时按小时自动折算（`labor_hours` 由上下班打卡算） | 需要考勤模块，属 Phase 3；当前手工填 |
