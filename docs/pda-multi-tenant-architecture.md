# PDA 多租户部署架构评估

> **文档编号**：ZIWI-ARCH-PDA-MT-v1.0  
> **评估人**：Bob（架构师 / 高见远）  
> **评估日期**：2026-06-18  
> **背景问题**：产品负责人提出"PDA的安装包对于每个租户都是独立提供和打包的，不知架构设计中是否能满足"  
> **前置文档**：`product-functional-specification.md`、`wms/m20-wms-spec.md`、`architecture-comprehensive-review.md`、`extensibility-design.md`、`backend/app/core/config.py`

---

## 目录

1. [当前架构快照](#1-当前架构快照)
2. [三种多租户部署方案评估](#2-三种多租户部署方案评估)
   - [方案A：单 APK + 租户登录切换（标准 SaaS 模式）](#方案a单-apk--租户登录切换标准-saas-模式)
   - [方案B：多 APK（按租户白标打包）](#方案b多-apk按租户白标打包)
   - [方案C：独立部署（每个租户独立后端+独立 PDA）](#方案c独立部署每个租户独立后端独立-pda)
3. [方案综合对比](#3-方案综合对比)
4. [架构补充设计建议](#4-架构补充设计建议)
5. [推荐方案详细设计](#5-推荐方案详细设计)
6. [FAQ](#6-faq)

---

## 1. 当前架构快照

### 1.1 租户隔离体系（当前已实现）

| 隔离层次 | 实现方式 | 当前状态 |
|:--------:|:---------|:--------:|
| **L1 基础设施** | K8s Namespace / DB Schema | ⚠️ 预留，未启用（当前单库模式） |
| **L2 基础数据** | 租户-组织-用户-角色 独立管理 | ✅ 已实现 |
| **L3 业务数据** | `tenant_id` 行级自动注入（MultiTenantRepository） | ✅ 已实现 |
| **L4 数据作用域** | 组织级/部门级/个人级细粒度权限（DataScopeService） | ⚠️ v2 设计中 |

### 1.2 当前 PDA 交互架构

```
┌─────────────────────────────────────────────────┐
│                 PDA 手持终端                      │
│   ┌───────────────────────────────────────┐      │
│   │  未单独构建 PDA App                     │      │
│   │  当前 PDA 功能仅在 WMS 产品规格中定义       │      │
│   │  实际移动端能力通过 Vant 组件库在前端 SPA 中 │      │
│   └───────────────────────────────────────┘      │
│            │ HTTPS + JWT + X-Tenant-Id            │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│              API Layer                            │
│  /api/v1/{resource} → Depends(get_current_user)   │
│  JWT (sub + tenant_id + features)                 │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│           Service Layer                           │
│  WMS Service (入库/出库/盘点/移库/查询/批次)       │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│         Repository Layer                          │
│  MultiTenantRepository (自动注入 tenant_id)        │
│  Raw SQL (参数化绑定)                              │
└──────────────┬──────────────────────────────────┘
               │
┌──────────────▼──────────────────────────────────┐
│       Database (SQLite/PostgreSQL)                │
│  所有表均含 tenant_id 字段 + 行级隔离              │
└─────────────────────────────────────────────────┘
```

### 1.3 当前前端技术栈

| 维度 | 技术选型 | 说明 |
|:-----|:---------|:------|
| 框架 | Vue 3 + Vite | 前端 SPA |
| UI 组件库 | Vant 4（移动端优先） | 当前 admin 前端已使用移动端组件库 |
| 状态管理 | Pinia | auth store 管理 JWT 和租户上下文 |
| HTTP 客户端 | Axios | 自动注入 `Authorization: Bearer` + `X-Tenant-Id` |
| 认证 | JWT | token 中含 tenant_id 上下文；login 接口支持 `tenant_id` 参数 |
| 包管理 | npm + package.json | 单构建配置 |

### 1.4 当前认证/租户上下文流程

```
用户登录
  │
  ▼
POST /api/v1/auth/login { username, password, tenant_id? }
  │
  ▼
后端校验 → 生成 JWT (sub + tenant_id + features + exp)
  │
  ▼
前端存储: localStorage { access_token, refresh_token, tenant_id, user_info }
  │
  ▼
每次 API 请求:
  Axios interceptor → 自动注入
    Header: Authorization: Bearer <token>
    Header: X-Tenant-Id: <tenant_id>
  │
  ▼
后端:
  Depends(get_current_user) → 解析 JWT → 提取 tenant_id
  MultiTenantRepository → 所有 SQL 自动拼接 WHERE tenant_id=?
```

---

## 2. 三种多租户部署方案评估

---

### 方案A：单 APK + 租户登录切换（标准 SaaS 模式）

#### 方案描述

所有租户使用同一 PDA 安装包。PDA 启动时展示租户选择页（或通过租户专属域名自动识别），用户输入用户名/密码后，系统通过 JWT token 携带 `tenant_id` 上下文，所有后端操作自动隔离。

#### 当前架构支持度：✅ **直接支持**

**评估理由**：

| 架构维度 | 支持情况 | 说明 |
|:---------|:--------:|:------|
| **认证流程** | ✅ 直接支持 | Login 接口已支持 `tenant_id` 参数；JWT 已内嵌 `tenant_id` |
| **租户隔离** | ✅ 直接支持 | MultiTenantRepository 自动注入 `tenant_id`，行级隔离无需修改 |
| **X-Tenant-Id** | ✅ 直接支持 | Axios interceptor 已实现自动注入 |
| **后端 API** | ✅ 直接支持 | 所有 WMS API（收货/拣料/盘点/移库/查询）均通过标准 API + tenant 隔离 |
| **数据模型** | ✅ 直接支持 | 所有 WMS 表均含 `tenant_id` 字段 |
| **离线缓存** | ✅ 支持 | PDA 本地 SQLite 存储时以 `tenant_id` 区分租户数据即可 |
| **白标需求** | ⚠️ 不支持 | 所有租户看到相同的 App 图标/名称/品牌色 |

#### 需要新增的配置

| 配置项 | 类型 | 说明 | 优先级 |
|:-------|:----:|:------|:------:|
| PDA 专属前端项目 | 代码 | 新建 `frontend/pda/` 独立 Vite 项目，使用 Vant 构建 6 大 PDA 功能页面 | P0 |
| 租户选择页面 | UI | 登录页增加租户选择/输入（域名/租户代码），或通过部署域名自动识别 | P0 |
| 离线缓存隔离 | 代码 | PDA 本地 IndexedDB/SQLite 按 `tenant_id` 分区存储 | P1 |
| 后台 API URL 配置 | 配置 | 构建时固定 API base_url 或运行时通过配置文件读取 | P1 |

#### CI/CD 影响

| 影响项 | 说明 |
|:-------|:------|
| **构建流水线** | 单条流水线，构建一次，产出 1 个 APK |
| **应用商店分发** | 全球/全客户使用同一包名，通过 Google Play / 企业分发 |
| **版本管理** | 单一版本号（v1.0.0），所有租户自动升级 |
| **热修复** | 修复一次，所有租户受益 |
| **分支策略** | 主分支 + release 分支，无多租户分支 |

#### 推荐度：⭐⭐⭐⭐⭐（强烈推荐，知微默认方案）

**理由**（结合知微云 SaaS 定位：50-150人中小制造企业）：

| 维度 | 评估 |
|:-----|:------|
| **适配 SaaS 定位** | ✅ 完全契合 SaaS 标准模式，"一次构建，服务所有客户" |
| **运维成本** | 极低 — 只需要维护 1 条流水线、1 个 APK、1 套版本 |
| **开发成本** | 最低 — 只需新建 PDA 前端项目，后端无改动，前端改动极小 |
| **升级体验** | 最优 — 新版本发布后所有租户自动受益，无需逐个通知升级 |
| **租户体验** | 良好 — 输入账号即自动识别租户，无需额外操作 |
| **白标需求** | 不满足 — 所有租户共享同一品牌外观 |
| **离线能力** | 可行 — 本地缓存按 `tenant_id` 分区即可 |

**结论**：方案A是知微云 SaaS 的**最佳默认方案**。PDA 作为租户用户端的一部分，通过 JWT 中的 `tenant_id` 自动切换上下文，后端 MultiTenantRepository 提供天然的行级隔离，整体架构完全支持且无需重大改造。

---

### 方案B：多 APK（按租户白标打包）

#### 方案描述

同一代码仓库，CI/CD 构建时传入租户参数（租户代码、品牌色、图标、服务器地址、包名等），每个租户产出独立的 APK。代码层面 100% 共享，仅构建配置不同。

#### 当前架构支持度：⚠️ **需少量调整**

**评估理由**：

| 架构维度 | 支持情况 | 说明 |
|:---------|:--------:|:------|
| **代码复用** | ✅ 支持 | 同一仓库，构建时传入参数，代码零修改 |
| **白标能力** | ⚠️ 需新增 | 需要新增 `tenant_brand_config` 配置表和前端构建时的白标插件 |
| **API 地址** | ⚠️ 需新增 | 每个租户的 PDA 需要指向正确的后端地址（或使用统一 API Gateway） |
| **CI/CD** | ⚠️ 需重大调整 | 单流水线 → 多流水线（每个租户一条）或矩阵构建 |
| **租户隔离** | ✅ 直接支持 | 后端不变，MultiTenantRepository 依然生效 |
| **认证** | ✅ 直接支持 | JWT 不变，PDA 登录后可固定 tenant_id 不允许切换 |
| **版本管理** | ⚠️ 复杂化 | 多 APK = 多版本号，需要跟踪每个租户的构建版本 |

#### 需要新增的配置

| 配置项 | 类型 | 说明 | 优先级 |
|:-------|:----:|:------|:------:|
| **`tenant_brand_config` 表** | 数据库 | 存储每个租户的白标配置：app_name、primary_color、logo_url、icon_url、splash_screen | P0 |
| **白标构建脚本** | 代码/CI | `scripts/build-tenant.sh --tenant=<code>` 读取租户配置后执行构建 | P0 |
| **前端主题切换插件** | 代码 | Vite 插件在构建时注入品牌变量（`$brand-primary`、`$brand-secondary`） | P0 |
| **Android/iOS 资源生成** | CI | 构建时自动替换 App 图标、启动屏、应用名称 | P1 |
| **包名/证书管理** | CI | 每个租户独立 package name（`com.ziwi.pda.<tenant_code>`），独立签名证书 | P1 |
| **PDA 配置下发 API** | 后端 | `GET /api/v1/pda/config` 返回当前租户的白标配置（启动时从服务端拉取） | P1 |
| **租户独立更新通道** | 部署 | 每个租户有独立的更新检查 URL / 二维码下载页 | P2 |

#### CI/CD 影响

| 影响项 | 说明 |
|:-------|:------|
| **构建策略** | 从"1条流水线"变为"矩阵构建"：每新增一个租户，CI 中新增一个构建参数组合 |
| **构建频率** | 每次代码提交触发 N 次构建（N=活跃租户数），随租户增长线性膨胀 |
| **构建时间** | 假设 50 个租户，每次构建需要 50 × 单次构建时间 |
| **制品管理** | 需要为每个租户保留独立的 APK 归档和历史版本 |
| **发布策略** | 无法统一发布，需按租户逐个发布（或通过 MDM/企业分发按租户推送） |
| **版本追踪** | 需要记录每个租户当前运行的 APK 版本号，管理升级时间窗口 |

#### 推荐度：⭐⭐（低 — 不推荐作为默认方案）

**理由**：

| 维度 | 评估 |
|:-----|:------|
| **适配 SaaS 定位** | ❌ 偏离 SaaS 模式，更接近"私有化部署"的操作方式 |
| **运维成本** | 极高 — 50 个租户 = 50 条构建 = 50 个 APK 需管理 |
| **开发成本** | 中 — 白标构建脚本 + 配置表开发约 3-5 天 |
| **升级体验** | 差 — 每次升级需要为每个租户构建、测试、分发，升级周期显著拉长 |
| **租户体验** | 好 — 每个租户看到自己的品牌信息 |
| **适用场景** | 仅面向有强烈白标需求的**大客户**（≥ 500 人企业），而非中小制造企业 |

**结论**：方案B**技术上可行**，但与知微云 SaaS 的标准化运营模式存在根本性冲突。对于 50-150 人的中小制造企业，白标 PDA 的价值远低于运维复杂度增加的成本。**仅在以下条件同时满足时考虑**：
1. 客户明确要求 PDA 展示其自有品牌
2. 客户愿意为白标支付额外费用
3. 客户数量 ≤ 5 家白标客户

---

### 方案C：独立部署（每个租户独立后端+独立 PDA）

#### 方案描述

每个租户拥有独立的数据库、独立域名、独立部署的 PDA 后端服务和独立构建的 PDA APK。实现 L1 基础设施级别的完全隔离。

#### 当前架构支持度：⚠️ **需少量调整（架构预留）**

**评估理由**：

| 架构维度 | 支持情况 | 说明 |
|:---------|:--------:|:------|
| **后端隔离** | ⚠️ 需少量调整 | 当前数据库层支持 SQLite/PostgreSQL，K8s Helm Chart 支持多实例部署，需参数化租户配置 |
| **数据库隔离** | ✅ 支持 | 切换 `DB_DRIVER=postgresql` + 独立 `DB_NAME` 即可，或使用 SQLite 文件级隔离 |
| **域名隔离** | ⚠️ 需新增 | 需要租户域名管理（`<tenant>.ziwi.cloud` 或自定义域名）+ Nginx/Ingress 配置 |
| **PDA 构建** | ⚠️ 需少量调整 | 复用方案B的白标构建逻辑，再加每个租户独立构建 |
| **租户隔离** | ✅ 完全满足 | L1 基础设施级隔离，最高安全级别 |
| **CI/CD** | ⚠️ 需重大扩展 | 需要租户部署流水线 + 基础设施即代码（IaC） |

#### 需要新增的配置

| 配置项 | 类型 | 说明 | 优先级 |
|:-------|:----:|:------|:------:|
| **租户部署模板** | IaC | K8s Helm Chart 参数化模板（`values-tenant-<code>.yaml`） | P0 |
| **租户域名管理** | 基础设施 | 自动签发 SSL 证书、配置 Ingress/DNS、租户子域名分配 | P0 |
| **租户数据库自动创建** | 自动化 | 租户开通时自动创建独立数据库并执行 DDL 迁移 | P0 |
| **租户部署触发** | CI | 每次代码变更触发所有租户的重新部署（或按租户选择性部署） | P1 |
| **监控告警** | 基础设施 | 每个租户的独立监控（Pod 状态 / DB 连接 / API 响应时间） | P1 |
| **备份策略** | 基础设施 | 每个租户独立备份策略和恢复演练 | P1 |
| **PDA 构建与分发** | CI | 每个租户独立构建 APK + 分发二维码页面 | P1 |

#### CI/CD 影响

| 影响项 | 说明 |
|:-------|:------|
| **部署流水线** | 1条CI流水线构建 + N条CD流水线部署（N=独立部署租户数） |
| **环境数量** | 每个租户 = 1套生产环境 + 1套预发布环境 |
| **资源消耗** | 线性增长：50个租户 = 50倍的服务器/数据库/存储成本 |
| **升级节奏** | 无法统一升级，需逐个租户灰度 + 验证 + 发布 |
| **运维团队** | 从"1人维护SaaS平台"到"N倍平台运维工作量" |

#### 推荐度：⭐（极低 — 仅限私有化部署场景）

**理由**：

| 维度 | 评估 |
|:-----|:------|
| **适配 SaaS 定位** | ❌ 完全背离 SaaS 模式，回归到传统私有化部署 |
| **运维成本** | 极高 — 50 个租户 = 管理 50 套独立系统 |
| **资源成本** | 极高 — 50 个租户 = 50 倍的基础设施成本（不共享任何资源） |
| **开发成本** | 中 — Helm Chart 参数化 + 部署自动化约 5-7 天 |
| **升级体验** | 最差 — 逐个租户升级，耗时且易出错 |
| **租户体验** | 最好 — 完全隔离，定制化程度最高 |
| **适用场景** | ⚠️ 仅限：① 有数据合规要求（如涉密/军工/金融）；② 客户主动要求私有化部署并承担成本；③ 单租户规模 ≥ 500 人 |

**结论**：方案C**技术上可行**（当前架构已有基础设施隔离的预留设计），但与知微云 SaaS 的核心定位完全不匹配。对 50-150 人中小制造企业而言，独立部署的成本和复杂度远超客户愿意支付的价格。

---

## 3. 方案综合对比

| 维度 | 方案A：单APK | 方案B：多APK白标 | 方案C：独立部署 |
|:-----|:------------:|:----------------:|:---------------:|
| **当前架构支持度** | ✅ 直接支持 | ⚠️ 需少量调整 | ⚠️ 需少量调整 |
| **后端改动** | 无需改动 | 无需改动 | 新增部署模板 |
| **前端/PDA 改动** | 新建 PDA 项目（~5 天） | 新增白标构建框架（~5 天） | 复用方案B |
| **白标能力** | ❌ 不支持 | ✅ 支持 | ✅ 完全支持 |
| **租户隔离级别** | L3 行级 | L3 行级 | L1 基础设施级 |
| **运维复杂度** | ⭐（低） | ⭐⭐⭐（高） | ⭐⭐⭐⭐⭐（极高） |
| **基础设施成本** | ⭐（1份） | ⭐（1份，共享后端） | ⭐⭐⭐⭐⭐（N份） |
| **升级便利性** | ✅ 一次发布全量升级 | ⚠️ 逐个租户构建+分发 | ❌ 逐个租户升级 |
| **离线缓存方案** | 按 tenant_id 分区 | 无需分区（单租户） | 无需分区（单租户） |
| **开发工作总量** | **5-7 天** | **8-12 天** | **15-25 天** |
| **推荐度（知微 SaaS）** | ⭐⭐⭐⭐⭐ | ⭐⭐ | ⭐ |
| **推荐条件** | ✅ **默认方案** | 仅限 ≤5 个白标大客户 | 仅限私有化部署合同 |

---

## 4. 架构补充设计建议

### 4.1 现有架构不足之处的识别

通过本次多租户 PDA 部署分析，发现以下当前架构的不足和需要补充的设计：

| # | 不足项 | 影响 | 建议补充设计 |
|:-:|:-------|:-----|:------------|
| 1 | **PDA 专用前端项目缺失** | 当前 admin SPA 使用 Vant 组件库，但 PDA 功能（收货上架/拣料下架/盘点/移库/查询）**仅有产品规格定义，无前端实现**。PDA 需要构建为独立的移动端应用，不能复用 PC admin 的页面布局 | 新建 `frontend/pda/` 独立 Vite + Vue 3 + Vant 项目 |
| 2 | **无租户配置下发 API** | 方案B需要 PDA 启动时获取租户品牌配置（Logo/颜色/名称），当前后端没有提供此接口 | 新增 `GET /api/v1/pda/config` 返回当前租户的基础配置和白标信息 |
| 3 | **离线缓存策略未实现** | WMS 规格中定义了 PDA 离线缓存需求（本地 SQLite/IndexedDB），但当前架构中前端没有统一的离线数据管理层 | 设计 PDA 离线数据层 `PdaOfflineStorage`（基于 IndexedDB），支持按 `tenant_id` 分区的数据缓存 |
| 4 | **无 PDA 专属 API** | 当前所有 PDA 操作通过通用 API 执行，但 PDA 场景需要更精简的响应数据、更好的错误提示、以及特定的批量操作接口 | 考虑新增 `/api/v1/pda/` API 前缀，封装 PDA 专用的批量/精简接口（可选，当前通过通用 API 也可行） |
| 5 | **缺少租户品牌配置表** | 方案B和方案C需要 `tenant_brand_config` 表存储白标配置，当前 `tenants` 表缺少品牌相关字段 | 在租户开通流程中增加品牌配置阶段，存储到扩展表或 `ext_attrs` |
| 6 | **无统一版本管理策略** | 多 APK 模式下，版本管理复杂化。当前没有考虑 PDA 客户端版本的兼容性管理机制 | 设计 PDA 版本兼容策略：后端 API 版本化 + 客户端最低版本校验 |
| 7 | **PDA 扫码支持的条码类型** | WMS 规格定义了 5 种条码类型（物料/库位/批次/单据/工单），但后端条码解析逻辑未实现 | 新增 `POST /api/v1/pda/scan` 接口：接收条码内容，自动识别类型并返回对应的业务数据 |

### 4.2 推荐补充设计清单（优先级排序）

| 优先级 | 补充设计 | 工作量 | 作用 |
|:------:|:---------|:------:|:-----|
| **P0** | 新建 `frontend/pda/` 独立 PDA 前端项目 | 3-5 天 | PDA 功能实现的基础 |
| **P0** | 实现 PDA 6 大功能页面（收货上架/拣料下架/盘点/移库/查询/批次查询） | 5-8 天 | PDA 核心功能 |
| **P1** | PDA 离线缓存层（IndexedDB + 同步队列） | 2-3 天 | 离线操作能力 |
| **P1** | `GET /api/v1/pda/config` 租户配置下发 API | 0.5 天 | 支持白标配置 |
| **P2** | `tenant_brand_config` 表 + 租户品牌配置管理 | 1-2 天 | 白标扩展基础 |
| **P2** | `POST /api/v1/pda/scan` 扫码解析接口 | 1 天 | 统一扫码入口 |
| **P3** | PDA API pda 专用 API 前缀（`/api/v1/pda/`） | 1-2 天 | 性能优化 |

---

## 5. 推荐方案详细设计

### 5.1 推荐方案：方案A（单 APK + 租户登录切换）

#### 5.1.1 架构图

```
┌──────────────────────────────────────────────────────────────────┐
│                    PDA 手持终端（单 APK）                          │
│  ┌────────────────────────────────────────────────────────┐      │
│  │  租户A仓库员 → 在 PDA 登录（用户名+密码+租户自动识别）      │      │
│  │  租户B仓库员 → 在 PDA 登录（用户名+密码+租户自动识别）      │      │
│  │                                                          │      │
│  │  离线策略：本地 IndexedDB 按 tenant_id 分区存储            │      │
│  │  同步策略：在线实时提交 API | 离线队列 + 断点续传            │      │
│  └────────────────────────────────────────────────────────┘      │
│            │ HTTPS + JWT (tenant_id 内嵌)                         │
└──────────────┬───────────────────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────────────┐
│                    API Gateway / Nginx                            │
│  统一入口: https://api.ziwi.cloud                                │
│  路由规则: /api/v1/{resource} → 后端服务                         │
└──────────────┬───────────────────────────────────────────────────┘
               │
┌──────────────▼───────────────────────────────────────────────────┐
│                ziwi SaaS 后端（共享实例）                          │
│                                                                   │
│  JWT 解析 → tenant_id → MultiTenantRepository → 行级隔离         │
│                                                                   │
│  ┌──────────────────────────────────────────────────────────┐    │
│  │  PDA 专用 API（可选）：                                     │    │
│  │  POST /api/v1/pda/scan            ← 扫码解析              │    │
│  │  GET  /api/v1/pda/config          ← 租户配置下发           │    │
│  │  POST /api/v1/pda/sync            ← 离线数据同步            │    │
│  └──────────────────────────────────────────────────────────┘    │
│                                                                   │
│  共享数据库（单实例）                                             │
│  所有表：tenant_id 行级隔离                                      │
└──────────────────────────────────────────────────────────────────┘
```

#### 5.1.2 前端 PDA 项目结构

```
frontend/pda/
├── package.json                  # 依赖声明（vue, vant, axios, dayjs）
├── vite.config.ts                # Vite 构建配置
├── tsconfig.json                 # TypeScript 配置
├── index.html                    # 入口 HTML
├── public/
│   ├── favicon.ico               # 通用图标
│   └── ziwi-logo.png             # 知微品牌 Logo
├── src/
│   ├── main.ts                   # 应用入口
│   ├── App.vue                   # 根组件（含登录状态判断）
│   ├── router/
│   │   └── index.ts              # 路由定义
│   ├── stores/
│   │   ├── auth.ts               # 认证状态（复用 admin 模式）
│   │   └── pda.ts                # PDA 操作状态（当前仓库/当前任务）
│   ├── api/
│   │   ├── client.ts             # Axios 实例（复用 X-Tenant-Id 注入）
│   │   ├── wms.ts                # WMS API 封装
│   │   └── pda.ts                # PDA 专用 API
│   ├── composables/
│   │   ├── useScanner.ts         # 扫码解析逻辑
│   │   ├── useOffline.ts         # 离线缓存 + 同步队列
│   │   └── usePdaOperation.ts    # PDA 操作通用逻辑（扫码→确认→提交）
│   ├── utils/
│   │   ├── offline-storage.ts    # IndexedDB 离线存储
│   │   └── sync-engine.ts        # 离线同步引擎（断点续传/冲突处理）
│   ├── pages/
│   │   ├── login/
│   │   │   └── LoginPage.vue     # 登录页（含租户自动识别）
│   │   ├── home/
│   │   │   └── HomePage.vue      # PDA 首页（6 大功能按钮）
│   │   ├—— receiving/            # PDA-01 收货上架
│   │   │   ├── TaskList.vue      # 待收货任务列表
│   │   │   ├── ScanReceive.vue   # 扫码收货
│   │   │   └── ScanPutaway.vue   # 扫码上架
│   │   ├── picking/              # PDA-02 拣料下架
│   │   │   ├── TaskList.vue      # 待拣料任务列表
│   │   │   ├── PickNavigate.vue  # 拣料导航
│   │   │   └── ScanPick.vue      # 扫码确认下架
│   │   ├── counting/             # PDA-03 库存盘点
│   │   │   ├── TaskList.vue      # 待盘点任务列表
│   │   │   └── ScanCount.vue     # 扫码盘点
│   │   ├── transfer/             # PDA-04 库存移库
│   │   │   └── TransferForm.vue  # 移库操作页
│   │   ├── inquiry/              # PDA-05 库存查询
│   │   │   ├── MaterialQty.vue   # 扫码查库存
│   │   │   └── LocationQty.vue   # 库位库存查询
│   │   └── batch/                # PDA-06 批次查询
│   │       └── BatchQty.vue      # 扫码查批次
│   └── styles/
│       └── pda-theme.css         # PDA 主题样式（Vant 定制）
```

#### 5.1.3 PDA 登录认证流程（含租户自动识别）

```
PDA 启动
  │
  ▼
检查 localStorage 是否有缓存的 auth token
  ├── 有效 → 验证 token 有效性（GET /api/v1/auth/me）
  │            ├── 有效 → 进入首页
  │            └── 过期 → 显示登录页
  │
  └── 无 token → 显示登录页
                   │
                   ▼
           用户输入：用户名 + 密码
                  （可选的：租户代码/域名）
                   │
                   ▼
           POST /api/v1/auth/login
           { username, password, tenant_id? }
                   │
                   ▼
           成功后，JWT 包含 tenant_id
           localStorage { access_token, tenant_id, user_info }
                   │
                   ▼
           进入 PDA 首页 HomePage.vue
           展示 6 大功能按钮
```

#### 5.1.4 离线数据隔离策略

```typescript
// 离线存储按 tenant_id 分区的设计

interface PdaOfflineStore {
  tenant_id: string;
  // 字典数据（启动时全量拉取，按租户隔离）
  materials: MaterialCache[];
  locations: LocationCache[];
  batches: BatchCache[];
  // 操作队列（离线时暂存，在线时提交）
  operationQueue: PdaOperation[];
  // 同步状态
  lastSyncAt: string;
  syncVersion: number;
}

// IndexedDB 中按 tenant_id 建库
// DB name: `ziwi_pda_${tenant_id}`
// 每个租户独立数据库，物理隔离
```

#### 5.1.5 关键 API 封装

```typescript
// api/pda.ts — PDA 专用 API 封装

// 扫码解析接口
export async function scanBarcode(code: string): Promise<ScanResult> {
  return post('/pda/scan', { barcode: code });
  // 返回: { type: "material"|"location"|"batch"|"receipt"|"issue"|"count",
  //          data: {...}, label: "物料编码: RAW-001" }
}

// 租户配置下发
export async function getPdaConfig(): Promise<PdaConfig> {
  return get('/pda/config');
  // 返回: { app_name, primary_color, logo_url, warehouse_list,
  //         offline_sync_interval, max_offline_days }
}

// 离线数据同步
export async function syncOfflineData(operations: PdaOperation[]): Promise<SyncResult> {
  return post('/pda/sync', { operations, last_sync_at });
  // 返回: { success_count, fail_count, failed_items, server_version }
}
```

### 5.2 方案B补充设计（如需白标）

#### 5.2.1 租户品牌配置表

```sql
-- 租户品牌配置表（扩展 tenant 表）
CREATE TABLE tenant_brand_configs (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    tenant_id         VARCHAR(64) NOT NULL UNIQUE,
    app_name          VARCHAR(128) NOT NULL DEFAULT '知微WMS',     -- 应用显示名称
    primary_color     VARCHAR(32) NOT NULL DEFAULT '#1677ff',      -- 主色（Hex）
    secondary_color   VARCHAR(32) NOT NULL DEFAULT '#52c41a',       -- 辅色
    logo_url          VARCHAR(256),                                 -- Logo URL
    icon_url          VARCHAR(256),                                 -- App 图标 URL
    splash_screen_url VARCHAR(256),                                 -- 启动屏 URL
    package_name      VARCHAR(128),                                 -- Android package name
    ios_bundle_id     VARCHAR(128),                                 -- iOS bundle ID
    server_base_url   VARCHAR(256) NOT NULL,                        -- 后端服务地址
    is_active         INTEGER DEFAULT 1,
    created_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at        TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

#### 5.2.2 白标构建脚本

```bash
#!/bin/bash
# scripts/build-tenant-pda.sh — 按租户构建 PDA APK
# 用法: ./build-tenant-pda.sh --tenant=T001

set -e

# 解析参数
for arg in "$@"; do
  case $arg in
    --tenant=*) TENANT_CODE="${arg#*=}";;
  esac
done

if [ -z "$TENANT_CODE" ]; then
  echo "错误: 请指定租户代码 --tenant=<code>"
  exit 1
fi

echo "▶ 开始构建租户 $TENANT_CODE 的 PDA APK..."

# 1. 从 API 获取租户品牌配置
TENANT_CONFIG=$(curl -s -H "X-Admin-Key: $ADMIN_API_KEY" \
  "$CONFIG_SERVICE_URL/api/v1/admin/tenants/$TENANT_CODE/brand-config")

# 2. 注入品牌变量到 Vite env
export VITE_APP_NAME=$(echo $TENANT_CONFIG | jq -r '.app_name')
export VITE_PRIMARY_COLOR=$(echo $TENANT_CONFIG | jq -r '.primary_color')
export VITE_APP_LOGO_URL=$(echo $TENANT_CONFIG | jq -r '.logo_url')
export VITE_API_BASE_URL=$(echo $TENANT_CONFIG | jq -r '.server_base_url')
export VITE_TENANT_CODE=$TENANT_CODE

# 3. 替换 App 图标和启动屏
# (使用 ImageMagick/Sharp 将 tenant 图标缩放到各尺寸)

# 4. 执行构建（Vite 读取 env 变量注入主题）
cd frontend/pda
npm run build -- --mode tenant

# 5. 重命名输出产物
mv dist/apk/release/app-release.apk "dist/apk/release/ziwi-pda-${TENANT_CODE}-v${VERSION}.apk"

echo "✅ 租户 $TENANT_CODE PDA APK 构建完成"
```

---

## 6. FAQ

### Q1：当前架构到底能不能支持每个租户独立 PDA 安装包？

**能。** 当前架构的多租户设计（JWT + MultiTenantRepository + 行级隔离）直接为多租户 PDA 场景提供了基础设施。无论选择哪种方案，后端都不需要修改。

- 方案A（默认推荐）：**直接支持**，后端无改动，仅需新建 PDA 前端项目
- 方案B（白标）：**需少量调整**，新增品牌配置表 + 白标构建脚本
- 方案C（独立部署）：**需少量调整**，新增部署模板，后端代码无改动

### Q2：如果先做方案A，以后要切换到方案B或方案C，需要多少改造？

**方案A → 方案B**：在方案A的 PDA 前端基础上，增加构建时品牌注入插件 + 租户品牌配置表即可。预计 **3-5 天**。PDA 前端代码无需重写。

**方案A → 方案C**：需要增加 K8s 多实例部署 + 租户域名管理。预计 **5-7 天**。PDA 前端代码无需重写。

**结论**：方案A是最安全的起点，与方案B/C之间不存在"架构重构"级别的鸿沟，均为增量扩展。

### Q3：如果客户有 5 个仓库，每个仓库使用不同的 PDA 配置？

这属于**单租户内多仓库**的场景，不是多租户问题。当前架构已支持：
- 用户登录时选择/默认分配仓库（PDA 首页顶部显示当前仓库）
- 所有操作关联 `warehouse_id`，仓库切换在应用层完成
- 不需要多 APK

### Q4：方案A中，一个租户的数据会被其他租户看到吗？

**不会。** 安全体系保障：

| 防护层 | 机制 | 绕过难度 |
|:-------|:-----|:--------:|
| JWT 认证 | token 中包含 `tenant_id`，篡改即失效 | 极高（HS256 签名） |
| MultiTenantRepository | 所有 SQL 自动拼接 `WHERE tenant_id=?` | 极高（参数化绑定，SQL注入防护） |
| X-Tenant-Id 校验 | 后端校验 JWT 中的 tenant_id 与请求 header 一致 | 高 |
| 字段名白名单 | UPDATE/DELETE 操作校验字段名白名单 | 高 |

### Q5：初始 PDA 开发需要多长时间？

| 阶段 | 工作内容 | 工作量 |
|:-----|:---------|:------:|
| 新建 PDA 前端项目 | package.json, vite.config, router, stores, api | 0.5 天 |
| 登录页 + 首页（6大功能按钮） | LoginPage.vue, HomePage.vue | 0.5 天 |
| 6 大 PDA 功能页面 | 收货上架/拣料下架/盘点/移库/查询/批次查询 | 5-8 天 |
| 离线缓存 + 同步引擎 | IndexedDB + sync-engine | 2-3 天 |
| 扫码解析 | useScanner + scan API | 0.5 天 |
| 测试 + 联调 | 端到端验证 | 1-2 天 |
| **总计** | | **10-15 天** |

### Q6：推荐方案A对于知微 SaaS 业务模式的战略意义？

方案A完美契合知微云 SaaS 的核心理念：

> **"一次构建，服务所有客户"**

- PDA 作为知微云 SaaS 的标准化终端，所有租户共享同一安装包
- 租户通过登录自动切换上下文，无需管理多个 APK 版本
- 后端零改动，前端构建 PDA 独立项目，风险最低
- 升级维护成本最低，适合 50-150 人中小制造企业的快速扩展

---

> **最终结论**：当前架构完全支持多租户 PDA 部署。**推荐使用方案A（单 APK + 租户登录切换）**，新建独立 PDA 前端项目 `frontend/pda/`，复用现有 JWT 认证和 MultiTenantRepository 的租户隔离机制，后端无需任何改动。方案B和方案C作为可选扩展路径，在出现特定客户需求时可在方案A基础上增量实现。
