# 数据路由与模块整合方案 — 多角色评审汇总报告

> **汇总日期**：2026-06-14
> **评审团队**：P（产品经理）、E（工程师）、Q（QA）、A（架构师）

---

## 总体判定：🔴 不建议进入编码阶段

**三位评审员（PM、工程师、QA）一致判定"不可直接编码"**，架构师的设计文档已完成但需针对评审意见修订。

---

## 一、🔴 阻断级问题汇总（8 个独立问题）

### 1. Tenant 模型缺少套餐字段（E-B1）
**影响**：FeatureFlag 无数据源，整个三层路由架构的基石缺失
**解决**：Tenant 表新增 `package_modules JSONB` 字段
**优先级**：Phase 0 前置

### 2. JWT 签发未写入 features（E-B2）
**影响**：`get_current_user` 返回的 user dict 不含 features，`get_feature_flags` 永远返回空 dict
**解决**：修改 `security.py` + `auth_service.py`，在登录时获取套餐信息写入 JWT payload
**优先级**：Phase 0 前置

### 3. `async def __init__` 语法错误（E-B3）
**影响**：`EnergyRepository` 无法被 `get_tenant_repo` 工厂正常实例化
**解决**：改为惰性属性（`@property`）或工厂方法
**优先级**：Phase 0 前置

### 4. 缺少 aiosqlite + pyyaml 依赖（E-B4）
**影响**：独立部署模式和场景规则引擎会崩溃
**解决**：添加到 `requirements.txt`
**优先级**：Phase 0 前置

### 5. 多租户基类缺少 feature_flags 支持（E-B5）
**影响**：`repo.feature_flags = features` 无类型注解，子类需全部适配
**解决**：`MultiTenantRepository.__init__` 新增 `feature_flags` 参数
**优先级**：Phase 0 前置

### 6. 路由解析器设计 Bug：SUPPLIER 路由不可达 + 死代码（Q-B1/B2）
**影响**：`resolve(DataType.SUPPLIER, ...)` 永远返回 `MANUAL_INPUT` 而非预期的 `EXCEL_IMPORT`；第二个 for 循环永远不执行
**解决**：修 `"默认"` → `"default"`，删除死代码段
**优先级**：Phase 0 前置

### 7. 供应商模块归属未决策（PM-🔴-1）
**影响**：当前硬编码 EXCEL_IMPORT 可能全盘错误
**解决**：本周内产品+架构决策会议
**优先级**：Phase 1 启动前

### 8. 独立部署模式产品定位模糊（PM-🔴-2）
**影响**：SQLite + 硬编码密码方案可能在产品定位明确后被推翻
**解决**：确定独立部署是"演示版"、"正式单租户版"还是"离线版"
**优先级**：Phase 1 启动前

---

## 二、🟡 重要级问题汇总（8 个）

| # | 问题 | 来源 | 说明 |
|:-:|:-----|:----|:------|
| 1 | 自选套餐变更端到端体验缺失 | PM | 后端 `/refresh-features` 端点有了，但前端刷新/Token 生命周期/降级策略均未定义 |
| 2 | 6 大画像在路由设计中实质缺位 | PM | 路由是 flat flag 判断，无画像抽象层 |
| 3 | 场景规则引擎仅 3 条约束 | PM | 远不足以支撑 13 个模块间依赖 |
| 4 | 碳资产模块归属延迟 | PM | Migration 可能返工 |
| 5 | FeatureFlag 默认 False 策略的灰度问题 | PM | 存量客户扩展模块不可见 |
| 6 | JWT 注入时序耦合（E-W1） | E | `get_current_user` 和 `get_feature_flags` 的依赖链需要重构 |
| 7 | 独立部署认证密钥一致性（E-W4/Q-I3） | E+Q | `standalone_auth.py` 用 `STANDALONE_JWT_SECRET`，`get_current_user` 用 `JWT_SECRET_KEY` → 401 |
| 8 | 跨模块事务边界未确定（Q-B6） | Q | `create_alert` 联动安灯失败时 raise 还是不 raise？ |

