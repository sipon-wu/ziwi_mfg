# 工程师（可实施性）评审报告 — 数据路由与模块整合技术设计

> **评审人**：寇豆码（Software Engineer）
> **评审日期**：2026-06-14
> **评审版本**：data-routing-integrated-design.md v1.0
> **现有代码基线**：`backend/app/` 下现有 18 个 Python 源文件

---

## 总体判定

### 🔴 当前设计**无法直接进入编码阶段**，需先解决以下前置条件：

| 条件 | 说明 | 影响范围 |
|:-----|:------|:---------|
| 1️⃣ 数据库模型缺少 `package_modules` 字段 | Tenant 表无字段存储租户套餐，FeatureFlag 无法生成 | 🔴 阻塞 Layer 1 和全部路由 |
| 2️⃣ JWT Payload 当前不含 `features` | `create_access_token` 只写 `sub`+`tenant_id`，无 `features` 载入 | 🔴 阻塞 Layer 1 |
| 3️⃣ 缺少 `aiosqlite` 和 `pyyaml` 依赖 | SQLite 异步需要 `aiosqlite`；场景规则引擎需要 `pyyaml` | 🔴 阻塞独立部署和场景引擎 |
| 4️⃣ `async def __init__` 语法错误 | Python 不支持异步 `__init__`，`EnergyRepository.__init__` 不可实施 | 🔴 必须改为工厂方法或惰性初始化 |
| 5️⃣ 无现有测试目录 | `tests/` 目录不存在，测试策略需要从头搭建基础设施 | 🟡 重要 |

**综合结论**：解决上述 5 个阻塞项后，Layer 2（DataRouteResolver）和 Layer 3（Repo 改造）可以立即编码。预计需 1~2 天的前置准备工作。

---

## 一、问题清单（按严重等级）

---

### 🔴 阻断级（共 6 项，不解决无法启动任何编码）

#### 🔴 B1. Tenant 模型无 `package_modules` 字段

**文档位置**：第 3.1 节 "读取 tenant.package_modules → 生成 feature_flags dict"
**代码位置**：`backend/app/models/tenant.py`

**问题描述**：
设计文档假定 `tenant` 表存在 `package_modules` 字段存储该租户购买的模块列表，但现有 `Tenant` 模型（`models/tenant.py`）仅有 7 个字段（`id`, `tenant_id`, `name`, `code`, `contact_name`, `contact_phone`, `status`, `industry`, `region`, `expire_at`），完全没有任何有关套餐或模块的字段。

**影响**：
- 登录时无法生成 `feature_flags`
- `POST /api/v1/tenant/refresh-features` 端点无法实现
- 整个 Layer 1 无数据源

**整改建议**：
- 方案 A（推荐）：Tenant 表新增 `package_modules JSONB` 字段，存储如 `{"M01_WORK_ORDER":true, "M02_EQUIPMENT":true, ...}` 的模块配置
- 方案 B：新建 `tenant_package_modules` 关联表（tenant_id, module_code, is_enabled），更规范但增加了查询复杂度
- 无论哪种方案，都需要在 `TenantRepository` 中新增 `get_tenant_features(tenant_id)` 方法
- 需要新增对应的 Alembic 迁移文件

---

#### 🔴 B2. JWT 签发时未写入 `features`

**文档位置**：第 3.1 节 / 第 3.2 节
**代码位置**：`backend/app/core/security.py` 第 17-21 行

**问题描述**：
现有 `create_access_token` 仅写入 `{"sub": ..., "tenant_id": ...}`。设计文档假设 JWT payload 中包含 `features` 字段，但没有配套修改 `security.py` 中的 token 签发逻辑。

**影响**：
- `get_current_user`（`dependencies.py` 第 14-32 行）从 DB 查询用户信息并返回，其返回值不会有 `features` 字段
- 即使加了 `get_feature_flags`，它调用 `current_user.get("features", {})` 也会始终返回空 dict

**整改建议**：
1. 修改 `security.py` 中的 `create_access_token`，新增 `features` 参数
2. 修改 `auth_service.py` 中的 `login` 方法，在生成 token 前查询租户的 `package_modules` 并写入 claims
3. 或者修改 `get_current_user` 在 `dependencies.py` 中合并 JWT payload 信息（而非从 DB 重新查询）

---

#### 🔴 B3. `async def __init__` 语法无效

**文档位置**：第 8.3 节（design doc 第 769-772 行）

