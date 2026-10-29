# 角色权限配置界面（系统管理 → 角色权限）实施报告

- 日期：2026-10-30
- 范围：让 S1（端点级功能权限）/ S2（前端权限码驱动）/ S3（组织数据范围）**真正可运维**
- 前置：`docs/permission-system-design-2026-10-29.md` / `docs/permission-system-impl-2026-10-29.md`

---

## 一、为什么先做界面

权限体系落地后有个尴尬状态：`permissions` 表已有 332 条权限点、9 个角色已授权，
但**改授权只能跑 `scripts/seed_permissions.py` 或直接改库**。这带来三个具体问题：

| 问题 | 表现 |
|:--|:--|
| 租户自建角色无法配权限 | 新建角色 = 全无权限，没有任何入口给它授权 |
| 授予过宽/过窄无法调 | 只能改脚本里的 `ROLE_GRANTS` 常量再全量重跑（会覆盖所有人手工调整） |
| 数据范围不可见 | `roles.scope` 四个取值在库里，但没人知道自己的角色是哪一档 |

界面不是"锦上添花"，它是把权限体系从"代码里的常量"变成"可运营的配置项"的**唯一开关**。

---

## 二、后端：补齐三处缺口

### 2.1 权限目录接口（新）

```
GET /api/v1/roles/permissions
```

返回按 **模块 → 资源 → 动作** 三层聚合的全量权限点：

```json
{"total": 332,
 "modules": [
   {"module": "M01", "module_name": "生产管理",
    "resources": [
      {"resource": "work_order", "resource_name": "工单",
       "permissions": [
         {"id": 12, "code": "M01:work_order:read",   "action": "read",   "action_name": "查看"},
         {"id": 13, "code": "M01:work_order:create", "action": "create", "action_name": "新建"},
         {"id": 14, "code": "M01:work_order:delete", "action": "delete", "action_name": "删除"}
       ]}
    ]}
 ]}
```

排序规则：业务模块 `M00..M30` 按编码在前、`PLAT` 平台底座垫底；
模块内资源按编码升序；动作按 **查看 → 新建 → 修改 → 审批 → 执行 → 导出 → 删除** 排列
（符合"从只读到可写"的授权直觉，`delete` 恒在最后）。

**关键约束（已写进代码注释与单测）**：该路由**必须注册在 `/{role_id}` 之前**。
FastAPI 按注册顺序匹配，否则 `/roles/permissions` 会被 `/roles/{role_id}` 抢先命中、
`role_id` 解析 `"permissions"` 失败 → 422。

**不新增权限点**：路径 `/roles/permissions` 与 `/roles/{id}/permissions` 推导出的
资源名同为 `role_permission`，权限码都是 `PLAT:role_permission:read`。

### 2.2 按权限码授权（`permission_codes`）

`PUT /api/v1/roles/{role_id}/permissions` 原来只收 `permission_ids: List[int]`。
界面拿到的是 code，让前端维护 code→id 映射必然漂移，所以扩展为二选一：

```python
class AssignPermissionRequest(BaseModel):
    permission_ids:   Optional[List[int]]  = None
    permission_codes: Optional[List[str]]  = None   # 同时传时本字段优先
```

语义细节（都有单测）：

- 去重保序 —— 同一权限重复勾选不重复插入
- `unknown_codes` 回报 —— 库里不存在的码（拼错 / 端点已删）不静默吞掉，回给调用方提示
- **显式空数组 = 清空**，与"未传"严格区分；两者都没传直接 400（防一次误调用把角色清空）
- 写入前先校验 role 属于当前租户 —— `role_permissions` **没有 tenant_id 列**，
  隔离只能靠这一步把关

### 2.3 角色成员管理补齐

- `GET /roles/{id}/users` 改为 `LEFT JOIN organizations` 回填 `org_name` / `org_code`
  （B3 组织树已落地，原来那句"待 B3 落地后回填"的注释可以退休了）
- 新增 `DELETE /roles/{id}/users/{user_id}`：移出成员（只解绑 `user_roles`，不删用户）
- `GET /roles` 增加 `permission_count`（`LEFT JOIN role_permissions` + `COUNT(DISTINCT)`）

