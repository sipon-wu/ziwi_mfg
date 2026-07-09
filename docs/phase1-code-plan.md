# Phase 1 P0 功能编码计划

> **文档状态**：定稿  
> **编制人**：Bob（架构师）  
> **编制日期**：2026-06-23  
> **参考文档**：`product-functional-specification.md`、`architecture-impact-scan-v2.md`  
> **项目根目录**：`D:\工业元\数云_新质力\ziwi_project_SaaS\code\`

---

## 技术栈确认

| 层 | 技术 | 说明 |
|:---|:-----|:------|
| 后端框架 | Python 3.13 + FastAPI | 已就位 |
| ORM | SQLAlchemy async + Raw SQL | Repository 层使用原生 SQL（`MultiTenantRepository` 基类） |
| 数据库 | SQLite / PostgreSQL | 当前使用 SQLite（通过 `aiosqlite`） |
| 认证 | JWT + `require_auth=True` | 已就位，所有 API 走 `get_current_user` 依赖 |
| 前端框架 | Vue 3 + TypeScript + Vite + Tailwind CSS | 前端代码另行实施 |
| 架构模式 | API → Service → Repository | 三层已落地，本计划遵循此模式 |

---

## 前置分析：代码现状关键发现

在正式开始计划前，对现有后端代码进行了审查，发现以下重要情况：

### 1️⃣ M08 machine_hours 字段已存在

`WorkReport` 模型和 `CreateWorkReportRequest` Schema 中**已经包含 `machine_hours` 字段**（模型第56行，Schema第79行）。这意味着 M08 人工/机器工时区分的**后端变更实际上已完成**。

**剩余工作**：
- 前端报工表单需要添加"机器工时"输入框
- 报表汇总需要区分人工工时 vs 机器工时（当前 `daily_report` 和 `monthly_report` 的查询中 `SUM(wr.labor_hours)` 未区分）

### 2️⃣ product_bom 模型不存在

**当前代码中没有 `product_bom` 模型/表/Service/Repository**。M02 的 BOM 版本锁定需要**从零创建 BOM 基础设施**，而非仅字段扩展。具体包括：
- 创建 `ProductBom` 模型（含基础字段 + `version`/`effective_from`/`is_active`）
- 创建 `bom_repo.py`（Repository）
- 创建 `bom_service.py`（Service）
- 创建 BOM API 路由

### 3️⃣ M20 仓储模块不存在

当前代码中**没有 warehouse/inventory 相关模块**。M07 齐套性检查需要调用库存查询，因此在 Phase 1 中需要**创建库存查询的简化实现**（或至少定义接口契约），否则齐套性检查无法完成。

### 4️⃣ AndonCall 已含 escalation_level

`andon_call` 模型已经包含 `escalation_level` 字段（第28行），M11 的升级序列只需扩展配置表，无需修改 `andon_call` 表结构。

---

## 1. M00 key_user 关键用户角色

### 1.1 实现方案

在现有角色体系中新增 `key_user` 预置角色编码（`code='key_user'`），数据作用域为 `DEPT_CHILD`。需要做三件事：

1. **数据库初始化**：在 `roles` 表 seed 数据中新增 `key_user` 行（`is_system=false`），以及在 `permissions` 表中新增三个 key_user 专属权限编码
2. **角色创建/编辑 API 增强**：在现有角色管理 API 中，允许 admin 创建/分配 `key_user` 角色（当前 API 已支持创建任意角色，无需修改后端路由）
3. **前端**：角色管理页面新增 `key_user` 选项（前端单独实施）

**核心变更**：
- 无新表，完全复用现有角色+权限+用户关联体系
- 现有 `RoleRepository.create()` 和 `RoleRepository.assign_permissions()` 已支持创建角色和分配权限
- key_user 不可访问系统管理区的限制通过**前端菜单路由守卫** + **后端权限编码校验**双重保障

### 1.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 修改 | `backend/app/models/role.py` | 在 Role 表注释或常量中定义 key_user 角色编码和权限编码常量 |
| 修改 | `backend/app/api/roles.py` | 新增 `POST /api/v1/roles/key-user-permissions` 端点（或扩展现有权限分配逻辑，确保 key_user 的三个权限编码可被分配） |
| 修改 | `backend/app/services/role_service.py` | 新增 `assign_key_user_permissions()` 方法，组合分配 `key_user:module_config`、`key_user:approval_scope`、`key_user:dept_scope` 三个权限 |
| 修改 | `backend/app/repositories/role_repo.py` | 新增 `bulk_assign_permissions()` 方法（批量分配权限，优化性能） |
| 新增 | `backend/app/schemas/role.py` | 新增 `AssignKeyUserPermissionsRequest` Schema（含 `role_id`, `module_codes` 列表等字段） |
| 新增 | `backend/seed/seed_key_user_permissions.py` | 新增权限种子数据脚本 |
| 修改 | 前端: 角色管理页面 | 角色选项新增 key_user，模块权限勾选树扩展 |

### 1.3 依赖包变更

无。复用现有 `FastAPI`、`SQLAlchemy`、`Pydantic`。

### 1.4 实施顺序建议

独立变更，无外部依赖。可在任意时间实施。

### 1.5 预估工作量

| 项目 | 人天 |
|:-----|:----:|
| 权限种子数据脚本 | 0.5 天 |
| 后端权限分配逻辑增强 | 0.5 天 |
| 前端角色管理页面扩展 | 1 天 |
| **合计** | **2 天** |

---

## 2. M02 BOM 版本锁定

### 2.1 实现方案

由于当前代码中**没有 BOM 基础设施**，本变更需要从零创建 `product_bom` 模型及配套的 Service/Repository/API，并在创建时就包含版本锁定能力。

**表结构设计**（`product_bom`）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| id | BIGINT PK | 主键 |
| tenant_id | VARCHAR(50) | 租户ID |
| product_id | BIGINT | 关联产品ID |
| material_code | VARCHAR(100) | 物料编码 |
| material_name | VARCHAR(200) | 物料名称 |
| qty_per_unit | DECIMAL(10,4) | 单件用量 |
| unit | VARCHAR(20) | 单位 |
| material_type | VARCHAR(50) | 类型: raw/semi/finished |
| scrap_rate | DECIMAL(5,2) | 损耗率(%) |
| issue_operation_seq | VARCHAR(50) | 投料工序序号 |
| is_key_material | BOOLEAN | 关键物料标记 |
| **version** | **INTEGER** | **BOM 版本号** |
| **effective_from** | **DATE** | **生效日期** |
| **is_active** | **BOOLEAN** | **是否激活** |
| remark | TEXT | 备注 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

**bom_snapshot 表**（BOM 快照，工单下达时生成）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| id | BIGINT PK | 主键 |
| tenant_id | VARCHAR(50) | 租户ID |
| work_order_id | BIGINT | 工单ID |
| bom_version | INTEGER | 快照时的 BOM 版本 |
| snapshot_data | JSON/TEXT | BOM 快照内容（物料清单 JSON） |
| created_at | DATETIME | 创建时间 |

**Service 方法**：
- `snapshot_bom(work_order_id)`: 工单下达时自动调用，创建 BOM 快照
- `get_active_bom_by_date(product_id, date)`: 根据日期获取指定产品当前生效的 BOM 版本
- 工单下达时自动锁定当前 BOM 版本

### 2.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 新增 | `backend/app/models/production.py` | 在现有 production.py 中新增 `ProductBom` 和 `BomSnapshot` 两个模型类 |
| 修改 | `backend/app/models/__init__.py` | 导出新模型 |
| 新增 | `backend/app/repositories/bom_repo.py` | 新增 `BomRepository`（继承 `MultiTenantRepository`），包含 CRUD + `get_active_by_date()` + `create_snapshot()` |
| 新增 | `backend/app/services/bom_service.py` | 新增 `BomService`，包含 `snapshot_bom()`、`get_active_bom_by_date()`、CRUD 委托方法 |
| 新增 | `backend/app/api/bom.py` | 新增 BOM API 路由组（`/api/v1/boms`、`/api/v1/boms/{product_id}/active`） |
| 新增 | `backend/app/schemas/production.py` | 在现有 production.py 中新增 `ProductBomCreate`、`ProductBomResponse`、`BomSnapshotResponse` Schema |
| 修改 | `backend/app/services/production_service.py` | 在 `change_status()` → `released` 时调用 `bom_service.snapshot_bom()` |
| 修改 | `backend/app/api/production.py` | 扩展工单下达端点，注入 BOM 快照调用 |
| 修改 | `backend/app/main.py` | 注册新路由 `bom_router` |

### 2.3 依赖包变更

无。使用 SQLAlchemy JSON 字段（SQLite 兼容）。

### 2.4 实施顺序建议

建议在第 1 位或第 2 位实施，因为 M07 齐套性检查需要读取 BOM 数据。

### 2.5 预估工作量

| 项目 | 人天 |
|:-----|:----:|
| ProductBom + BomSnapshot 模型创建 | 0.5 天 |
| BomRepository CRUD + 版本查询 + 快照 | 1 天 |
| BomService + API 路由 | 1 天 |
| 工单下达时 BOM 快照集成 | 0.5 天 |
| Schema 定义 | 0.5 天 |
| 前端 BOM 管理页面（含版本锁定 UI） | 2 天 |
| **合计** | **5.5 天** |

---

## 3. M07 齐套性检查

### 3.1 实现方案

在工单下达流程中插入齐套性检查步骤。由于 **M20 仓储模块尚未实现**，需要先创建一个**简化的库存查询 Service/Repository**，用于 Phase 1 的齐套性计算。

**表结构变更**（`work_orders` 新增字段）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| material_check_status | VARCHAR(20) | 齐套状态: pending/passed/failed/force_passed |
| material_check_result | TEXT/JSON | 缺料明细（JSON 字符串） |

**简化库存设计**（Phase 1 临时方案）：

创建 `inventory_items` 表（轻量级库存表），仅包含齐套性检查所需的字段：
- `material_code` / `material_name` / `available_qty` / `locked_qty` / `unit`

该表在 Phase 2 正式 M20 仓储模块上线后可迁移/废弃。

**Service 方法**：
- `check_material_availability(work_order_id)`: 
  1. 展开工单 BOM 物料清单（调用 `bom_service.get_active_bom_by_date()`）
  2. 遍历物料，调用库存查询获取各物料可用量
  3. 计算缺料数量 = 需求数量 × (1 + 损耗率) - 可用库存
  4. 计算齐套率 = 齐套物料数 / 总物料数 × 100%
  5. 返回检查结果（含缺料明细清单）
- 工单下达 API 扩展：下达前先执行齐套检查
  - 齐套（所有物料不缺料）→ 正常下达
  - 缺料 → 返回缺料明细 + 允许强制下发（记录强制下发原因+操作人）

### 3.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 修改 | `backend/app/models/production.py` | WorkOrder 模型新增 `material_check_status` 和 `material_check_result` 字段 |
| 新增 | `backend/app/models/inventory.py` | 新增 `InventoryItem` 模型（简化库存表） |
| 修改 | `backend/app/models/__init__.py` | 导出新模型 |
| 新增 | `backend/app/repositories/inventory_repo.py` | 新增 `InventoryRepository`（含 `get_by_material_code()` 方法） |
| 新增 | `backend/app/services/material_check_service.py` | 新增 `MaterialCheckService`，含 `check_material_availability()` |
| 修改 | `backend/app/services/production_service.py` | 在 `release_work_order()` 中集成齐套检查 |
| 修改 | `backend/app/api/production.py` | 扩展工单下达端点（增加 `force_release` 参数和 `force_reason` 参数） |
| 新增 | `backend/app/schemas/production.py` | 新增 `ReleaseWorkOrderRequest` Schema（含 force_release、force_reason 字段）、`MaterialCheckResult` 响应 Schema |
| 新增 | `backend/seed/seed_inventory.py` | 支持导入初始库存数据（用于测试） |

### 3.3 依赖包变更

无。

### 3.4 实施顺序建议

**依赖 M02（BOM 读取）**，需要在 M02 之后实施。同时依赖新建的简化库存查询。

推荐实施顺序：M02 → M07（含 M20 简化库存）

### 3.5 预估工作量

| 项目 | 人天 |
|:-----|:----:|
| WorkOrder 模型字段扩展 | 0.25 天 |
| InventoryItem 模型 + Repository 创建 | 0.5 天 |
| MaterialCheckService（核心算法） | 1 天 |
| 工单下达 API 扩展 | 0.5 天 |
| Schema 定义 | 0.25 天 |
| 前端缺料提示弹窗/强制下发 UI | 1.5 天 |
| **合计** | **4 天** |

---

## 4. M08 人工/机器工时区分

### 4.1 实现方案

**后端已基本完成**：`WorkReport` 模型已包含 `machine_hours` 字段（第56行），`CreateWorkReportRequest` Schema 也已包含 `machine_hours`（第79行）。

剩余实施内容：
1. **后端报表查询修正**：`daily_report()` 和 `monthly_report()` 查询中当前仅统计 `labor_hours`，需要增加 `machine_hours` 的统计
2. **前端报工表单**：新增"机器工时"输入框
3. **前端报表**：生产报表区分人工工时 vs 机器工时

### 4.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 修改 | `backend/app/repositories/production_repo.py` | `daily_report()` 和 `monthly_report()` 查询增加 `SUM(wr.machine_hours)` |
| 修改 | `backend/app/services/production_service.py` | `daily_report()` 和 `monthly_report()` 返回数据结构增加 `total_machine_hours` |
| 修改 | `backend/app/schemas/production.py` | `DailyReportResponse` 增加 `total_machine_hours` 字段 |
| 修改 | 前端: 报工表单组件 | 新增"机器工时"输入框（类型：数字，单位：小时） |
| 修改 | 前端: 生产报表组件 | 表格和图表区分人工工时 vs 机器工时 |

### 4.3 依赖包变更

无。

### 4.4 实施顺序建议

独立变更，无外部依赖，可在任意时间实施。与 M07 无冲突。

### 4.5 预估工作量

| 项目 | 人天 |
|:-----|:----:|
| 后端报表查询修正 | 0.25 天 |
| 前端报工表单添加机器工时 | 0.5 天 |
| 前端报表区分人工/机器工时 | 0.5 天 |
| **合计** | **1.25 天** |

---

## 5. M11 多级升级序列

### 5.1 实现方案

扩展现有安灯系统，增加三级升级序列的配置和执行能力。核心变更在三处：

**1. 升级规则配置表**（新增 `andon_escalation_rules` 表）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| id | BIGINT PK | 主键 |
| tenant_id | VARCHAR(50) | 租户ID |
| rule_name | VARCHAR(100) | 规则名称 |
| call_type | VARCHAR(50) | 适用安灯类型（如 quality/equipment/material/...） |
| priority | VARCHAR(10) | 适用优先级（low/normal/high/emergency/all） |
| level | INTEGER | 升级级别（1/2/3） |
| timeout_minutes | INTEGER | 超时分钟数（从安灯发起开始计算） |
| notify_role | VARCHAR(100) | 通知角色编码 |
| notify_users | TEXT/JSON | 通知用户ID列表（JSON数组，替代角色） |
| notify_channels | TEXT/JSON | 通知通道列表（JSON数组: board/broadcast/wechat/dingtalk/sms/email） |
| is_active | BOOLEAN | 是否启用 |
| created_at | DATETIME | 创建时间 |
| updated_at | DATETIME | 更新时间 |

**2. 升级历史记录表**（新增 `andon_escalation_logs` 表）：

| 字段 | 类型 | 说明 |
|:-----|:-----|:------|
| id | BIGINT PK | 主键 |
| tenant_id | VARCHAR(50) | 租户ID |
| andon_call_id | BIGINT | 关联安灯呼叫ID |
| escalation_level | INTEGER | 升级级别 |
| triggered_at | DATETIME | 触发时间 |
| timeout_minutes | INTEGER | 触发时的超时配置值 |
| notified_users | TEXT/JSON | 实际通知的用户列表 |
| notify_channels | TEXT/JSON | 实际使用的通知通道 |
| response_status | VARCHAR(20) | 响应状态: pending/responded/ignored |
| created_at | DATETIME | 创建时间 |

**3. 定时任务**：新增后台循环任务（FastAPI 生命周期事件），定期扫描超时未处理的安灯，自动触发升级通知：

```
scan_escalations() → 每60秒执行一次:
  for each pending/acknowledged/in_progress andon_call:
    calculate elapsed = now - created_at
    for each escalation_rule matching call_type + priority:
      if timeout_minutes <= elapsed < next_level.timeout_minutes:
        if not already escalated at this level:
          trigger_escalation(call, rule)
          create escalation_log
          send notifications via configured channels
          update andon_call.escalation_level