```python
async def __init__(self, db, feature_flags=None):
    super().__init__(db, feature_flags)
    self._andon_repo = AndonRepository(db)
```

**问题描述**：
Python 的 `__init__` 方法不能声明为 `async`。CPython 解释器不会将 `async def __init__` 视为异步构造函数，它只是返回一个 coroutine 对象而非初始化后的实例。当 `get_tenant_repo(EnergyRepository)` 调用 `repo_class(db)` 时，得到的将是一个 coroutine 而非 `EnergyRepository` 实例，会触发运行时错误。

**影响**：
- `EnergyRepository` 无法被 `get_tenant_repo` 工厂正常实例化
- `AndonRepository` 的跨模块联动完全无法初始化
- 测试代码中任何 `EnergyRepository(db)` 调用都会异常

**整改建议**（三选一）：
1. **推荐**：使用惰性属性（`@property` + 首次访问时初始化 `AndonRepository`）
2. 使用 `__post_init__` 风格的显式初始化方法（如 `async def init_async(self)`）在首次使用前调用
3. 使用类级别的工厂方法 `@classmethod async def create(cls, db, feature_flags)`

---

#### 🔴 B4. 缺少两个核心依赖：`aiosqlite` 和 `pyyaml`

**文档位置**：第 7.3 节（SQLite）/ 第 11.3 节（yaml）
**代码位置**：`requirements.txt`

**问题描述**：

| 依赖 | 用途 | 是否在 requirements.txt |
|:-----|:------|:-----------------------|
| `python-jose[cryptography]` | JWT 编解码 | ✅ 已存在（3.3.0） |
| `aiosqlite` | SQLite 异步引擎（独立部署模式） | ❌ **缺失** |
| `pyyaml` | 场景规则引擎 YAML 解析 | ❌ **缺失** |

当前 `requirements.txt` 共 11 个依赖，不含 `aiosqlite` 和 `pyyaml`。

**影响**：
- 独立部署模式：`database.py` 调用 SQLite 时会因缺少 `aiosqlite` 驱动而崩溃
- 场景规则引擎：`import yaml` 会在 `ScenarioEngine` 首次加载时抛出 `ModuleNotFoundError`

**整改建议**：
```txt
# 新增到 requirements.txt
aiosqlite>=0.20.0
pyyaml>=6.0
```

---

#### 🔴 B5. feature_flags 通过 `repo.feature_flags` 直接属性注入，未定义类型

**文档位置**：第 3.3 节 / 第 5.1 节
**代码位置**：`app/repositories/base.py`（MultiTenantRepository）

**问题描述**：
设计文档中，`get_tenant_repo` 工厂函数通过 `repo.feature_flags = features` 直接属性注入。但现有 `MultiTenantRepository` 的 `__init__` 仅接受 `db` 参数，没有 `feature_flags` 参数，也没有声明 `feature_flags` 类型注解。此外，现有 `base.py` 第 46 行有 `_tenant_id: Optional[str] = None` 类变量声明，但没有 `feature_flags` 的对应声明。

**影响**：
- `repo.feature_flags = features` 虽然 Python 语法允许，但缺少类型注解，IDE 无法提供自动补全和类型检查
- 新写的 `self.resolve(data_type)` 方法在 `energy_repo.py` 中调用时，若 `feature_flags` 为 `None` 会导致 `DataRouteResolver.resolve(data_type, None)` 报错
- `MultiTenantRepository.__init__` 签名变更会影响所有现有子类（TenantRepo, UserRepo, RoleRepo, AndonRepo, EnergyRepo）

**整改建议**：
在 `base.py` 的 `MultiTenantRepository` 类中添加：

```python
class MultiTenantRepository(Repository):
    _tenant_id: Optional[str] = None
    feature_flags: Dict[str, bool] = {}  # 新增
    
    def __init__(self, session: AsyncSession, feature_flags: Optional[Dict[str, bool]] = None):
        super().__init__(session)
        self.feature_flags = feature_flags or {}
```

同时需检查所有子类的 `__init__` 是否需要透传 `feature_flags`。

---

#### 🔴 B6. 无测试基础设施 — `tests/` 目录完全不存在

**文档位置**：第 10 节
**实际状态**：在 `backend/` 目录下不存在 `tests/` 目录

**问题描述**：
设计文档提出了一套"场景驱动的测试架构"（`tests/scenarios/`），但项目中不存在任何测试目录或测试文件。这意味着：
- 需要新建 `tests/` 目录结构
- 需要新建 `tests/conftest.py` 配置 pytest
- 需要安装 `pytest`、`pytest-asyncio` 等测试依赖
- 需要新建测试数据库 fixture

