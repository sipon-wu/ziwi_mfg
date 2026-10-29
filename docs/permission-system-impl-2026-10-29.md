# 权限体系（S1+S2+S3）实施报告 · 2026-10-29

> 对应设计：`docs/permission-system-design-2026-10-29.md`
> 范围：功能权限 + 数据范围（按拍板：两者一起做，admin 走 `*`，department_head 默认本部门）
> 状态：**已落地并通过四层回归**；当前运行在**影子模式**（`PERMISSION_ENFORCE=false`）

---

## 一、做了什么

### S3｜组织主数据（原来这张表根本不存在）

| 文件 | 内容 |
|:--|:--|
| `backend/app/models/organization.py`（新） | `Organization` 模型：`parent_id` / `code` / `org_type` / **物化路径 `path`** / `level` / `leader_user_id` / `status`；`(tenant_id, code)` 唯一 + `(tenant_id, path)` 索引 |
| `backend/app/repositories/organization_repo.py`（扩充） | 追加 12 个树操作方法（`list_org_subtree` 用 `path LIKE` 取子树，避免递归 CTE） |
| `backend/app/services/organization_service.py`（扩充） | 建树 / 更新 / **移动（重算整棵子树 path+level）** / 删除保护 / 成员 / 数据范围解析 |
| `backend/app/api/organization.py`（扩充） | 9 个新端点：`GET /organizations/tree`、`GET/POST/PUT/DELETE /organizations`、`PUT /organizations/{id}/move`、`GET/POST /organizations/{id}/members`、`DELETE .../members/{user_id}` |
| `backend/migrations/20261029_organizations.py`（新） | 建表 + 给 4 张业务表加 `org_id` + 建索引；幂等、方言无关 |

**为什么用物化路径**：`DEPT_CHILD` 查询只需 `path LIKE '1/5/%'`，一条索引搞定；不用递归 CTE，SQLite 也能跑。

**校验已实现**（对应场景 A-S2 / A-E1）：
- 类型白名单：`company → workshop|dept`、`workshop → dept|team`、`dept → team`、`team → 无`
- 编码租户内唯一
- **成环检测**：目标父的 `path` 不能以自己 `path` 开头
- **删除保护**：有子节点 → 409；有成员 → 409（不做级联删，避免数据范围静默失真）

### S1｜后端端点级权限校验（原来 372 端点零校验）

| 文件 | 内容 |
|:--|:--|
| `backend/app/constants/modules.py`（新） | 模块码（M00–M20 + PLAT）、`ROUTER_MODULE_MAP`、动作字典、`SCOPE_BREADTH`、`ORG_CHILD_TYPES`、`ORG_SCOPED_TABLES` |
| `backend/app/core/permissions.py`（新） | 权限推导 + 映射构建 + 四级通配判定 + `permission_guard` 全局依赖 + fail-closed 自检 |
| `backend/app/main.py` | `FastAPI(dependencies=[Depends(permission_guard)])` + 启动时构建映射与自检 |
| `backend/app/core/config.py` | `PERMISSION_ENFORCE`（默认 False=影子）、`PERMISSION_STRICT_STARTUP` |
| `backend/app/repositories/base.py` | `set_org_scope()` + `_inject_tenant_where_select` 追加 org 过滤 |
| `backend/app/core/dependencies.py` | `resolve_data_scope_org_ids()` + `get_tenant_repo` 注入范围 |
| `backend/scripts/seed_permissions.py`（新） | 权限字典（331 条）+ 9 角色授权 + 孤儿清理，全幂等 |
| `backend/scripts/seed_organizations.py`（新） | 演示组织树 + 角色 scope + **存量数据 org_id 回填** |
| `backend/scripts/check_perm_consistency.py`（新） | 前后端权限码静态比对 |
| `backend/scripts/verify_permissions.py`（新） | 真实 DB + 真实 JWT 的 21 项端到端验证 |

**关键设计决策：权限码自动推导，不手写 372 条**

```
{MODULE}:{RESOURCE}:{ACTION}
  MODULE    ← 路由函数所在文件（app.api.production → M01），比路径前缀稳定
  RESOURCE  ← 路径静态段单数化拼接（/spc/control-limits → spc_control_limit）
  ACTION    ← HTTP 方法 + 动作后缀细化
```

