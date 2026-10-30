# 场景核查结论（代码级取证 · v2 · 2026-10-29）

> 输入：`docs/scenario-inventory-2026-10-29.md`（125 场景，其中 59 项标 ❓）
> 方法：逐条对照后端源码判定"校验是否存在"，不跑接口、不改代码。
> 产出：把 ❓ 收敛为 ✅ 已实现 / ⚠️ 部分实现 / ❌ 未实现，并把"未闭环"落到**具体文件行号**。
> 代码基线：`backend/app/`（372 个端点 / 27 个 api 模块）

---

## 一、结论摘要：三个结构性缺口（优先级高于原 TOP-5）

原清单的 P0-1~P0-5 都是"流程联动"，核查后发现它们**只是表象**，底下压着三层更硬的问题：

### 缺口 S1（最严重）：后端零接口级权限校验

- `grep -rn "require_permission|has_permission|check_permission" app/` → **0 命中**
- `app/main.py` 只有 CORS + request-id 两个中间件（L77、L144），无鉴权中间件
- `get_current_user`（`app/core/dependencies.py:32`）对本地用户**不加载 permissions**，仅返回用户行；权限只在 API-Key 路径（同文件 L234）被读出来
- 372 个端点全部只校验"**是否登录**"，不校验"**是否有权**"

**后果**：RBAC 四张表（`roles` / `permissions` / `role_permissions` / `user_roles`）在后端是**死数据**，任何持有效 token 的用户可调用任意接口。

### 缺口 S2：前端权限是硬编码角色名，自定义角色接不进去

- `frontend/src/router/index.ts:5-22` 定义 12 个硬编码角色组常量
  ```ts
  const R_PROD   = ['admin','department_head','team_leader','scheduler','process_engineer','key_user']
  const R_SPC    = ['admin','quality_engineer']
  const R_SYSTEM = ['admin','key_user']
  ```
- `MainLayout.vue:175` `hasAnyRole()` 只比对 `user.roles[].code` 与这些常量

**后果**：租户新建一个自定义角色（如"仓库主管"），前端路由不认它 → 菜单看不到；既然后端也不拦 → 绕开前端就全通。**"按租户职能部门配置权限"这条需求，两侧都没有承载点。**

### 缺口 S3：`organizations` 表根本不存在（部门主数据缺失）

- `grep -rn "class Organization" app/models/` → **0 命中**
- `app/models/user.py:65` 建了 `user_organizations`，其 `org_id` 注释写"指向 organizations.id，见任务 B3"——**指向了一张不存在的表**
- `app/api/roles.py:100` 注释自陈："organizations 表…本轮整个 org 树链路未建表"
- 实库只有 `teams` / `user_organizations` / `wc_teams`

**后果**：没有部门树 → 无法做"部门级模块开关"、无法做"本部门数据范围"、无法把角色挂到部门上。A-S2 / P1-1 / P1-3 全部卡在这一张表上。

---

## 二、原 TOP-5 P0 的精确化（从"未闭环"落到"缺哪个字段/哪一行"）

### P0-1 检验结果联动库存 —— 比原判断好，但断在一个外键上

**核查结果：WMS 侧其实已经有 IQC 闸门，不需要从零建。**

- 收货登记即入**待检区**：`wms_service.py:369-431`，注释明确"计入现存量、可用量不含"
- 上架（转正式台账）前有 IQC 前置校验：`wms_service.py:461-464`
  ```python
  insp = item.get("inspection_status")
  if insp == INSPECTION_DISQUALIFIED:
      raise PostingError("WMS_409_INSPECTION", "IQC 判定不合格，禁止上架确认")
  ```
- 待检区库存天然不可出库（可用量 = quantity − locked_qty，且待检区单独库存行）→ **E-E7 冻结不可出库实际已实现**

**真正的断点**：`InspectionOrder` 模型（`app/models/quality.py:55-71`）**没有入库单外键**，只有 `work_order_id` / `process_id` / `material_id`。质检员判定 REJ 时，`judge_order`（`app/api/quality.py:280`）写下 NCR 就结束了，**没有任何字段能表达"这批货不许上架"**——`inspection_status` 全靠人工维护。

