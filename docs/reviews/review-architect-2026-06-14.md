# 架构评审报告 — 数据路由与模块整合方案

> **评审人**：高见远（Gao）· 架构师  
> **评审日期**：2026-06-14  
> **评审对象**：`data-routing-integrated-design.md` (D1)  
> **关联文档**：D2(M11-能碳整合-v2) / D3(自选套餐-数据路由策略) / D4(自选套餐-全场景枚举表)  
> **现有代码基**：`backend/app/` (源系统)  
> **评审性质**：🔴 实质评审（非走过场）

---

## 目录

1. [总体判定](#一总体判定)
2. [问题清单](#二问题清单)
3. [与旧方案的差异分析](#三与旧方案的差异分析d1-与-d2d3d4-路由变更差异表)
4. [补充建议](#四补充建议)
5. [附录：变更追踪表](#五附录变更追踪表)

---

## 一、总体判定

### ❌ 暂缓进入编码阶段。需先解决 3 个 🔴 阻断性问题。

| 维度 | 判定 | 说明 |
|:----|:----|:------|
| **架构完整性** | 🟡 基本完整 | 三层路由架构覆盖了主要场景，但 JWT 刷新时序、数据迁移策略有缺失 |
| **可实施性** | 🔴 **不可直接编码** | 3 个阻断性问题 + 4 个重要问题必须在编码前解决 |
| **旧方案冲突消除** | 🟡 部分解决 | 设备查询冲突已消除，但告警联动的事务语义仍模糊 |
| **未来扩展性** | 🟢 良好 | DataRouteResolver 的声明式设计可支撑 13 个模块，但 Repo 层的扩展声称有误导 |
| **安全性** | 🔴 **有风险** | JWT 注入方案无失效机制 + 独立部署默认密码硬编码 |
| **工作量可信度** | 🟢 可接受 | 28h 的逐条盘点可信，相比原 3h 有实质性改进 |

### 进入编码的前置条件

1. **必须解决**：JWT 无失效机制（🔴 B2）、独立部署默认密码（🔴 B3）、事务边界歧义代码（🔴 B5）
2. **确认至少 1 个设计方案**：是否增加路由结果缓存层（🟡 Y1 升级为决策）
3. **补充文档**：新增"M01/M02 数据兼容性迁移"章节

---

## 二、问题清单

### 🔴 阻断性问题（3 个 — 编码前必须解决）

#### 🔴 B1：FeatureFlag JWT Payload 膨胀风险

| 属性 | 值 |
|:----|:----|
| **严重性** | 🔴 阻断 |
| **位置** | D1 §3.2 JWT Payload 结构 |
| **影响范围** | 全平台所有 API 请求 |
| **发现类别** | 架构遗漏 |

**问题描述**：
当前 JWT payload 中 `features` 字段包含 10 个 flag。按设计扩展到 13 个模块，每个模块可能包含 2~3 个子功能（如 M01_WORK_ORDER + M01_WORK_REPORT），flag 数量将达到 **20~30 个**。JWT 作为 Bearer Token 随 **每个 HTTP 请求** 发送，payload 膨胀将导致：
- 每次请求 Header 增加 2~3KB（Base64 编码后）
- 在 1000+ 并发租户场景下，纯带宽浪费显著
- 如果未来新增模块粒度更细的 flag（如 M01_* 扩展为 M01_PRODUCTION_LINE / M01_BOM / M01_SCHEDULING），flag 数量可能突破 50+

**建议修复方案**：
- 选项 A（推荐）：JWT 中仅存储 `features_hash`（模块位图或紧凑编码），在应用启动时预热全量 feature 映射表。请求到达时仅需 O(1) 查表匹配。
- 选项 B：将 features 从 JWT payload 移至 Redis 缓存，JWT 中仅存 `tenant_id`，服务端通过 tenant_id 查询缓存。优点是 JWT 体积最小化，缺点是增加一次缓存查询。
- 选项 C：接受 JWT 膨胀但添加压缩（如使用 `zlib` 压缩 features 字段）。这是最简单的妥协方案。

---

#### 🔴 B2：套餐变更后旧 JWT 无失效机制

| 属性 | 值 |
|:----|:----|
| **严重性** | 🔴 阻断 |
| **位置** | D1 §3.1 JWT 存储方案 + §3.4 刷新端点 |
| **影响范围** | 租户套餐变更 → 数据安全 |
| **发现类别** | 安全漏洞 |

**问题描述**：
D1 的设计流程是："套餐变更 → POST /api/v1/tenant/refresh-features → 刷新 JWT"。

但关键问题：**旧 JWT 仍然有效直到过期**（默认 30 分钟）。这意味着：
1. 管理员将某租户的 M11 能碳模块从"已购买"改为"未购买"
2. 但拥有旧 JWT 的用户仍可在 30 分钟内继续使用 M11 的 API
3. JWT 签发给了单个用户，但套餐变更发生在租户级别——当前用户可能需要"退出登录再重新登录"才能获得新 token，而不仅仅是调用 refresh-features

更严重的是，refresh-features 端点**没有验证"套餐变更是谁发起的"**。D1 §3.4 的代码中，调用了 `get_current_user` 和 `get_tenant_repo`，但谁能调用此端点？普通用户能否自行刷新获取更多模块权限？这些都没有定义。

**建议修复方案**：
- 选项 A（推荐）：引入 **JWT 黑名单（Redis 缓存）**。每次套餐变更时，将该租户所有已签发 JWT 的 `jti`（JWT ID）加入黑名单，TTL 设为原 JWT 的剩余有效期。API 层在 `get_current_user` 中增加黑名单校验。
- 选项 B：降低 JWT 过期时间到 1 分钟（不现实，频繁刷新 token 影响性能）。
- 选项 C（临时方案）：在 refresh-features 端点上增加 `admin_only` 权限校验，并在部署文档中明确说明"最长 30 分钟生效延迟"。

**增强建议**：
- 将 `jti`（JWT ID）加入标准 payload，使黑名单可操作
- refresh-features 端点应限制为 `tenant_admin` 角色可调用

---

#### 🔴 B3：独立部署模式硬编码默认密码

| 属性 | 值 |
|:----|:----|
| **严重性** | 🔴 阻断 |
| **位置** | D1 §7.5 `standalone_auth.py:689` |
| **影响范围** | 独立部署模式的安全性 |
| **发现类别** | 安全漏洞 |

**问题描述**：
```python
STANDALONE_USERS = {
    "admin": {
        "password": settings.STANDALONE_ADMIN_PASSWORD or "admin123",
        ...
    }
}
```

`"admin123"` 作为硬编码默认密码是 **严重安全风险**。在实际部署中，运维人员可能忘记设置 `STANDALONE_ADMIN_PASSWORD` 环境变量，导致系统以默认密码运行。这将使任何能访问独立部署实例的人以管理员身份登录。

**建议修复方案**：
- **必须**：移除硬编码默认值。改为：
  ```python
  if not settings.STANDALONE_ADMIN_PASSWORD:
      raise RuntimeError("STANDALONE_ADMIN_PASSWORD 环境变量未设置，独立部署模式无法启动")
  ```
- **附加**：在首次启动时强制要求修改密码（类似"首次登录强制修改密码"流程）

---

#### 🔴 B4（补充）：跨模块调用事务边界存在歧义代码

| 属性 | 值 |
|:----|:----|
| **严重性** | 🔴 阻断 |
| **位置** | D1 §8.3 `energy_repo.py:create_alert()` 第 789-792 行 |
| **影响范围** | M11 告警 + M05 安灯联动 |
| **发现类别** | 设计歧义 |

**问题描述**：
```python
except Exception as e:
    logger.warning(f"安灯联动失败 (告警ID={alert_id}): {e}")
    # 当前事务中，安灯失败 → 整个事务回滚
    raise  # 或者可以选择不 raise → 仅告警成功
```

这段代码包含注释标注的两个互斥的行为：
1. `raise` — 安灯失败 → 整个事务回滚（包括已成功的告警插入）
2. 不 raise — 安灯失败 → 仅告警成功（安灯联动静默失败）

**这是业务决策，不是技术决策。** 代码中同时保留了两种路径，但没有任何注释说明什么条件下走哪条路径。

**建议修复方案**：
- 明确业务决策：从 Phase 1 的同事务联动设计来看，应当是 `raise`（事务回滚）。如果业务上允许"告警成功但安灯失败"，则应在 Phase 1 就从同事务方案改为独立事务方案（方案 B），而不是在代码中留一个"装了但最后不 raise 的 try-except"。
- 删除歧义注释，锁定一种行为。

---

### 🟡 重要问题（4 个 — 建议编码前解决）

#### 🟡 Y1：DataRouteResolver 路由结果无缓存

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟡 重要 |
| **位置** | D1 §4 DataRouteResolver |
| **影响范围** | 性能（高频 API） |

**问题描述**：
`DataRouteResolver.resolve()` 是纯函数、无缓存。每次 API 请求（设备列表、告警列表、碳排放核算等）都会调用此方法。在最坏情况下，一个页面加载可能触发 5~8 次 resolve 调用（不同数据类型）。

虽然每次遍历是 O(n)（n 为 route_map 条目数），但在 1000+ 并发租户规模下，这不算零成本。`feature_flags` 在同一租户的同一 JWT 生命周期内不会变化，理论上路由结果是可缓存的。

**建议修复方案**：
- 在 `MultiTenantRepository` 层增加 `_route_cache: Dict[DataType, RouteStrategy]` 字典
- `resolve()` 方法先查缓存，缓存未命中再调用 DataRouteResolver
- 在 `feature_flags` 更新时清空缓存

```python
class MultiTenantRepository:
    def __init__(self, db, feature_flags=None):
        self.db = db
        self.feature_flags = feature_flags or {}
        self._route_cache: Dict[DataType, RouteStrategy] = {}
    
    def resolve(self, data_type) -> RouteStrategy:
        if data_type not in self._route_cache:
            self._route_cache[data_type] = DataRouteResolver.resolve(data_type, self.feature_flags)
        return self._route_cache[data_type]
```

---

#### 🟡 Y2：Repo 层"新增模块只需加一行配置"的说法有误导

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟡 重要 |
| **位置** | D1 §4.4 扩展新模块 |
| **影响范围** | 开发预期管理 |

**问题描述**：
D1 §4.4 声称"无需修改任何 Repo 方法内部的 if/else 结构"。但事实上：

1. `DataType` 枚举新增一个值
2. `RouteStrategy` 枚举新增一个值  
3. `ROUTES` 字典新增一条映射
4. **每个相关的 Repo 方法**仍需新增 `if strategy == RouteStrategy.NEW_STRATEGY:` 分支来处理新的逻辑

步骤 4 是无法通过声明式配置消除的。D1 的声明式路由解决了"选择哪个策略"的问题，但没有解决"策略选定后执行什么 SQL/逻辑"的问题。Repo 内的条件分支是必然存在的。

**建议修复方案**：
- 修正文档中的描述，准确表述为："新增模块只需在 ROUTES 字典中新增路由规则，但 Repo 方法中需要新增对应的 SQL 执行分支"
- 或者在架构层面进一步抽象：将 SQL 模板也移入配置驱动（类似 MyBatis 的 SQL 映射文件），但 Phase 1 不必过度设计

---

#### 🟡 Y3：FeatureFlag 默认值配置的维护负担

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟡 重要 |
| **位置** | D1 §5.2 `DEFAULT_FEATURES` 字典 |
| **影响范围** | 长期维护 |

**问题描述**：
`DEFAULT_FEATURES` 字典在 `dependencies.py` 中硬编码了所有已知模块的默认值：

```python
DEFAULT_FEATURES = {
    "M01_WORK_ORDER": False,
    "M01_WORK_REPORT": False,
    # ... 所有 10 个 flag 都要手动维护
}
```

当扩展到 13 个模块时，此列表需要同步更新。如果新增模块时忘记在此处添加默认值，而 JWT 中也没有该 flag，则 `current_user.get("features", {}).get("M14_NEW_MODULE")` 会返回 `None`（被当作 False 处理），行为与显式 `False` 相同，所以功能上不会出错。但这不是"Fail Fast"——应该让未注册的 flag 在开发/测试阶段就跑出异常。

**建议修复方案**：
- 将默认值表改为从 `RouteStrategy` 和 `DataType` 枚举自动推导（每个 DataType 关联的 flag 列表）
- 或者在 `DataRouteResolver.resolve()` 中遇到未知 flag 时输出 warning 日志（开发环境）/ 静默忽略（生产环境）

---

#### 🟡 Y4：独立部署模式的数据库迁移策略不够明确

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟡 重要 |
| **位置** | D1 §7.3 数据库迁移策略 |
| **影响范围** | 独立部署运维 |

**问题描述**：
D1 设计了两种迁移目录：
```
backend/
  alembic/versions/       # 全平台 PostgreSQL
  migrations/standalone/  # 独立部署 SQLite
```

但存在以下未明确的问题：
1. **SQLite 不支持 `RETURNING id`** — 当前 `energy_repo.py:create_device()` 使用 `RETURNING id`，这在 SQLite 3.35+ 支持，但旧版本不支持。是否需要兼容？
2. **SQLite 无 `schema` 概念** — 全平台模式可能使用 schema 做模块隔离（见架构设计书 V1.0 ADR-009），但 SQLite 不支持。两种迁移的输出格式不同。
3. **迁移脚本的同步机制** — 当全平台 `energy.py` 模型变更时，SQLite 的 `v001_initial.sql` 是否需要同步更新？没有流程保证一致性。

**建议修复方案**：
- 明确 SQLite 最低版本要求（≥ 3.35，支持 RETURNING）
- 增加自动化检查：CI 中校验独立部署的建表 SQL 与 SQLAlchemy 模型定义一致
- 或者在独立部署模式中也使用 Alembic（配置不同的数据库 URL），避免两套迁移脚本的不一致

---

### 🟢 建议性问题（3 个 — 可在编码中逐步优化）

#### 🟢 G1：独立部署认证与全平台认证的代码复用率低

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟢 建议 |
| **位置** | D1 §7.5 vs 现有 `security.py` |

`standalone_auth.py` 重新实现了 JWT 签发逻辑，与 `security.py` 中的 `create_access_token()` 有大量重复。建议将 JWT 签发抽象为公共函数，独立部署模式和 SaaS 模式共用同一套 `create_access_token()`，仅在用户认证逻辑处分支。

---

#### 🟢 G2：场景规则引擎的 YAML 路径硬编码

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟢 建议 |
| **位置** | D1 §11.3 `scenario_engine.py` |

```python
def __init__(self, rules_path: str = "app/core/scenario_rules.yaml"):
    with open(rules_path, "r") as f:
```

相对路径 `"app/core/scenario_rules.yaml"` 在部署为 Python 包后将不工作。建议使用：
```python
import importlib.resources as pkg_resources
# 或
_path = os.path.join(os.path.dirname(__file__), "scenario_rules.yaml")
```

---

#### 🟢 G3：路由规则不支持复合条件

| 属性 | 值 |
|:----|:----|
| **严重性** | 🟢 建议 |
| **位置** | D1 §4.2 ROUTES 规则表 |

当前路由规则只支持单 flag 匹配。未来可能出现复合条件场景（如 "M02_EQUIPMENT AND M11_ENERGY" 才走 TPM 设备 JOIN）。建议在 Phase 2 考虑支持表达式引擎（或简单 `AND`/`OR` 组合），但 Phase 1 不做。

---

## 三、与旧方案的差异分析（D1 与 D2/D3/D4 路由变更差异表）

> **说明**：D2（M11 能碳整合 v2）、D3（自选套餐-数据路由策略）、D4（自选套餐-全场景枚举表）为上游输入方案，D1（本评审对象）为整合方案。以下分析 D1 相比三份旧方案的路由技术路线变更。

### 3.1 路由变更差异总表

| 对比维度 | D2（M11 能碳整合 v2） | D3（自选套餐路由策略） | D4（全场景枚举表） | **D1（新整合方案）** | 变更说明 |
|:---------|:--------------------|:---------------------|:-----------------|:-------------------|:---------|
| **设备查询** | 写死 LEFT JOIN `equipment` + `energy_device` | 条件 if/else 判断套餐 → 不同 SQL 路径 | 枚举场景 A/B/C/D → 映射查询方式 | **FeatureFlag 驱动的 DataRouteResolver** | ✅ **冲突已消除**。用声明式路由替代了 D2 的写死 JOIN 和 D3 的条件 if/else |
| **告警联动** | 隐式依赖 M05，未明确事务边界 | 条件判断联动/不联动 | 枚举场景→映射安灯规则 | **FeatureFlag 驱动 + 事务边界标注** | ✅ **冲突已消除**。统一了判断逻辑，增加了事务边界文档化 |
| **路由实现方式** | Repo 方法内写 SQL | Service 层条件判断 | 预定义映射表 | **三层架构：注入 → 解析 → 执行** | 🔄 **架构升级**。路由选择与执行分离 |
| **FeatureFlag** | 未涉及 | 提及但未实现 | 未涉及 | **JWT 注入 + 懒刷新** | 🆕 **全新设计** |
| **模块扩展** | 本次仅 M11 | 提及多模块 | 枚举 6 大场景 | **声明式 ROUTES 字典扩展** | ✅ 优于旧方案 |
| **独立部署** | 未涉及 | 未涉及 | 未涉及 | **M11_STANDALONE 配置 + SQLite** | 🆕 **全新设计**（旧方案均未覆盖） |
| **事务边界** | 未定义 | 未定义 | 未定义 | **同事务/独立事务/异步消息 三选标注** | 🆕 **全新设计** |
| **测试策略** | 未涉及 | 未涉及 | 未涉及 | **场景驱动的参数化测试** | 🆕 **全新设计** |
| **场景枚举** | 未涉及 | 部分提及 | 全手工 Markdown 枚举 | **YAML 规则引擎 + 约束规则** | ✅ 优于 D4。将静态枚举表转化为可编程规则 |
| **工作量评估** | ~3h | 未评估 | 未评估 | **28h（逐条盘点 52 个端点）** | ✅ **重大修正**。修正了 9 倍差距 |
| **供应商归属** | 未提及 | 未提及 | 未提及 | **标记为"待决策"** | ❌ **仍待决策**。供应商品归属 M11 还是全平台未决定 |

### 3.2 旧方案中被 D1 舍弃的内容

| 旧方案内容 | D1 处理 | 合理性 |
|:----------|:--------|:------|
| D3 的"Service 层做路由判断"方案 | ❌ 舍弃，改为 Repo 层路由 | ✅ 合理。表现层无路由是正确决策 |
| D4 的全场景手工枚举表 | ❌ 舍弃，改为规则引擎 | ✅ 合理。手工枚举到 13 模块不可维护 |
| D2 的设备查询写死 LEFT JOIN | ❌ 舍弃，改为条件路由 | ✅ 合理。全平台和独立部署模式路由不同 |
| D3 的部分条件 if/else 在 API 层 | ❌ 舍弃，路由全下沉到 Repo | ✅ 合理。API 路由层应不感知套餐 |

### 3.3 仍未被 D1 覆盖的旧方案内容

| 旧方案内容 | 当前状态 | 影响 |
|:----------|:---------|:-----|
| D3 中的"自选套餐定价/配置逻辑" | D1 §11 场景规则引擎覆盖了约束规则，但未覆盖定价逻辑 | 🟡 需要产品经理确认定价逻辑是否在路由方案中体现 |
| D4 中 M13 看板的数据聚合方式 | D1 仅提及"看板需数据源"约束规则，未明确看板的数据聚合技术方案 | 🟢 可独立于路由方案，属于 M13 看板自身设计 |
| 旧方案中系统管理(carbon_asset)的模块归属 | D1 §9.4 标记为"需判断是否属于 M11" | 🟡 未决策，影响 P2 迁移 |

---

## 四、补充建议

### 4.1 架构层面建议

1. **为 FeatureFlag 增加版本号字段**：JWT payload 中增加 `features_version: int`。当套餐变更时递增版本号。API 层可以快速判断版本是否最新（通过 Redis 缓存版本号），而无需解析全部 features。这可以解决 🔴 B2 的一部分问题。

2. **Repo 层考虑 Query Object 模式**：Phase 2 时，可将条件路由的不同 SQL 分支封装为独立的 Query Object，通过依赖注入选择。避免 Repo 内出现大量 if/else 分支。

3. **三层路由架构是否过度设计？** — 我的判断：**当前是合理的，但不排除过度的可能**。
   - Layer 1（FeatureFlag 注入）和 Layer 3（Repo 多态执行）是必须的，没有争议
   - Layer 2（DataRouteResolver）在当前 7 个模块的场景下显得"重"，但扩展到 13 个模块后会显现价值
   - **风险信号**：如果未来每个 RouteStrategy 在 Repo 中的处理分支超过 3~5 个，说明路由抽象不够细；如果始终只有 2 个分支（TPM vs standalone），说明 Layer 2 过度设计了
   - **建议**：Phase 1 保留三层架构，但在 Phase 1 结束时做一次架构回顾，评估 Layer 2 的实际价值

### 4.2 实施建议

4. **T01（项目基础设施）**：在创建 `dependencies.py` 时，应同时将 `get_feature_flags` 集成到现有的 `get_tenant_repo` 工厂中，确保所有 Repo 创建时自动获得 feature_flags。这样不需要每个 API 路由手动注入 FeatureFlag。

5. **测试优先级**：先完成 DataRouteResolver 的单元测试（纯函数，无外部依赖），再写 Repo 的集成测试。路由解析是核心逻辑，应最先验证。

6. **迁移顺序**：考虑先迁移"无路由逻辑"的端点（纯 CRUD 操作），再迁移"有路由逻辑"的端点（设备查询/告警联动/碳排放核算）。避免在一个 Sprint 内同时引入路由框架 + 大量迁移任务。

### 4.3 跨文档一致性检查

7. **架构设计书 V1.0 与 D1 的 DAL 层一致**：V1.0 定义了 `MultiTenantRepository` / `SingleTenantRepository`，D1 在此基础上增加了 `feature_flags` 支持。两者兼容。

8. **架构设计书 V1.0 的部署模式路由 vs D1 的独立部署模式**：V1.0 通过 `X-Deploy-Mode: saas/onprem` 请求头做路由，D1 通过 `M11_STANDALONE` 环境变量控制。两者有差异：
   - V1.0：请求头级别（每个请求可不同模式）
   - D1：部署级别（整个实例固定模式）
   - 建议 D1 明确说明：独立部署模式下 `M11_STANDALONE=True` 时，是否存在某些请求仍需要访问全平台数据？如果不存在，则 D1 的环境变量方案优于 V1.0 的请求头方案（更简单）。

### 4.4 工作量估算补充

9. **D1 的 28h 工作量评估已较为可信**，但仍需补充以下隐性成本：
   - **路由框架本身的测试**（估计 2~3h）：DataRouteResolver + ScenarioEngine + 场景测试框架
   - **JWT FeatureFlag 注入的开发与测试**（估计 2h）：dependencies.py 改造 + refresh-features 端点 + 黑名单机制
   - **独立部署模式验证**（估计 1h）：SQLite 迁移脚本验证 + 精简认证测试
   - **总计隐性成本**：约 5~6h，加上已有 28h = **34h 左右**

---

## 五、附录：变更追踪表

### 与评审输入问题的对照

| 评审问题 | 结论 | 对应问题编号 |
|:---------|:-----|:-----------|
| D1 是否彻底消除了 D2/D3/D4 的方案冲突？ | ✅ 基本消除。设备查询和告警联动均统一为 FeatureFlag 驱动 | - |
| DataRouteResolver 能否支撑 13 个模块？ | ✅ 可以。声明式路由字典可线性扩展 | 🟡 Y2（文档声称需修正） |
| FeatureFlag JWT 有无安全漏洞？ | 🔴 **有**。无失效机制 + 无黑名单 | 🔴 B2 |
| 独立部署 vs SaaS 代码复用是否合理？ | 🟡 基本合理，但认证代码有重复 | 🟢 G1 |
| 旧方案中未被 D1 覆盖的内容？ | 定价逻辑 + 供应商归属 + 看板聚合方案 | 见 §3.3 |
| 是否存在过度设计？ | 🟢 当前合理，Phase 1 结束时需回顾 | 见 §4.1.3 |

### 代码文件变更建议更新

建议在 D1 附录 A 的基础上新增以下文件变更：

| 文件路径 | 操作 | 说明 |
|:---------|:----|:------|
| `app/repositories/base.py` | 修改 | 新增 `_route_cache` 缓存 + 清空机制（🟡 Y1） |
| `app/core/security.py` | 修改 | 新增 JWT 黑名单校验函数（🔴 B2） |
| `app/api/tenants.py` | 修改 | refresh-features 增加 admin_only 权限 + jti 黑名单（🔴 B2） |
| `app/core/standalone_auth.py` | 修改 | 移除默认密码，未配置时启动失败（🔴 B3） |
| `docs/architecture/data-migration-plan.md` | **新增** | 现有数据兼容性迁移方案（🔴 B6 建议） |

---

*评审结束。以上包含 3 个 🔴 阻断、4 个 🟡 重要、3 个 🟢 建议问题。总体判定：暂缓编码，3 个阻断问题解决后可进入 Phase 1 实施。*
