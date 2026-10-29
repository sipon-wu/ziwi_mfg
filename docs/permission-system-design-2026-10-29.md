# 权限体系（S1+S2+S3）设计方案 v1

> 目标：让"按租户内部职能部门配置功能 + 分配权限"真正可执行。
> 范围：S3 组织主数据 → S1 后端端点级权限校验 → S2 前端权限驱动。
> 基线：`backend/app/` 372 端点 / 27 api 模块；`permissions` 与 `role_permissions` **均为 0 行**。
> 状态：**方案待确认，尚未改代码**

---

## 一、现状取证（已核实）

| 事实 | 证据 |
|:--|:--|
| 后端零接口级权限校验 | `grep -rn "require_permission\|has_permission\|check_permission" app/` → 0 命中；`main.py` 仅 CORS + request-id 中间件 |
| `permissions` 表 0 行、`role_permissions` 表 0 行 | 实库直查；`roles` 有 9 行、`user_roles` 有 10 行 |
| `roles.scope` 全为 `NULL` | 实库直查（默认值 `ROLE_SCOPE_ALL` 未落库） |
| `organizations` 表不存在 | `grep "class Organization" app/models/` → 0；`user_organizations.org_id` 注释写"见任务 B3" |
| 前端权限 = 硬编码角色名 | `router/index.ts:5-22` 12 个 `R_*`；`config/menu-permissions.ts` 全文 `roles: string[]` |
| 已有可复用件 | `/auth/me` 已返回 `roles` + `permissions`（`auth.py:70-90`）；`RoleRepository.get_user_permissions()` 已实现；`seed_permissions_if_not_exist()` 已实现 |

**结论：不需要从零搭，缺的是"权限字典内容 + 校验执行点 + 前端消费 + 组织表"四块。**

---

## 二、权限码规范

### 2.1 格式

```
{MODULE}:{RESOURCE}:{ACTION}
```

- **MODULE**：`M00`–`M20`、`PLAT`（平台级）
- **RESOURCE**：资源名，小写下划线，如 `work_order` / `inspection` / `ncr`
- **ACTION**：`read` / `create` / `update` / `delete` / `approve` / `execute` / `export`

现有 `Permission` 模型（`models/role.py:44`）字段 `code/module/resource_type/action` 正好一一对应，**无需改表结构**。

示例：`M01:work_order:create`、`M03:inspection:judge`、`M30:ncr:dispose`、`M20:spc_limit:update`

### 2.2 模块码必须先统一（当前混乱）

现有 router tags 混着中英文和错误编号：

| 现状 tag | 问题 | 应统一为 |
|:--|:--|:--|
| `M02-TPM` | TPM 不是 M02（BOM 才是） | `M06` |
| `M03-Quality` | 中英混 | `M03` |
| `仓储管理-WMS` | 中文 | `M07` |
| `基础数据-BasicData` | 中文 | `M00` |
| `M30-不合格评审NCR` | M30 不在 21 模块序列 | `M30`（保留，作为品质子域） |
| `系统配置` / `Integration-Gateway` | 无编号 | `PLAT` |

**改造点**：新建 `app/constants/modules.py` 定义唯一模块码枚举，各 `api/*.py` 的 `tags` 改用该枚举。纯字符串替换，零行为风险。

---

## 三、端点权限声明方式（关键决策）

### 3.1 三个候选

| 方案 | 做法 | 优点 | 缺点 |
|:--|:--|:--|:--|
| **A 逐个装饰器** | 372 个端点函数各加 `@require_perm("M01:work_order:read")` | 最精确、就近可见 | 372 处改动，易漏、review 成本高 |
| **B 声明表 + 中间件** | 独立一张 `(method, path) → code` 表，中间件查表 | 不改业务代码；集中审计；可配置 | 表要维护 372 条；路径参数需归一化 |
| **C 路由级依赖 + 覆盖** | `APIRouter(dependencies=[Depends(module_gate("M01"))])` 模块级兜底，敏感端点装饰器细化 | 改动少 | 模块级太粗（"能看工单"≠"能改 BOM"） |

### 3.2 推荐：B + fail-closed 自检