```

### 5.2 文件变更清单

| 操作 | 文件路径 | 变更内容 |
|:----|:---------|:---------|
| 新增 | `backend/app/models/andon.py` | 新增 `AndonEscalationRule` 和 `AndonEscalationLog` 模型 |
| 修改 | `backend/app/models/__init__.py` | 导出新模型 |
| 新增 | `backend/app/repositories/andon_repo.py` | 新增 `get_active_rules()`、`create_escalation_log()`、`get_escalation_logs()`方法 |
| 新增 | `backend/app/services/andon_service.py` | 新增 `scan_escalations()` 定时扫描方法、`trigger_escalation()` 方法 |
| 修改 | `backend/app/api/andon.py` | 新增升级规则 CRUD 端点（`/api/v1/andon/escalation-rules`）|
| 新增 | `backend/app/schemas/andon.py` | 新增 `AndonEscalationRuleCreate`、`AndonEscalationRuleResponse`、`AndonEscalationLogResponse` Schema |
| 修改 | `backend/app/main.py` | 在应用生命周期 `startup` 事件中启动定时扫描任务（使用 `asyncio.create_task` 或 `BackgroundTasks`） |
| 修改 | 前端: 安灯配置页面 | 新增"升级规则配置"子页面（三级序列配置表单） |

### 5.3 依赖包变更

| 包名 | 用途 | 说明 |
|:-----|:-----|:------|
| `apscheduler` (可选) | 后台定时任务 | 推荐使用，若用 `asyncio.create_task` + `while` 循环则不需要 |

### 5.4 实施顺序建议

独立变更，无外部依赖。可在任意时间实施。

### 5.5 预估工作量

| 项目 | 人天 |
|:-----|:----:|
| 升级规则+日志模型 | 0.5 天 |
| Repository 扩展 | 0.5 天 |
| Service 扫描+触发逻辑 | 1 天 |
| API 路由（规则 CRUD） | 0.5 天 |
| FastAPI 生命周期集成定时任务 | 0.5 天 |
| Schema 定义 | 0.25 天 |
| 前端升级规则配置页面 | 1 天 |
| **合计** | **4.25 天** |

---

## 6. 总体实施依赖关系图

```
M00 key_user ────── 独立
                      │