**最小修复**（不含表结构变更的话无法做）：
1. `inspection_order` 增 `source_type` + `source_id`（或直接 `receipt_item_id`），让来料检验单能指向入库明细
2. `judge_order` 判定后按来源回写 `receipt_order_items.inspection_status` = `qualified` / `disqualified`
3. `INSPECTION_PENDING`（"待检"）应改为**默认不可上架**（当前 `wms_service.py:448` 注释写"为 None/待检 视为可上架（兼容）"，这是个默认放行的口子）

### P0-2 工单完工联动成品入库 —— 手工可达，自动未通

- `POST /work-orders/{id}/close`（`api/production.py:73`）只调 `change_status`，**不写任何库存**
- `receipt_orders` 有 `source_type`（po/wo/return/transfer）+ `source_doc_no`，**理论上可手工建"生产入库"单**
- 但 `receipt_orders` **无 `work_order_id` 外键**，`source_doc_no` 是字符串弱关联 → 无法 JOIN 校验"入库量 ≤ 完工量"

**修复**：`receipt_orders` 加 `work_order_id`；`close_work_order` 在完工量 > 0 时自动生成生产入库单（待检区入账）。

### P0-3 SPC 判异联动 NCR —— 确认完全断开

- `app/api/spc.py` 全文**无 `ncr` 引用**（`grep -in ncr app/api/spc.py` → 0）
- 判异只产出 `alert_rule` 字段（`spc.py:192`），停在告警展示
- NCR 侧状态机是完备的（`ncr_service.py:21-27` `NCR_TRANSITIONS`），接得上

**修复**：`spc.py` 判异命中 Weston 规则时，调用 `NcrService.create_ncr`，`source_type="spc"`、`source_id=control_limit.id`，用 `get_by_source` 做幂等。

### P0-4 试产转量产 —— **端点存在，但"一键转量产"是空转**

这个比原判更危险：功能**看起来有**，用户会以为量产主数据已生成。

- 端点确实存在：`POST /trial/{id}/convert`（`api/trial.py:299`，注释写"M16-08: 一键转量产"）
- 前置校验是**好的**（`trial_service.py:206-220`）：必须是 `review` 状态、必须有评审记录、结论必须是 `approved` / `conditional_approve`
- 但真正做的事只有两行（`trial_service.py:223-226`）：
  ```python
  await self.order_repo.update_order(order_id, {"status": "production", "completed_at": now})
  ```
  **没有写 `boms` 表、没有写工艺路线表、没有版本继承**——`product_id` 只是原样带出去做返回值。

**后果**：用户点了"转量产"，系统回"转量产成功"，但去 BOM 管理页面找不到任何正式 BOM。G-S3 / X4 的断点不在校验，在**落库**。

**修复**：`convert_to_production` 内按试产 BOM（`/trial/{id}/bom`）生成正式 `boms` 记录 + 版本号，按试产路线生成正式 routing；同时补"继承范围清单"（G-B2）。

### P0-5 报工不良联动返工 —— 确认无联动

`create_report`（`production_service.py:125-136`）只累加 `completed_qty` / `scrap_qty` 两个数，**scrp_qty > 0 不触发任何 NCR 或返工单**。

---

## 三、逐条核查结论（把 ❓ 收敛）

### C. 生产执行（最弱的一环）

| 编号 | 场景 | 结论 | 证据 |
|:--|:--|:--|:--|
| C-E1 | 报工 > 计划数 | ❌ 无校验、无告警 | `production_service.py:125` 直接累加 |
| C-E2 | 报工数量 = 0 | ❌ 无校验 | 同上，无任何 qty 断言 |
| C-E3 | 未派工直接报工 | ❌ 无派工概念 | 无派工端点、`work_orders` 无派工字段 |
| C-E4 | 工单暂停/恢复 | ❌ 无端点 | `production.py` 只有 release/close |
| C-E5 | 取消已有报工的工单 | ❌ **状态机缺失** | `change_status`（`production_service.py:35`）任意→任意，只校验存在性 |
| C-E6 | 物料未齐套下达 | ⚠️ 有提示需 force | `production_service.py:87-101` + `force_release` |
| C-E7 | 挂停用设备 | N/A | `work_orders` 无 `equipment_id` 字段 |
| C-S2 | 派工到班组/个人 | ❌ 未实现（原标 ⚠️） | 无端点无表 |
| C-S4 | 完工→成品入库 | ❌ | `production.py:73-80` |
| C-S6 | 工单拆分 | ❌ 无端点 | — |
| C-S7 | 工单合并 | ❌ 无端点 | — |
| C-B2 | 报工早于开工 | ❌ 无时序校验 | — |
| C-S1 | 创建→审核→下达 | ✅ | `release_work_order` 严格校验 `draft` + BOM 快照 + 齐套 |
| C-B3 | 同工序多次报工 | ✅ 累加 | `production_service.py:131-135` |