**理由**：既不用改 372 个函数，又不会漏，而且映射表本身就是"可配置"的天然载体（后续可下发给租户自定义）。

```python
# app/core/permission_map.py
# (path_pattern, method) -> permission_code
PERMISSION_MAP = {
    ("/api/v1/work-orders",            "GET"):    "M01:work_order:read",
    ("/api/v1/work-orders",            "POST"):   "M01:work_order:create",
    ("/api/v1/work-orders/{id}/release","POST"):  "M01:work_order:execute",
    ("/api/v1/inspection-orders/{id}/judge","PUT"):"M03:inspection:approve",
    ("/api/v1/ncrs/{id}/dispose",      "PUT"):    "M30:ncr:approve",
    # ... 372 条
}
```

**fail-closed 自检**（防漏的关键）：应用启动时遍历 `app.routes`，任何路由若在映射表中查不到，**启动直接失败**并列出缺失清单。

```python
# app/core/permission_guard.py
def assert_all_routes_declared(app):
    missing = []
    for route in app.routes:
        if not getattr(route, "path", "").startswith("/api/v1"): continue
        key = (normalize(route.path), next(iter(route.methods)))
        if key not in PERMISSION_MAP: missing.append(key)
    if missing: raise RuntimeError(f"未声明权限的路由 {len(missing)} 条: {missing[:20]}")
```

这样"漏声明"永远暴露在启动期，而不是上线后被人绕过。

### 3.3 白名单

登录、健康检查、`/auth/me`、OpenAPI 文档必须豁免：

```python
PERMISSION_EXEMPT = {"/api/v1/auth/login", "/api/v1/auth/me", "/health", "/docs", "/openapi.json"}
```

---

## 四、执行点：`require_permission` 中间件

```python
# app/core/permission_guard.py
async def permission_guard(request, call_next):
    if request.url.path in PERMISSION_EXEMPT: return await call_next(request)
    perm = lookup(PERMISSION_MAP, request.method, request.url.path)
    user = request.state.user          # 由 get_current_user 注入
    if perm is None: raise HTTPException(500, "权限映射缺失")   # fail-closed
    if perm not in user["permissions"]:
        raise HTTPException(403, {"code":"403-0001","message":f"缺少权限 {perm}"})
    return await call_next(request)
```

**注意**：中间件拿不到 `Depends` 的结果，需把 `get_current_user` 的结果写入 `request.state`，或改用**全局依赖**（`app = FastAPI(dependencies=[Depends(permission_guard)])`）。后者更简单且能拿到依赖注入值 —— **推荐全局依赖，不用中间件**。

---

## 五、S3：组织主数据

### 5.1 模型

```python
# app/models/organization.py
class Organization(Base):
    __tablename__ = "organizations"
    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False)
    parent_id     = Column(BigInteger)                          # NULL = 根
    code          = Column(String(64), nullable=False)          # 部门编码
    name          = Column(String(200), nullable=False)
    org_type      = Column(String(20), nullable=False)          # company/workshop/dept/team
    path          = Column(String(500), nullable=False)         # 物化路径 '1/5/12'
    level         = Column(Integer, default=1)                  # 层级深度
    sort_order    = Column(Integer, default=0)
    leader_user_id= Column(BigInteger)                          # 负责人
    status        = Column(String(20), default="active")        # active/disabled
    created_at / updated_at
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_org_tenant_code"),
        Index("ix_org_tenant_path", "tenant_id", "path"),
    )
```

**为什么用物化路径 `path`**：`DEPT_CHILD` 作用域查询直接 `path LIKE '{my_path}/%'`，一条索引搞定，不用递归 CTE。

### 5.2 关键校验（对齐场景 A-E1 / A-S2）

| 校验 | 规则 |
|:--|:--|
| 编码唯一 | `(tenant_id, code)` 唯一约束 |
| 不可成环 | `parent_id != id`，且新父的 `path` 不能以自己 `path` 开头 |
| 层级合法 | `company` 只能有 `workshop` 子级；`workshop` 只能有 `dept`；`dept` 可有 `team` |
| 删除保护（A-E1） | 有子节点 → 409；有 `user_organizations` 引用 → 409；有在办单据 → 409 |