---

## 三、顺手修掉的 5 个真实缺陷

做界面过程中撞上的，全部是"改之前就存在、只是没人走到"的坑：

| # | 缺陷 | 根因 | 修法 |
|:--|:--|:--|:--|
| 1 | `GET /roles/{id}/permissions` **500** | `query()` 把 `tenant_id` 过滤注入主表，而 `permissions` 是**全局字典表、无 tenant_id 列** | 改裸 `session.execute(text(...))` |
| 2 | `PUT /roles/{id}/permissions` **500** | 同上，`role_permissions` 也无 tenant_id，`execute()` 自动注入 → `no such column: tenant_id` | 新增 `_replace_role_permissions()` 走裸 session，并改用 executemany（332 条不再 332 次往返） |
| 3 | `GET /roles` 加 `permission_count` 后 500 | `query_page` 把 SQL 包成 `SELECT COUNT(*) FROM (<sql>)`，而注入正则是"第一个 `FROM <标识符>`"——命中了**相关子查询里的** `FROM role_permissions` | 改用 `LEFT JOIN + COUNT(DISTINCT)`，不用子查询 |
| 4 | 删除角色后**新建角色带着旧权限** | SQLite 的 `ON DELETE CASCADE` 不生效（Pragma 默认关），留下孤儿 `role_permissions`；rowid 复用 → 新角色"继承"旧授权 | `delete()` 里显式先删 `role_permissions` / `user_roles`（PG 上重复执行无副作用） |
| 5 | 删除角色**静默 0 行** | `WHERE is_system = false`：存量行 `is_system` 多为 `NULL`，`NULL = false` 求值为 NULL → 条件不成立 | 改 `(is_system IS NULL OR is_system = false)`；service 层再加"系统内置角色不可删"的显式 409 |

> 第 3 条是通用陷阱，值得记住：**`query_page` + 相关子查询 = tenant 注入打偏**。
> 以后 `MultiTenantRepository` 的列表查询里不要写 `(SELECT ... FROM other_table ...)`。

---

## 四、必须一起做的：写入归属组织（S1b）

这是本轮**唯一超出"界面"范围但不可省略**的改动，原因是它把数据范围从"半成品"补成"闭环"。

### 问题

数据范围只做**读**过滤（`{org_col} IN (...)`），写时不落 `org_id`：

```
部门负责人（DEPT_CHILD）新建一张工单 → work_orders.org_id = NULL
→ 列表查询 WHERE org_id IN (1,2,3...) 把 NULL 行全部排除
→ 自己建的单，自己看不见
```

实测证据：权限验证脚本报 `dept_head=16 admin=17`，差的正是 E2E 脚本刚建的那张单。

### 修法

在 `MultiTenantRepository` 上加第四个注入点，与已有的三个对称：

| 注入点 | 触发 | 作用 |
|:--|:--|:--|
| `_inject_tenant_where` | UPDATE / DELETE | 租户隔离 |
| `_inject_tenant_where_select` | SELECT | 租户隔离 + 组织读过滤 |
| **`_inject_org_owner`（新）** | **INSERT** | **写归属组织** |

规则写死为"不猜"：

- 表不在 `ORG_SCOPED_TABLES` → 不动
- SQL 已显式带 org 列 → 尊重调用方（`issue_orders` 的 `department_id` 就属此类）
- 非标准 INSERT 形态 → 不动

归属值取 `current_user["org_id"]`（主组织），无需额外查库 —— `UserRepository.get()`
已经把 `org_id` / `org_ids` 附在用户对象上了。

### 连带修掉的丢注入问题

`NcrService.__init__` 原来无条件 `NcrRepository(session)`，把 API 层注入好的 repo **丢掉**：

```python
# 改前
def __init__(self, session, tenant_id=None):
    self.repo = NcrRepository(session)      # ← tenant_id / _org_scope / _write_org_id 全丢

# 改后
def __init__(self, session, tenant_id=None, repo=None):
    self.repo = repo or NcrRepository(session)
```

同步改了 `api/ncr.py::_svc` 与 `api/quality.py` 的判定开单路径
（后者还要显式把检验单 repo 的 `_write_org_id` 传给新建的 ncr_repo）。