**影响**：
- Phase 1 任务清单中的测试项无法在编码阶段同步开展
- 条件路由的 32 种场景组合无法验证
- 测试成本（搭建基础设施）被低估

**整改建议**：
1. 在 `requirements.txt` 或新建 `requirements-dev.txt` 中添加：`pytest>=8.0`, `pytest-asyncio>=0.24`, `httpx>=0.27`
2. 新增 `tests/conftest.py` 提供异步 DB session fixture
3. 在 Phase 1 任务清单中明确标注"搭建测试基础设施（1h）"

---

### 🟡 重要级（共 5 项，建议在编码前或首批 Sprint 中解决）

#### 🟡 W1. `get_current_user` 和 `get_feature_flags` 的注入时序耦合

**文档位置**：第 3.3 节
**代码位置**：`app/core/dependencies.py`

**问题描述**：
设计文档的 `get_feature_flags` 依赖 `get_current_user`。但当前 `get_current_user` 的实现（`dependencies.py` 第 14-32 行）做了两件事：
1. 从 JWT 解析 payload → 获取 `user_id`
2. 从 DB 查询用户完整信息 → 返回 user dict

如果需要从 JWT payload 直接读取 `features`，当前设计有两种方式：
- **方式 A**：修改 `get_current_user` 从 JWT payload 直接返回全部 claims（含 `features`）→ 无需额外 DB 查询
- **方式 B**：新增 `get_feature_flags` 函数，从 `get_current_user` 返回的 user dict 中取 `features`

**问题**：当前代码走的是方式 A 的反面——它用 `user_id` 重新查 DB 返回了 `UserRepository.get()` 的结果，而这个结果根本不含 `features`。所以无论方式 A 还是 B，当前代码都需要改动。

**整改建议**：
推荐方式 A 的变体——将 JWT 解析和 DB 查询分离：
1. `get_current_user_claims`：仅解析 JWT，返回 payload（含 `features`）
2. `get_current_user`（保留现有）：用于需要完整用户信息的场景
3. `get_feature_flags`：从 `get_current_user_claims` 的返回值中提取 `features`

---

#### 🟡 W2. 文件变更清单遗漏 4 个文件

**文档位置**：附录 A
**实际代码**：按设计文档描述必须修改但未列入清单的文件

| 遗漏文件 | 理由 | 需要做什么 |
|:---------|:------|:----------|
| `app/core/security.py` | JWT 签发时必须写入 `features` | `create_access_token` 新增 `features` 参数 |
| `app/services/auth_service.py` | 登录逻辑需要在生成 token 前获取 `features` | 在 `login` 方法中读取租户套餐，传入 token |
| `app/models/tenant.py`（或新增模型） | 需要 `package_modules` 字段存储套餐配置 | 新增字段或关联表 |
| `requirements.txt` | 需要新增 `aiosqlite`、`pyyaml`、测试依赖 | 添加 5 个新依赖 |

此外，设计文档声明 `app/repositories/andon_repo.py` 为"无修改"，但实际上如果要实现跨模块事务回滚（第 8.3 节），`AndonRepository` 需要暴露一个 `create_call_with_same_session` 方法给 `EnergyRepository` 使用，或至少需要确认两个 Repo 共享同一个 session 对象的正确性。

**整改建议**：更新附录 A 文件变更清单，补充上述遗漏项。

---

#### 🟡 W3. `_create_andon_call` 方法未在 EnergyRepository 中定义

**文档位置**：第 6.2 节（design doc 第 529 行）

```python
await self._create_andon_call(andon_data)
```

**问题描述**：
`energy_repo.py` 中调用了 `self._create_andon_call()`，但该设计代码片段中并未定义此方法。从上下文推断，它应该调用 `self._andon_repo.create_call(andon_data)`。这是一个接口定义层面的断裂——如果按设计文档的伪代码逐字照搬编码，会出现 `AttributeError`。

**整改建议**：在 EnergyRepository 中定义：

```python
async def _create_andon_call(self, andon_data: dict) -> int:
    return await self._andon_repo.create_call(andon_data)
```

---

#### 🟡 W4. `standalone_auth.py` 与现有 `security.py` 的功能重叠问题

**文档位置**：第 7.5 节
**代码位置**：`app/core/security.py` vs 新增的 `app/core/standalone_auth.py`