> **总体判断**：生产模块是 8 个模块里校验最薄的一层。157 行 service 承载工单全生命周期，`change_status` 连状态机都没有 → **任何前端 bug 都能把已完工工单改回草稿**。

### D. 品质

| 编号 | 场景 | 结论 | 证据 |
|:--|:--|:--|:--|
| D-S1 | ACC → 入库放行 | ⚠️ 闸门在，判定不写入 | `wms_service.py:461` vs `quality.py:280` 无回写 |
| D-S9 | SPC 判异 → NCR | ❌ | `spc.py` 无 ncr 引用 |
| D-E1 | 检验单无检验项 | ❌ 不校验 | `quality.py:235-254` 只生成单号 |
| D-E2 | 结果未填判定 | ⚠️ 默认 pending | `quality.py:244` |
| D-B3 | 判定后改判定 | ❌ 可反复 judge 覆盖 | `quality.py:290-293` 无锁定 |
| D-S7 | AQL 抽样 | ❌ 无表无逻辑 | — |
| D-E3/E4 | NCR 状态机 | ✅ **完备** | `ncr_service.py:21-27` 含 cancelled 终态 |
| D-E6 | SPC 点不足 2 个 | ✅ 返回 400 | 上轮已修 |

### E. 仓储（**最扎实的一环**）

| 编号 | 场景 | 结论 | 证据 |
|:--|:--|:--|:--|
| E-S1 | 采购入库→质检→上架 | ✅ **原判 ⚠️ 应上调** | 待检区 + IQC 闸门 + 三步原子过账（`wms_service.py:369-520`） |
| E-E1 | 出库 > 库存 | ✅ | `wms_service.py:245-247`、`753`、`761`、`784` |
| E-E2 | 负库存 | ✅ 同上 | 可用量 = quantity − locked_qty |
| E-E7 | 冻结不可出库 | ✅ 待检区天然隔离 | `wms_service.py:374` |
| E-B2 | 先进先出 | ✅ | `find_available_batches` + `pick_strategy` |
| E-S8 | 红冲 | ✅ 方案B 状态感知 | `receipt-orders/{id}/cancel` L478-503 |
| E-E4 | 入库单重复提交 | ❌ 单号无 unique 约束 | `models/wms.py` 全文无 `unique=True` |

> WMS 是唯一一个**有状态机常量表**（`constants/wms_constants.py:36` `RECEIPT_STATUS_TRANSITIONS`）的模块——可作为其余模块改造的模板。

### A / B / F

| 编号 | 场景 | 结论 | 证据 |
|:--|:--|:--|:--|
| A-S2 | 组织树搭建 | ❌ **表不存在** | 缺口 S3 |
| A-E2 | 删仍被引用的角色 | ❌ 直接删，留孤儿 `user_roles` | `role_service.py:58-60` |
| A-E3 | 权限变更即时生效 | ❌ 见缺口 S1 | — |
| A-E4 | 停用有在办单据的用户 | ❌ 无 `is_active` 概念 | `api/users.py` 全 68 行 |
| B-E1 | 删被 BOM 引用的物料 | ❌ 无校验 | `bom.py` / `basic_data.py` 无 referred 检查 |
| B-E3 | BOM 循环引用 | ❌ 无检测 | — |
| B-E5/E6 | 无 BOM/工艺下工单 | ⚠️ 不阻断 | `production_service.py:84-85` BOM 快照失败只记 `{"error": ...}` 仍下达 |
| F-S5 | 备件领用扣库存 | ⚠️ 表在 API 在，流程未验 | `models/tpm.py:76/93`、`api/tpm.py` |
| G-S3 | 试产转量产生成正式主数据 | ❌ **端点空转** | `trial_service.py:223-226` 只翻状态位 |

---

## 四、修正后的现状分布