> 教训：**任何 `XxxRepository(session)` 的二次构造都会丢注入**。
> 新增 Service 时优先接 `repo` 参数，别自己 new。

### 修复效果（实测）

| 表 | 修复前 | 修复后 |
|:--|:--|:--|
| `work_orders` | 新建 1 张 → `org_id=NULL` | 新建 `WO-E2E-998250` → `org_id=1` |
| `inspection_order` | 同上 | 新建 `QC-20261030-0002` → `org_id=1` |
| `ncr_records` | 3 条 NULL（含 REJ 自动开单） | 新建 → `org_id=1`，存量 3 条已回填 |

`verify_permissions.py` 的数据范围断言从 `dept_head=16 admin=17`（FAIL）变为 `17 / 17`（PASS）。

---

## 五、前端：角色权限配置页

路由 `/#/system/roles`，权限码 `PLAT:role_permission:read`（复用已有码，不新增）。
菜单位置：系统管理 → 角色权限（排在 系统配置 / 许可证 之间）。

### 页面结构

```
┌─────────────┬──────────────────────────────────────────────┐
│ 角色 (10)   │ E2E 临时角色  __e2e_role     已勾选 0/332 项  │
│             ├──────────────────────────────────────────────┤
│ ● 系统管理员│ 数据范围                                     │
│   全租户 332│ [仅本人][本部门][本部门及下级][全租户]        │
│             ├──────────────────────────────────────────────┤
│ ○ 部门负责人│ 功能权限   [搜索框] [全选当前] [清空当前]     │
│   本部门及下级│ ▾ ◻ 基础数据 M00                    0/25    │
│             │    ◻ 工厂日历 calendar      [查看]            │
│ ○ 班组长    │    ◻ 工序 operation  [查看][新建][修改][删除] │
│   ...       │ ▸ ◻ 生产管理 M01                    0/9     │
│             ├──────────────────────────────────────────────┤
│             │ 角色成员  张三 · 一号车间          [移出]     │
│             ├──────────────────────────────────────────────┤
│             │ 有未保存的改动          [重置] [保存]        │
└─────────────┴──────────────────────────────────────────────┘
```

### 三个设计决定

1. **前端状态用「权限码集合」而不是「id 集合」**
   目录返回的就是 code，保存也回传 code。少一层 code→id 副本，就少一处会漂移的地方。

2. **三态勾选不落库**
   模块/资源的勾选框只是"批量勾上/批量清掉"下级的快捷键，状态由
   `已选数 / 总数` 推导（全选 ✓ / 部分 – / 未选 空）。不做"父级权限"概念，
   避免"模块权限"和"资源权限"两种语义打架。

3. **脏状态保护**
   切换角色时若有未保存改动，弹确认框而不是静默丢弃；
   底部常驻「有未保存的改动 / 改动已保存」+ 重置（回到上次保存快照）。

### 按钮级权限门（本轮先做这一页）

`hasPerm` 已能判定，本页按码藏按钮：

| 操作 | 需要的权限码 | 缺权限时表现 |
|:--|:--|:--|
| 勾选/保存权限 | `PLAT:role_permission:update` | 复选框 disabled，保存按钮灰，底部提示原因 |
| 改数据范围 | `PLAT:role_scope:update` | 四个选项卡 disabled |
| 移出成员 | `PLAT:role_user:delete` | 不显示「移出」按钮 |

演示账号对应关系：`department_head` 只拿到 `PLAT:role_permission:read`（能看不能改），
`key_user` 拿到 `role_permission:*` / `role_scope:*` / `role_user:*`（能配），`admin` 是 `*`。

---

## 六、验证

### 单元测试

| 文件 | 数量 | 内容 |
|:--|:--|:--|
| `app/tests/test_role_permission_admin.py`（新） | 23 | 目录聚合/排序、中文标签回退、按码授权去重与未知码、空数组清空、缺参报错、越权拒绝、系统角色不可删、路由注册顺序、权限码归属 |
| `app/tests/test_permission_system.py`（+8） | 66 | 新增 `_inject_org_owner` 六种形态 + `execute()` 注入开关两例 |

全量：**431 passed**（上轮 400 + 23 + 8）。