**问题描述**：
`standalone_auth.py` 中又重新定义了一套 JWT 编码/解码逻辑（`from jose import jwt`），而现有 `security.py` 已有完全相同的 `verify_token` 和 `create_access_token` 函数。这会导致：

1. **代码重复**：两套 JWT 逻辑需同步维护
2. **密钥管理混乱**：独立部署模式使用 `STANDALONE_JWT_SECRET`，SaaS 模式使用 `JWT_SECRET_KEY`，但两个文件都依赖 `get_settings()`
3. **`main.py` 的启动分支**（第 7.6 节）中，独立模式不注册其他模块路由，但共享的 `dependencies.py` 中的 `get_current_user` 仍依赖 SaaS 认证逻辑

**影响**：
- 独立部署模式下，`get_current_user` 仍会走 `verify_token(credentials.credentials)`，使用的是 `settings.JWT_SECRET_KEY`，而非 `settings.STANDALONE_JWT_SECRET`
- 独立模式下签发和验签的密钥不一致，会导致认证失败

**整改建议**：
1. 不要在 `standalone_auth.py` 中重新实现 JWT 工具函数，而是复用 `security.py`，通过传入不同密钥
2. 创建统一的 `get_authenticator(standalone: bool) -> Callable` 工厂函数，根据部署模式返回不同的认证依赖注入函数
3. 或者：`standalone_auth.py` 只负责"认证"（验证用户名密码），JWT 签发仍调用 `security.py`

---

#### 🟡 W5. `DataRouteResolver.resolve` 不处理 feature_flags 为 `None` 的情况

**文档位置**：第 4.2 节（design doc 第 307-323 行）

**问题描述**：
`resolve` 方法的 `feature_flags` 参数类型为 `Dict[str, bool]`，但未标注 `Optional`。当 `feature_flags` 为 `None` 时，第 316 行的 `feature_flags.get(flag_or_default, False)` 会抛出 `AttributeError`。

**影响**：
- 新租户首次登录或 JWT 未携带 `features` 时，整个路由解析会崩溃
- 测试中如果 fixture 未设置 `feature_flags` 也会异常

**整改建议**：
```python
@classmethod
def resolve(cls, data_type: DataType, feature_flags: Optional[Dict[str, bool]] = None) -> RouteStrategy:
    feature_flags = feature_flags or {}
    # ... 原有逻辑 ...
```

---

### 🟢 建议级（共 4 项，优化项，不影响编码启动）

#### 🟢 S1. `get_tenant_repo` 工厂函数与 feature_flags 注入的集成

**文档位置**：第 3.3 节
**代码位置**：`app/core/dependencies.py`（`get_tenant_repo` 函数）

**建议**：
当前 `get_tenant_repo` 只注入 `tenant_id`。设计文档在第 3.3 节提出了通过 `get_feature_flags` 注入 `repo.feature_flags` 的方案，但没有修改 `get_tenant_repo` 去集成这个注入。应该统一：

```python
async def _factory(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    features: Dict[str, bool] = Depends(get_feature_flags),
) -> T:
    repo = repo_class(db, feature_flags=features)
    tenant_id = current_user.get("tenant_id") if current_user else None
    if tenant_id and hasattr(repo, "set_tenant_id"):
        repo.set_tenant_id(tenant_id)
    return repo
```

这样 `get_tenant_repo` 的调用者无需关心 feature_flags 的注入细节。

---

#### 🟢 S2. `_list_devices_standalone_mode` 的 `is_active` 过滤逻辑冗余

**文档位置**：第 6.2 节（design doc 第 474-487 行）

**建议**：
`_list_devices_standalone_mode` 中 `is_active` 过滤条件与 `_list_devices_tpm_mode` 存在不一致——TPM 模式没有 `is_active` 过滤。如果这是设计意图，建议在 TPM 模式的 SQL 中也增加 `ed.is_active = true` 作为隐式条件（仅过滤能源设备，不过滤 equipment），避免接口行为不一致。

---

#### 🟢 S3. RouteStrategy 枚举中缺少 `QUALITY_MODULE` 值

**文档位置**：第 4.4 节（design doc 第 347 行）

**建议**：
文档在"扩展新模块"示例中使用了 `RouteStrategy.QUALITY_MODULE`，但该值未在 `RouteStrategy` 枚举类中定义。新增模块时容易忘记同步更新枚举。建议在枚举定义中提前预留或增加注释说明。

---