M02 BOM 版本锁定 ──── 独立 ───┐
                              │
M07 齐套性检查 ───────────────┤ (依赖 M02 BOM 读取)
                              │
M08 工时区分 ──────── 独立    │
                              │
M11 多级升级序列 ──── 独立    │
```

**推荐实施顺序**：

| 阶段 | 功能 | 说明 |
|:----:|:-----|:------|
| 1 | M00 key_user | 角色定义先到位 |
| 2 | M02 BOM 版本锁定 | BOM 基础先建好 |
| 3 | M07 齐套性检查 | 依赖 M02 BOM |
| 4 | M08 工时区分 | 独立，可并行 |
| 5 | M11 多级升级序列 | 独立，可并行 |

**并行建议**：
- M08（工时区分）+ M11（升级序列）+ M00（key_user）可以**完全并行**实施，因为它们没有代码冲突和依赖关系
- M02 和 M07 建议串行：M02 → M07

---

## 7. 总计工作量

| 功能 | 后端(人天) | 前端(人天) | 合计(人天) |
|:----|:----------:|:----------:|:----------:|
| M00 key_user | 1.0 | 1.0 | 2.0 |
| M02 BOM 版本锁定 | 3.5 | 2.0 | 5.5 |
| M07 齐套性检查 | 2.5 | 1.5 | 4.0 |
| M08 工时区分 | 0.25 | 1.0 | 1.25 |
| M11 多级升级序列 | 3.25 | 1.0 | 4.25 |
| **合计** | **10.5** | **6.5** | **17 人天** |

---

## 8. 风险与注意事项

### 8.1 M02 BOM 从零创建风险

当前代码中无 `product_bom` 模型，本次需要**同时创建 BOM 基础功能和版本锁定功能**，工作量比预期大。建议：
- 优先创建 `ProductBom` 模型和 CRUD API
- 在此基础上叠加版本控制和快照能力
- 不要一次性提交过大代码量

### 8.2 M07 库存查询简化方案风险

由于 M20 仓储模块未实现，Phase 1 的齐套性检查需使用简化库存表。需注意：
- 简化库存表结构需与未来 M20 兼容（建议字段名、类型对齐）
- 在简化表中预留 `warehouse_id`、`batch_no` 等未来字段
- 实现上做好隔离，后续 M20 上线后只需替换 `InventoryRepository` 实现

### 8.3 M11 定时任务基础设施

当前代码中无定时任务基础设施。建议：
- 使用 `asyncio.create_task` 启动后台协程（轻量无额外依赖）
- 或者引入 `apscheduler`（功能完整但增加依赖）
- Phase 1 推荐 `asyncio.create_task` 方案，Phase 2 如有更多定时任务再引入 `apscheduler`

### 8.4 数据库迁移

当前代码中未发现 Alembic 或类似迁移工具。字段变更建议：
- 直接使用 SQLAlchemy Base metadata 自动建表（`Base.metadata.create_all()` 模式）
- 或提供手写 SQL 迁移脚本
- 需确认当前团队使用的数据库变更策略

---

## 附录：模型/表变更汇总

| 表名 | 操作 | 说明 |
|:-----|:----:|:------|
| `roles` | 🟢 无变更 | 仅 seed 数据新增 key_user 行 |
| `permissions` | 🟢 无变更 | 仅 seed 数据新增三个 key_user 权限 |
| `product_bom` | 🆕 新建 | BOM 物料清单表 |
| `bom_snapshots` | 🆕 新建 | BOM 快照表 |
| `work_orders` | ✏️ 字段扩展 | 加 `material_check_status` + `material_check_result` |
| `work_reports` | ✅ 已有 | `machine_hours` 字段已存在 |
| `inventory_items` | 🆕 新建 | 简化库存表（Phase 1 过渡方案） |
| `andon_escalation_rules` | 🆕 新建 | 升级规则配置表 |
| `andon_escalation_logs` | 🆕 新建 | 升级历史记录表 |