### 脚本验证

- `verify_permissions.py`：**22 项全通过**（含 `dept_head=17 admin=17`）
- `check_perm_consistency.py`：前端引用 31 个权限码，全部在后端存在

### 真实浏览器 E2E

| 脚本 | 结果 | 说明 |
|:--|:--|:--|
| `role_perm_ui_e2e.js`（新，13 项） | **13/13 PASS** | 见下 |
| `perm_e2e.js` | 8/8 PASS | 权限菜单/路由拦截回归 |
| `local_alpha_e2e.js` | 18/18 PASS | 工单→检验→判定→NCR 主流程 |
| `full_module_scan.js` | 71 PASS / 1 WARN / 0 FAIL | WARN 为既有 `lab/1` 报告 404 |

`role_perm_ui_e2e.js` 覆盖：

```
U0  准备临时角色            只动自己创建的 __e2e_role，不碰真实角色
U1  页面渲染                角色卡片 10、非 403
U2  三层树 + 中文标签       模块 14、工单资源 1、查看/新建标签正确
U3  勾选 → 未保存提示
U4  保存 → 后端真实落库     GET /roles/{id} 返回 ["M01:work_order:read"]
U5  刷新后状态持久          已勾选 1，非前端缓存
U6  数据范围保存            scope=DEPT_CHILD
U7  搜索过滤                模块 14 → 2
U8  重置                    回到上次保存快照
U9  无权限账号被拦          inspector → /403?perm=PLAT:role_permission:read
CL  清理临时角色            删除后关联授权一并清空
```

---

## 七、明确未做的部分（需拍板）

1. **角色增删改界面**：本轮只做「给已有角色配权限」。新建/改名/删除角色仍只有 API，
   没有界面。`POST/PUT/DELETE /roles` 都齐了，补个表单页即可。
2. **其他页面的按钮级权限门**：本轮只做了角色权限页自身。
   工单「下达/关闭」、检验「判定」、库存「红冲」、NCR「处置」等按钮仍是
   "能看到按钮，点了才 403"。需要扫一遍写操作按钮批量加 `v-if="auth.hasPerm(...)"`。
3. **切强制模式**：仍是影子模式 `PERMISSION_ENFORCE=false`。
   三步走：各角色真实跑业务收集 `[SHADOW] 本该 403` → 日志清空后置 true 重启 → 再跑全扫描。
4. **性能**：每请求多 2~3 次查询（角色权限 + scope 解析 + 用户组织），上量后需加缓存。
   **不能**用 `id(db)` 作键（AsyncSession 会被连接池复用）。
5. **`OrganizationRepository` 之外的组织归属**：目前只覆盖 5 张白名单表
   （`work_orders` / `inspection_order` / `ncr_records` / `receipt_orders` / `issue_orders`）。
   工单报工、检验结果、库存流水等子表未加 `org_id`，跨组织汇总报表会不准。
6. **WMS / 基础数据 / 安灯 的收紧**：这三个模块路由原本完全放开，
   种子里按"行为不变"保留了读权限全开。
7. **`_replace_role_permissions` 的非原子性**：先 DELETE 再 INSERT，中间失败会留下空授权。
   PG 上应包事务；SQLite 下 `session` 隐式事务可覆盖，但没显式验证过。

---

## 八、操作手册（给运维/实施）

```
# 1. 权限字典随代码变更同步（新增/删除端点后必跑）
cd backend && ./.venv/Scripts/python.exe scripts/seed_permissions.py

# 2. 校验前端写的权限码在后端都存在（防菜单静默消失）
./.venv/Scripts/python.exe scripts/check_perm_consistency.py

# 3. 权限矩阵 + 数据范围 + 组织 CRUD 冒烟
./.venv/Scripts/python.exe scripts/verify_permissions.py

# 4. 角色权限界面真实浏览器回归
cd .. && NODE_PATH=$(npm root -g)/@playwright/test/node_modules \
  node e2e/browser_test/role_perm_ui_e2e.js
```

界面操作路径：登录 `mfg_admin/admin123` → 系统管理 → 角色权限 → 左选角色 →
勾权限 / 改数据范围 → 保存。