---

## 三、🟢 关键改进建议

### 最紧急（Phase 0 可直接执行）
1. **修正 route_resolver.py bug**（"默认"→"default" + 删除死代码）
2. **搭建测试基础设施**（`tests/conftest.py` + `pytest-asyncio` + 内存 SQLite 方案）
3. **编写 DataRouteResolver 可运行代码**（纯函数，零依赖，5 分钟可产出）

### 产品侧决策（Phase 1 启动前）
4. **供应商模块归属决策会议**（本周内）
5. **独立部署模式产品定位确认**（演示版 vs 正式版）
6. **碳资产模块归属决策**（归 M11 还是独立 Mxx）
7. **套餐变更端到端体验流程设计**

### 架构设计补充
8. **引入画像驱动的路由模板**（Persona → flag 组合 → 路由策略映射）
9. **扩展场景规则约束到至少 10 条**
10. **补充模块间依赖矩阵文档**
11. **统一认证密钥方案**（消除 `STANDALONE_JWT_SECRET` vs `JWT_SECRET_KEY` 冲突）

---

## 四、工作量修正

| 项目 | 原估算 | 修正估算 | 原因 |
|:-----|:------:|:--------:|:------|
| 52 个端点迁移 | 28h | 28h（编码）| 纯编码时间不变 |
| 测试 | 未估算 | +10~12h | 32 种组合测试 + 集成测试 |
| 文档 | 未估算 | +2~3h | API 文档、迁移记录 |
| **总计** | **28h** | **~40-43h** | 增加约 50% |

---

## 五、建议的编码顺序（修正版）

```
Phase 0 — 前置准备（1-2 天）
├── [产品] 供应商归属 + 独立部署定位 + 碳资产归属 决策
├── [产品] 套餐变更端到端体验设计（与编码并行）
├── [后端] Tenant 模型新增 package_modules JSONB 字段 + Alembic 迁移
├── [后端] security.py: create_access_token 新增 features 参数
├── [后端] auth_service.py: login 时获取租户套餐写入 JWT
├── [后端] base.py: MultiTenantRepository 支持 feature_flags
├── [后端] requirements.txt: 新增 aiosqlite + pyyaml
├── [后端] 修正 route_resolver.py bug（"默认"→"default" + 删除死代码）
├── [测试] 搭建 tests/ 基础设施（conftest.py + pytest-asyncio + 场景 fixture）
└── [测试] 编写 RouteResolver 单元测试（覆盖全部 15+ 路由组合）

Phase 0.5 — 可并行编码
├── route_resolver.py（DataRouteResolver — 无依赖，可立即产出）
├── scenario_rules.yaml + scenario_engine.py
└── 独立部署认证密钥统一方案实施

Phase 1 — 核心路由改造
├── dependencies.py: get_feature_flags
├── energy_repo.py: 条件路由改造 + 集成测试
├── Energy API 端到端测试（8 个端点）
├── standalone_auth.py + 认证密钥统一
├── main.py: 独立部署分支
└── 跨模块事务测试（内存 SQLite）

Phase 2 — 后续 Sprint
├── 场景画像端到端测试（A~E 画像）
├── 迁移端点回归测试
├── 前端套餐变更体验（WebSocket/轮询 + UI 控制）
└── 新增模块的灰度发布策略
```

---

## 六、最大风险一览

| 风险 | 等级 | 说明 |
|:-----|:----:|:------|
| 独立部署认证 401 | 🔴 | 开发时无法发现，部署后才暴露 |
| SQLite vs PostgreSQL 特性差异 | 🟡 | ILIKE、array_agg、RETURNING 等在 SQLite 不可用 |
| 跨 Repo session 共享异常 | 🟡 | EnergyRepo + AndonRepo 同一 session 可能导致 DetachedInstanceError |
| 32 种组合测试膨胀 | 🟢 | 建议只覆盖有业务意义的组合 |