实测效果：
- `POST /work-orders/{id}/release` → `M01:work_order:execute`（不是 create）
- `PUT /inspection-orders/{id}/judge` → `M03:inspection_order:approve`（不是 update）
- 385 条路由 → 331 个唯一权限码，自检清单为空

**四级通配**：`*`（admin）/ `M01:*` / `M01:work_order:*` / `*:read`。让角色授权可写 `M01:*` 而不必罗列十几条。

**fail-closed 自检**：启动时遍历全部路由，任何 `/api` 路由推导异常即 `[WARN]`（`PERMISSION_STRICT_STARTUP=true` 时直接启动失败）。「漏登记」永远暴露在启动期。

### 数据范围（SELF / DEPT / DEPT_CHILD / ALL）

注入点在 `_inject_tenant_where_select`——复用已有的主表/别名解析，只在白名单表上追加：

```python
ORG_SCOPED_TABLES = {
    "work_orders":      "org_id",
    "inspection_order": "org_id",
    "ncr_records":      "org_id",
    "receipt_orders":   "org_id",
    "issue_orders":     "department_id",   # 复用已有列，不加冗余字段
}
```

- `None` → 不限（ALL）
- `[1,2,3]` → `org_id IN (1,2,3)`，组织 id 强制 `int()` 后内联
- `[]` → `AND 1 = 0`（恒假，安全返回空集，不是放行）

多角色 scope 取**最宽**（`SCOPE_BREADTH`），历史 `scope=NULL` 兜底 `ALL`（不让老角色突然看不到数据）。
用户无组织归属时退回 `None`——避免新用户"什么都看不到"。

**必做的前置动作**：存量数据 `org_id` 全为 NULL，不回填的话 DEPT 过滤会让老数据"凭空消失"。`seed_organizations.py` 已回填：work_orders 16 / inspection_order 15 / ncr_records 4 / receipt_orders 2 / issue_orders 2。

### S2｜前端权限驱动

| 文件 | 改动 |
|:--|:--|
| `frontend/src/stores/auth.ts` | 持久化 `permissions`；新增 `hasPerm()` / `hasRole()` / `hasPermissionsLoaded`；导出 `matchPermission()`（与后端同规则） |
| `frontend/src/config/menu-permissions.ts` | `roles: string[]` → `perm: string`（10 个菜单 + 8 个子菜单） |
| `frontend/src/router/index.ts` | `meta.roles` → `meta.perm`（41 处替换 + 17 处补齐）；守卫改为权限判定，拦截后跳 `/403` 并带 `from`/`perm` 参数 |
| `frontend/src/layouts/MainLayout.vue` | 菜单过滤改权限驱动；`perms` 未加载时保守放行（真正拦截在后端） |
| `frontend/src/pages/Forbidden.vue`（新） | 403 页，可展开显示「请求路径 + 所需权限码」，便于运维定位该补哪条权限 |
| `frontend/src/api/client.ts` | 403 且 `detail.code=403-0001` → toast 提示缺少的权限码，不跳转（避免打断正在进行的操作） |

**静默失效的防护**：前端把权限码写死，如果写错（如 `M00:factory_calendar:read` 而真实码是 `M00:calendar:read`），菜单会对所有非 admin 用户消失且**不报错**。`check_perm_consistency.py` + 对应的 pytest 用例专门抓这个——首次运行就抓到 4 处。

---

## 二、过程中修掉的真实缺陷

| # | 缺陷 | 后果 | 修法 |
|:--|:--|:--|:--|
| 1 | `OrganizationService.update_employee` 调用不存在的 `repo.update_employee` | 潜伏 AttributeError（暂无 API 触发） | 补 3 行 repo 方法 |
| 2 | 单数化把 `wms` 压成 `wm`（长度≤3 的模块缩写被误伤） | 权限码 `wm_warehous:read` | 长度≤3 不处理 |
| 3 | 单数化把 `warehouses` 压成 `warehous`（`ses→s` 规则误伤） | 权限码拼错 | 只去尾 `s`，不走 `ses` 规则 |
| 4 | 单数化把 `analysis→analysi`、`status→statu`、`batches→batche` | 权限码难看且易错 | 以 `sis/us/is/ss` 结尾不动；补 `ches/shes/xes/zes` 规则 |
| 5 | 前端 4 个权限码后端不存在（`M01:schedule:read` / `M00:process_route:read` / `M00:factory_calendar:read` / `M04:wms_stock_move:read`） | 这 4 个菜单对所有非 admin 用户**静默消失** | 改为真实码：`M01:work_order:read` / `M00:route:read` / `M00:calendar:read` / `M04:wms_inventory:read` |
| 6 | 原计划给 inspector `M01:work_order:read` | 检验员看到「生产管理」菜单（越权可见） | 收回；已 grep 确认品质页面不调工单接口 |
| 7 | `_SCOPE_CACHE` 曾想用 `id(db)` 作缓存键 | 连接池复用会导致**串用户数据** | 直接去掉缓存，每次请求重算（正确性优先） |
| 8 | `multi_module_scan.js` 断言拦截目标是 `/dashboard` | S2 后拦截目标变 `/403`，误报 3 项 FAIL | 断言改为 `/403 \|\| /dashboard \|\| /login` |