### 5.3 补齐外键

`user_organizations.org_id` 目前无外键（注释说等 B3）。B3 落地后加真外键：

```python
org_id = Column(BigInteger, ForeignKey("organizations.id", ondelete="RESTRICT"), nullable=False)
```

**注意**：这需要先建表再改引用，且老数据（现有 0 行 `user_organizations`？需确认）不能有孤儿。

### 5.4 API

| 方法 | 路径 | 权限码 |
|:--|:--|:--|
| GET | `/organizations/tree` | `PLAT:org:read` |
| GET | `/organizations` | `PLAT:org:read` |
| POST | `/organizations` | `PLAT:org:create` |
| PUT | `/organizations/{id}` | `PLAT:org:update` |
| DELETE | `/organizations/{id}` | `PLAT:org:delete` |
| PUT | `/organizations/{id}/move` | `PLAT:org:update`（改父级，需重算 path） |
| GET | `/organizations/{id}/members` | `PLAT:org:read` |

---

## 六、S1：权限种子与角色映射（迁移安全的关键）

### 6.1 从声明表生成字典

`scripts/seed_permissions.py`（幂等）：
1. 遍历 `PERMISSION_MAP`，去重得到全部权限码
2. 按 `module/resource_type/action` 拆分，upsert 进 `permissions`
3. 输出统计：`M01 12 条 / M03 9 条 / ...`

### 6.2 9 个系统角色的初始权限——**必须按现有前端硬编码翻译**

这是最容易出错的地方：如果新系统给的权限比现在少，用户会"功能突然消失"。

翻译规则：把 `router/index.ts` 的 `R_*` 常量与 `menu-permissions.ts` 逐条映射到权限码。

| 角色 code | 现状能看的（前端 `R_*`） | 初始权限（需逐条对齐） |
|:--|:--|:--|
| `admin` | 全部 | `*`（或全量显式列出） |
| `department_head` | 生产/排产/BOM/设备/品质/能碳/采集/系统/试产 | 上述各 `:read` + 部分 `:approve` |
| `team_leader` | 生产/设备 | `M01:*:read` + `M01:work_report:create` + `M06:equipment:read` |
| `scheduler` | 生产/排产 | `M01:work_order:read` + `M01:schedule:update` |
| `process_engineer` | 生产/BOM/FMEA/试产 | `M01:*:read` + `M02:bom:*` + `M10:fmea:*` + `M16:trial:*` |
| `key_user` | 生产/品质/能碳/采集/系统 | 各 `:read` + `PLAT:user:read` |
| `maintenance_tech` | 设备 | `M06:*` |
| `inspector` | 品质 | `M03:inspection:*` + `M30:ncr:read` |
| `quality_engineer` | 品质/SPC/PPAP/FMEA | `M03:*` + `M10:*` + `M30:*` |

> ⚠️ 上表是**草案**，必须先由人工逐条比对 `menu-permissions.ts` 与 `R_*` 才能定稿。**不能凭印象填**。

### 6.3 兼容回退（迁移期必做）

前端改造完成前，后端若开始强制校验会造成大面积 403。因此：

- **阶段 1（影子模式）**：`PERMISSION_ENFORCE=false`，只记录"本该 403 但放行"的日志到 `permission_denied_shadow`，不阻断
- **阶段 2**：观察日志确认无人被误伤后，`PERMISSION_ENFORCE=true` 正式拦截

这是本次改造**唯一的安全阀**，不可省。

---

## 七、S2：前端改造

### 7.1 数据结构

`auth.ts` 已从 `/auth/me` 拿到 `permissions`（string[]），只需持久化：

```ts
// stores/auth.ts  增加
permissions: [] as string[],
hasPerm(code: string) { return this.permissions.includes(code) }
```

### 7.2 配置改造

```ts
// config/menu-permissions.ts   改造前 → 后
{ menuId: 'quality', roles: ['admin','inspector',...] }
{ menuId: 'quality', perm: 'M03:inspection:read' }
```

```ts
// router/index.ts   改造前 → 后
{ path: 'work-orders', meta: { roles: R_PROD } }
{ path: 'work-orders', meta: { perm: 'M01:work_order:read' } }
```