#### 🟢 S4. 迁移工作量估算中缺少测试和文档时间

**文档位置**：第 9.3 节（28h 汇总）

**建议**：
28h 仅覆盖端点迁移的编码时间，未包含：
- 每个迁移端点的单元测试（按经验约占编码时间的 30-50%）
- 场景路由测试（32 种组合 × 每组合至少 1 个端到端测试）
- 独立部署模式的集成测试
- 文档更新（API 文档、迁移记录）

建议在 28h 基础上增加 10-15h 的测试和文档时间，更实际的总工时为 **38-43h**。

---

## 二、对比：现有代码 vs 设计文档的关键差异

| 维度 | 现有代码 | 设计文档要求的 | 差距 |
|:-----|:---------|:--------------|:----|
| JWT Payload | `{sub, tenant_id, exp}` | `+ features: {...}` | 🔴 需修改 `security.py` 和 `auth_service.py` |
| Repo 基类 | `__init__(db)` + `_tenant_id` | `__init__(db, feature_flags)` + 两者 | 🔴 需修改 `base.py` 和所有子类 |
| energy_repo | 仅查 energy_device 表 | 条件 JOIN equipment | 🟡 需新增条件分支 |
| create_alert | 仅写 energy_alert | + 可选联动 Andon | 🟡 需注入 AndonRepo |
| Tenant 模型 | 无套餐/模块字段 | 需有 package_modules | 🔴 需新增字段/表 |
| 数据库配置 | 仅 PostgreSQL | + SQLite | 🔴 需 `aiosqlite` |
| 测试 | 不存在 | scenarios/ 体系 | 🔴 需全新建 |

---

## 三、预编码风险评估

按实施过程中可能遇到的技术困难排序：

### 高风险 (🔴)

| # | 风险 | 触发条件 | 症状 |
|:-:|:-----|:---------|:-----|
| R1 | `get_current_user` 在独立部署模式下认证失败 | 独立部署模式启动，请求带 STANDALONE_JWT_SECRET 签发的 Token | `verify_token` 使用 `JWT_SECRET_KEY` 验签，密钥不匹配 → 401 |
| R2 | SQLAlchemy async session 在跨 Repo 共享时出现状态异常 | EnergyRepo 和 AndonRepo 共享同一 session，一方 commit 另一方未 commit | `DetachedInstanceError` 或部分写入 |
| R3 | `query_page` 的 COUNT 子查询在 LEFT JOIN 场景下性能异常 | 设备列表使用 `equipment LEFT JOIN energy_device` 且数据量大 | COUNT 子查询（嵌套了原 SQL）扫描全表，远超预期耗时 |

### 中风险 (🟡)

| # | 风险 | 触发条件 | 症状 |
|:-:|:-----|:---------|:-----|
| R4 | JWT 缓存刷新延迟 | 租户套餐变更，调用 `/refresh-features` 但旧 Token 未过期 | 用户在新 Token 前看到旧路由 |
| R5 | 独立部署的 SQLite 不支持所有 PostgreSQL 特性 | 使用了 PostgreSQL 特有的 SQL（如 `ILIKE`, `array_agg`, `RETURNING`） | SQLite 运行时报错 |
| R6 | 场景规则引擎的 `_eval_condition` 方法未实现 | `ScenarioEngine.validate()` 被调用 | `NotImplementedError` |

### 低风险 (🟢)

| # | 风险 | 说明 |
|:-:|:-----|:------|
| R7 | `scope IN` 的字符串拼接 SQL 注入风险 | `emission_repo.py` 第 57-60 行使用 f-string 拼接 scope 参数，虽然使用了参数化绑定，但拼入字段名时需确保 scope 值被校验 |
| R8 | 32 种场景组合的测试膨胀 | 全组合测试会随模块数指数增长，建议测试策略只覆盖有实际业务意义的组合（设计文档中已列了 8 个，合理） |

---

## 四、编码前必须补充的设计细节

1. **Tenant 模型套餐字段方案** — 需要最终决定是 JSONB 字段还是关联表，以及 JSONB 中 flag 的命名规范是否与 FeatureFlag 命名规范（附录 B）一致
2. **JWT 签发链的完整数据流** — 从 `login()` → `get_tenant_features()` → `create_access_token(data={..., "features": ...})` → `get_current_user` 解析 → `get_feature_flags` 提取的完整链路需要文档化
3. **独立部署的密钥管理方案** — `STANDALONE_JWT_SECRET` 是否应该完全独立于 `JWT_SECRET_KEY`？独立模式下如何防止用户使用 SaaS Token 访问独立部署实例？
4. **Phase 1 事务回滚策略的代码级规范** — 第 8.5 节的 🔴/🟡/🟢 标注需要在方法 docstring 中强制执行，但设计文档没有给出代码规范检查机制