---

## 三、验证结果（四层全绿）

| 层 | 结果 |
|:--|:--|
| **单元测试** | `pytest` **400 passed**（原 350 + 新增 50 权限用例） |
| **权限端到端**（真实 DB + 真实 JWT） | `verify_permissions.py` **21 项全通过**：影子模式不阻断 / 9 角色 403 判定 / 只读矩阵 / 数据范围 / 组织 CRUD |
| **权限浏览器 E2E**（Playwright） | `perm_e2e.js` **8/8 PASS**：admin 菜单齐全、inspector 无「生产/设备」有「品质」、maintenance_tech 反之、直访被拦并带权限码 |
| **全模块扫描** | `full_module_scan.js` **71 PASS / 1 WARN / 0 FAIL**（72 项）。唯一 WARN 是 `lab/1` 报告不存在的 404，属既有业务分支 |
| **核心流程 E2E** | `local_alpha_e2e.js` **18/18 PASS**（登录/工单/检验判定→NCR 闭环/WMS） |

数据范围实测（`team_leader`）：

```
原始（挂公司根节点）:  GET /work-orders → 16 条
移到「二号车间」（空）:  GET /work-orders →  0 条
恢复:                  GET /work-orders → 16 条
```

---

## 四、当前状态与下一步

### 当前跑在影子模式

`PERMISSION_ENFORCE=false`：无权限的调用**不阻断**，只打 `[SHADOW] 本该 403` 日志。
这是设计好的安全阀——角色授权矩阵是"按现有前端硬编码翻译"的草案，需要在真实使用中确认没有误伤。

### 切强制模式前要做的事

1. 用各角色真实跑一轮业务，收集 `[SHADOW] 本该 403` 日志
2. 日志为空（或确认都是合理的越权尝试）后，设 `PERMISSION_ENFORCE=true` 重启
3. 再跑一遍 `full_module_scan.js` + `local_alpha_e2e.js`，确认无回归

### 明确未做的部分（需拍板）

| 项 | 说明 |
|:--|:--|
| **按钮级权限** | 目前只做了菜单/路由级。判定、下达、红冲、处置等关键按钮还没加 `v-if="hasPerm(...)"` —— 表现为"能看到按钮，点了报 403" |
| **角色管理界面** | `permissions` 表已有 331 条数据，但前端没有勾选界面；目前改权限只能走 seed 脚本或直接改库 |
| **WMS / 基础数据 / 安灯 的收紧** | 这三个模块原本路由完全放开，本种子按"行为不变"保留了读权限全开。要收紧需产品决定给哪些角色 |
| `roles.scope` 的界面 | scope 字段已在库里（4 个取值），但没有配置界面 |
| 性能 | 每次请求多 2~3 次查询（角色权限 + scope 解析）。当前数据量下无感，上量后需加缓存（注意不能用 `id(db)` 作键） |

### 三个仍未解决的结构问题（原 TOP-5 P0 联动）

本次做的是权限与组织，**业务联动断点一个都没动**：
- P0-1 检验结果不写回 `receipt_order_items.inspection_status`（`inspection_order` 无入库单外键）
- P0-2 工单完工不生成成品入库单（`receipt_orders` 无 `work_order_id`）
- P0-3 SPC 判异不建 NCR
- P0-4 试产「一键转量产」只翻状态位、不生成正式 BOM/工艺
- P0-5 报工不良不触发返工/再检
- 工单 `change_status` 仍无状态机（任意状态可改任意状态）