### 7.3 守卫

```ts
// router/index.ts beforeEach
const need = to.meta.perm
if (need && !auth.hasPerm(need)) {
  // 兼容回退：老 token 无 permissions 时按旧 roles 判断，并打 warning
  if (auth.permissions.length === 0) return legacyRoleCheck(to)
  return next('/403')
}
```

### 7.4 按钮级

关键写操作按钮（判定、下达、红冲、处置）需 `v-if="auth.hasPerm('...')"`，否则"能看不能点"仍会被用户当成 bug。

---

## 八、任务拆解与依赖

```
T1 模块码统一 (constants/modules.py + 27 个 api 的 tags)
   └→ T3 权限字典种子 (permissions 表填充)
        └→ T4 声明表 + 全局依赖 + fail-closed 自检 (影子模式)
             └→ T6 角色-权限初始化 (role_permissions)   ← 依赖 T3
                  └→ T7 影子模式观察 1 轮全模块回归
                       └→ T8 切 ENFORCE=true
T2 organizations 模型 + 迁移 + CRUD            ← 独立，可与 T1 并行
   └→ T5 user_organizations 加真外键
        └→ T9 scope 数据过滤（Phase 2，本轮不做）
T10 前端 permissions 消费 (auth.ts / menu / router)  ← 依赖 T3
   └→ T11 按钮级 v-if
T12 前端 403 页面 + 权限测试页
```

| 任务 | 依赖 | 风险 |
|:--|:--|:--|
| T1 模块码统一 | — | 低（纯字符串） |
| T2 组织表+CRUD | — | 中（新表+迁移） |
| T3 权限字典种子 | T1 | 低（幂等 upsert） |
| T4 声明表+校验 | T1,T3 | **高**（372 条映射，靠 fail-closed 兜底） |
| T6 角色权限初始化 | T3 | **高**（填错=功能消失，须逐条比对） |
| T7 影子观察 | T4,T6 | — |
| T8 切 ENFORCE | T7 | 中 |
| T10~T12 前端 | T3 | 中 |

---

## 九、开放问题（需拍板）

1. **`department_head` / `key_user` 这类"跨部门"角色的语义**：它们是"能看全公司"还是"只看本部门"？这决定 `roles.scope` 填 `ALL` 还是 `DEPT`，也决定 T9 要不要本轮做。
2. **一个用户多角色时权限取并集还是取交集？** 现 `get_user_permissions` 是并集（`DISTINCT`）。若取并集，`scope` 怎么合并（最宽优先？）需明确定义。
3. **`admin` 是否走通配**：给 `admin` 一条 `*` 通配权限，还是显式列全 372 条？通配省事但审计困难。
4. **组织树是否允许跨层级**：比如"品质部"直接挂在"公司"下而不经过"车间"（品质通常不隶属车间）。若允许，第 5.2 节的层级校验要放宽为"白名单允许"。
5. **本轮做不做 scope（T9）**：不做则 `roles.scope` 仍是死字段，做了工作量大（要给业务表加 `org_id` 或全走 JOIN）。
6. **端点权限映射表的归属**：写死在代码（`permission_map.py`）还是入库可配置（租户可改）？后者符合"可配置平台"定位，但等于允许租户自我提权。

---

## 十、验收标准

| 层 | 验收 |
|:--|:--|
| 单测 | 每个权限码至少 1 条"有权限通过 / 无权限 403"用例；`assert_all_routes_declared` 0 缺失 |
| 组织 | A-E1 删除有子节点/有成员的组织 → 409；A-S2 建树 + 移动节点后 `path` 正确重算 |
| 影子 | 全模块回归跑一遍，影子日志中"本该 403"的调用数 = 0（说明初始权限对齐了现状） |
| 强制 | 用 `inspector` 账号直调 `POST /api/v1/work-orders` → 403；用 `admin` → 200 |
| 前端 | `inspector` 登录看不到"生产排产"菜单；直接输 URL → 跳 `/403` |
| 回归 | pytest 350 全绿；E2E 18 全绿；全模块扫描 0 FAIL |