---

## 五、补充建议

1. **自动化依赖检查**：在 CI/pipeline 中加入 `pip install -r requirements.txt` 检查，确保新增的 `aiosqlite` 和 `pyyaml` 可安装
2. **渐进式测试搭建**：不要求一次性完成全部场景测试，建议先搭好 `tests/conftest.py` + 1 个冒烟测试（验证 DataRouteResolver.resolve），再逐步扩展
3. **预生成代码骨架**：建议架构师先输出 `app/core/route_resolver.py` 和 `app/core/scenario_engine.py` 的完整可运行代码，这两文件无外部依赖，可独立编译测试
4. **独立部署认证验证**：建议在编码前先做一个小型 PoC——用 `aiosqlite` + FastAPI 搭建一个 hello-world 异步应用，验证技术栈兼容性
5. **事务边界注解检查**：考虑引入一个简单的 pytest 插件，自动检查所有标注了 🔴 同一事务 的方法是否真的共享了同一个 session 对象

---

## 六、分阶段可实施性判定

| 层级/组件 | 当前是否可编码 | 前置条件 |
|:----------|:-------------:|:---------|
| **Layer 1: FeatureFlag 注入** | ❌ | 需先解决 B1（Tenant 套餐字段）、B2（JWT 签发 features） |
| **Layer 2: DataRouteResolver** | ✅ | 无外部依赖，纯函数，可立即编码 🎉 |
| **Layer 3: Repo 条件路由** | ❌ | 需先解决 B3（async __init__）、B5（MultiTenantRepository 改造） |
| **场景规则引擎** | ⚠️ 部分可行 | 纯 Python 逻辑可编，但需要先安装 `pyyaml`（B4） |
| **独立部署模式** | ❌ | 需先解决 B4（aiosqlite）、W4（认证密钥）、B5（MultiTenantRepository 改造） |
| **迁移 52 个端点** | ❌ | 需 Layer 2+3 就绪后，逐端点进行 |
| **场景测试架构** | ⚠️ 部分可行 | `tests/conftest.py` + `pytest` 配置可立即搭建，但场景 fixture 需等 Layer 1 完成 |

### 建议的编码顺序

```
Phase 0（前置准备, 1-2天）
  ├── 新增 aiosqlite + pyyaml 到 requirements.txt
  ├── Tenant 模型新增 package_modules（JSONB）
  ├── security.py: create_access_token 新增 features 参数
  ├── auth_service.py: login 时获取并写入 features
  └── base.py: MultiTenantRepository 支持 feature_flags

Phase 0.5（可并行编码）
  ├── route_resolver.py（DataRouteResolver — 无依赖）
  ├── tests/conftest.py + 冒烟测试
  └── scenario_rules.yaml + scenario_engine.py（除 yaml 解析外可单独测）

Phase 1（核心路由改造）
  ├── dependencies.py: get_feature_flags
  ├── energy_repo.py: 条件路由改造
  ├── standalone_auth.py + 配置
  └── main.py: 独立部署分支
```

---

## 七、结论

**现有设计整体方向正确**：三层路由架构清晰、声明式路由表设计优雅、路由与执行分离原则合理。DataRouteResolver 的接口定义可以直接开始编码。

**但存在 6 个阻断项（🔴 B1-B6）**，其中 B3（`async __init__`）是典型的"设计阶段容易忽略的 Python 语法约束"，建议在最终设计稿中直接修正为惰性属性方案；B1 和 B2（Tenant 套餐字段 + JWT features 写入）是整个方案的根基，必须先落地。

**最让我（作为实施者）担心的是独立部署的认证密钥一致性问题**（W4）—— 它看起来是一个小细节，但在运行时会导致 401 错误，且排查路径隐蔽（快速排查思路：在独立模式下启动后调用 `/api/v1/energy/devices`，如果返回 401 而非 200，优先检查 JWT 验签使用的 key 是否正确）。

**可立即开始的编码工作**：`app/core/route_resolver.py`（含 DataType 和 RouteStrategy 两个枚举 + DataRouteResolver 类）—— 纯函数、零依赖，5 分钟内可写出完整可运行代码。

---

*报告结束*