| 判定 | 原清单 | 核查后 | 变化说明 |
|:--|:--|:--|:--|
| ✅ 已实现 | ~33 | **~36** | WMS 5 项上调（待检区/IQC闸门/负库存/先进先出/状态机） |
| ⚠️ 部分 | ~26 | **~18** | 8 项被精确定性为 ❌（C-S2/C-E4/C-E5/B-E5 等） |
| ❌ 未实现 | 7 | **~30** | 主要是 C 模块 11 项 + A 模块 4 项 |
| ❓ 待验证 | ~59 | **~41** | 本轮消掉 18 项；余下多为 B/F/G 模块细则 |

> 注：余下 ~41 项 `❓` 集中在 B（主数据边界）、F（设备能碳）、G（试产实验室），本轮未逐一取证。

---

## 五、修正后的优先级（替代原 TOP-10）

| 新优先级 | 问题 | 为什么排这个位置 | 工作量 |
|:--|:--|:--|:--|
| **S1** | 后端接口级权限校验为零 | **不做这个，"权限分配"就是空话**；372 端点全裸奔 | 中大：加 `require_permission` 依赖 + 路由元数据表 + 回归 |
| **S3** | `organizations` 表缺失 | **不做这个，"按职能部门配置"没有挂载点**；同时卡住 P1-1/P1-3 | 中：建表 + CRUD + 挂 user/role |
| **S2** | 前端权限硬编码 | 与 S1 同批改：权限码改为从后端取，路由 meta 改 `permission` 而非 `roles` | 中 |
| **P0-1★** | 检验单无入库单外键 | 只差一个外键 + 一次回写，投入最小、收益最大（堵住"不合格品上架"） | 小 |
| **P0-3★** | SPC 判异不建 NCR | NCR 状态机已完备，只需一个 `create_ncr` 调用 + 幂等 | 小 |
| **C-状态机** | 工单 `change_status` 无状态机 | **改 8 行**，抄 `wms_constants.py` 的写法即可 | 极小 |
| **P0-2★** | 完工不生成入库单 | 需先给 `receipt_orders` 加 `work_order_id` | 小中 |

> **排序逻辑变了**：原 TOP-10 按"业务流程完整度"排；现在按 **"堵漏洞的性价比 + 是否卡住用户的配置化目标"** 排。三个结构性缺口直接对应用户提的"按租户职能部门配置 + 权限分配"，必须先解。

---

## 六、可以直接开工的最小改动清单（按投入产出排序）

1. **工单状态机**（`production_service.py:35`）：抄 `wms_constants.py:36` 加 `WORK_ORDER_TRANSITIONS`，`change_status` 前校验。**8 行，零风险。**
2. **报工入参断言**（`production_service.py:125`）：`output_qty + scrap_qty > 0` 否则 400；超额时返回 warning 字段不阻断。**5 行。**
3. **SPC 判异建 NCR**（`spc.py` 判异处）：`NcrService.create_ncr(source_type="spc", ...)` + `get_by_source` 幂等。**~20 行。**
4. **检验单加来源外键 + judge 回写**（`models/quality.py` + `quality.py:280`）：建表变更 + `receipt_order_items.inspection_status` 回写。**~30 行 + 1 迁移。**
5. **单号唯一约束**（`models/wms.py`）：`receipt_no` / `issue_no` 加 `UniqueConstraint(tenant_id, no)`。**3 行 + 1 迁移。**
6. **角色删除保护**（`role_service.py:58`）：删前查 `user_roles` 计数，>0 则 409。**6 行。**

> 以上 6 项合起来**不动任何架构**，但能把"不合格品可出库 / 工单状态可任意改 / 过程失控无闭环 / 单号可重复 / 删角色留孤儿" 五类硬伤一次性堵住。

---

## 七、需要拍板的问题

1. **S1+S2（权限体系重做）是 Beta 前做，还是 Beta 后？** 它是唯一一项"不修就不能对外承诺权限隔离"的工作，但工作量最大。
2. **S3（组织表）本轮只建表不做界面，还是建表+界面一起？**
3. 上面第六节 6 项最小改动，**是否现在就动手**？

---

## 八、执行进展（2026-10-30 收口）

第六节清单已全部落地，另补两处本文未列出的断点（按钮级权限门、成品物料档案）。

| # | 断点 | commit | 验证 |
|---|---|---|---|
| 1 | 工单状态机可任意跳 | 前序 | pytest |
| 2 | 报工入参无断言 | 前序 | pytest |
| 3 | SPC 判异只飘红不开 NCR | `2873fdf` | pytest + E2E |
| 4 | 完工件数不进库存 | `e966db4` | pytest + E2E |
| 5 | 单号可重复（6 张单） | `f40880c` / `ebfed04` | `doc_no_unique_e2e.py` 18/18 |
| 6 | 删角色留孤儿 | 前序 | pytest |
| 7 | 试产转量产只翻状态位 | `a9f6411` | `trial_to_production_e2e.py` 45/45 |
| 8 | 页内动作不受权限约束 | `76a877c` | `perm_button_gate_e2e.js` 19 PASS / 0 FAIL |
| 9 | 成品无物料档案 → 完工入库一直 skipped | 本文档同期 | `material_sync_e2e.py` 17/17 |
| 10 | 权限只记日志不阻断（影子模式） | `a20b2ef` | `permission_enforce_e2e.js` 9×46 全 PASS |
| 11 | **参数化路由完全绕过权限**（见下节） | `a20b2ef` | `test_permission_enforce.py` 151 例 |
| 12 | 三张子表无组织归属 → 数据范围漏 | 本批 | `subtable_org_e2e.py` 17/17 + `data_scope_e2e.js` 13/13 |
| 13 | 种子用户全在根节点 → 数据范围无法验证 | 本批 | `verify_permissions.py` 新增严格小于断言 |

### 第 9 项的结论（推翻原 §六 之外的假设）

`products`（PRO-xxx）与 `materials`（M-xxx）两套编码未打通，导致「完工自动生成生产入库单」在种子数据上恒定 skipped。

**不能**按 products 直接建入库明细行：`receipt_order_items.material_id` NOT NULL，而库存查询 / 批次 / 盘点 / 预警 / 流水共 15 处全是 `LEFT JOIN materials`，硬建只会得到台账孤儿行。

**采用**：`materials.code` 沿用 `products.code`、`material_type='finished'`，在「试产转量产」和「完工前」两处幂等自动补建（`app/services/material_sync.py`）。

### 仍未闭的项

见 `docs/BACKLOG.md`（唯一台账）。当前待拍板 4 条：B-1 角色增删改界面、
B-4 `SCOPE_FALLBACK=ALL`、B-5 `issue_orders.department_id` 语义混淆、
B-6 `warehouse_repo.py` 疑似死代码。

### 已闭：子表组织归属（本批）

强模式切开后，"权限"是真的了，"数据范围"还差三张子表。

`ORG_SCOPED_TABLES` 只登记了 5 张主表，`work_reports` / `inspection_result` /
`inventory_transactions` **完全不过滤**。缺陷表现不是"看不到"而是**全看到** ——
页面有数据、排序正常、就是多了，不拿两个账号对比根本发现不了。

**归属规则**（写入侧）：

| 子表 | 归属给谁 | 为什么 |
|---|---|---|
| `work_reports` | **报工人**的组织 | 车间主任要看"本车间工人报的工"，不是"本车间被下的工单的报工"。工单通常由生产部/计划下达，按工单归属会让车间主任一条都看不到 |
| `inspection_result` | **继承检验单**（INSERT 子查询） | 子表若用录入人组织，"品质部录入 + 生产部检验单"会让生产部负责人看得到单头看不到明细 |
| `inventory_transactions` | **操作人**组织 | 仓库作业由仓储部执行，流水跟着作业人走 |

**顺带修掉的系统性问题**：服务层 `XxxRepository(self.repo._session)` 手工派生 repo
时只补 `tenant_id`，`_org_scope` 与 `_write_org_id` 全丢 → 写出的行 `org_id` 为 NULL，
随后被过滤掉（自己写的自己看不见），且不报错。新增
`MultiTenantRepository.inherit_context_from()` 统一继承，10 处派生全部改用它，
并加静态检查（`test_services_use_inherit_context`）防回归。

**可验证性问题**：10 个 `test_*` 用户 `primary_org_id` 全是公司根，
`DEPT_CHILD` 解析出整棵树 → 无论过滤写得对不对，所有人看到的都一样，
数据范围**在种子数据上根本没法验证**。新增 `demo_ws1_leader`（一号车间主任）
作为观察点，并把"可见量严格小于 admin"写成断言。

**验证**：pytest 774 → **797**｜`subtable_org_e2e.py` **17/17**｜
`data_scope_e2e.js` **13/13**（真实浏览器：admin 21 行 vs 一号车间主任 3 行，
且 DOM 行数与 API total 逐一对齐）｜`verify_permissions.py` 全通过｜
结构漂移 0

### 已闭：强制模式 + 参数化路由越权（`a20b2ef`）

切强制模式前的只读审计（`scripts/audit_permission_coverage.py`）顺带挖出一个比"模式松"严重得多的问题：

**`_PERMISSION_MAP` 是 `(path, method) -> code` 的精确字典**，而带路径参数的路由注册进来的是模板串
`/work-orders/{order_id}/release`，真实请求 `/work-orders/34/release` 查不到 → 返回 `None` →
guard 当成"未登记的路由"记一条 debug 日志后 `return` 放行。

对比很刺眼：

| 请求 | 结果 |
|---|---|
| `POST /api/v1/work-orders` | 403（正确拦住） |
| `POST /api/v1/work-orders/34/release` | **200（裸奔）** |
| `POST /api/v1/inspection-orders/12/judge` | **200（裸奔）** |
| `POST /api/v1/wms/receipt-order-items/88/store` | **200（裸奔）** |

394 条路由里带 `{param}` 的几乎全是真正"动手"的动作（下达/报工/完工/判定/收料/上架/转产），
即此前**约 91% 的写操作从未被检查过**。这不是"权限不够严"，是"以为有边界其实没有"。

**修复**：`permissions.py` 新增 `_RouteMatcher`——无参路径进精确表 `O(1)`；带参路径编译为
`^/work-orders/[^/]+/release$` 并按「静态段数降序、模板长度降序」排序（防止 `/a/{x}` 抢占 `/a/b/{y}`）；
命中入缓存（上限 4096）；`build_permission_map()` 末尾 `invalidate()`。

**佐证**：`perm_button_gate_e2e.js` 的 P15/P16 从 `WARN status=200` 变成 `PASS status=403`。

**强制模式落地三步**（`PERMISSION_ENFORCE` 默认 `true`，一个 env 变量即可回退，不需回滚代码）：

1. 只读审计——路由码 vs 字典 / 无人可用码 / 前端 perm vs 后端码 / 角色×模块矩阵
2. 灰度 `PERMISSION_ENFORCE_MODULES=M01,M03`——实测 M01 建工单 403 / M04 建物料 200
3. 全量——清空模块范围，启动横幅 `[INFO] 权限模式：强制（全量，394 条路由）`

**顺带补掉的授权缺口**（都是"文档写了但脚本没发"）：`M00:*` / `M04:*` 写权、`M30:*`（NCR）、
`M10:fmea*:*`（资源前缀此前被 `resolve_pattern` 静默丢弃，工艺工程师 FMEA 写权从未生效）、
平台基线抽成 `PLATFORM_BASELINE` 统一叠加。

**前端**：`menu-permissions.ts` 的 system 子菜单此前未声明、继承父级 `PLAT:user:read`，
导致"能看用户列表"的人也看得见「系统配置」、点进去 403 空白页；`quality/ncr` 路由误用
`M03:inspection_order:read`（真实接口要 `M30:ncr:read`）。

### 先前已闭：结果反馈闭环（`b98c283`）

改造前 `POST /work-orders` 不回 `data.id`、完工返回的 `production_receipt` 在 `src/`
里一次都没出现 —— 用户"点了、提示成功、什么都不知道"。现在：

- 建单回 `data.id`，前端建完直接 `router.replace` 到详情
- 完工弹「完工完成」：入库单号 / 仓库 / 数量 / "待收货"状态 / 成品档案是否自动建立，
  未建成时点名原因；有 `M04` 读权时给「查看入库单」直达按钮
- 新增 `src/utils/error.ts`：`errMessage()` 统一取后端 `detail.message`
  （此前 4 处用 `e.message`，拿到的是 axios 的 "Request failed with status code 400"）
- 验证：`work_order_result_e2e.js` 17/17 PASS，全程 0 JS 错误
