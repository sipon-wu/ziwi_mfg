# 知微教学（school.ziwi.cn）账户系统对接 cloud.ziwi.cn 方案

> 版本：v0.2（草案）｜日期：2026-07-09
> 依据：
> - `cloud运营与运维/multi-product-platform-integration.md` v0.1（cloud 统一 IdP 总体说明）
> - ziwi_school 代码现状（models.go / auth_handler.go / middleware/auth.go / rbac.go / frontend api.ts）
> - `产品规划/域名规划` v2.1（定稿，school 侧对接以此为准）
> - `cloud运营与运维/blazing-pulse-turing.md`（V2.0 域名策略可执行性评估 7/10；V2.1 已吸收其主要断裂，见第 7 节）

---

## 0. 背景与目标

cloud.ziwi.cn 已定位为**统一身份与授权平台（IdP）**：统一登录、签发 RS256 JWT（含 `tenant_id` + `products[]` claims）、统管 License/Token/财务/发票；各产品线（mfg/school/...）信任 cloud JWT，**不自签**业务 token。该总体方案见 `multi-product-platform-integration.md`，其第 8 节明确列出"待 school 团队评审的问题"。

**姊妹产品线说明**：school（知微教学）与 mfg（mfg.ziwi.cn，智能制造 / 工业化生产数字化服务系统）是 cloud 旗下**同架构、不同领域**的两条产品线——两者都是 TO B（学校/制造企业租户）+ TO C（教师学生 / 一线工人与管理者）混合架构，仅业务领域不同。本方案是 school 侧对 cloud 的对接答复；mfg 侧有对应的姊妹方案，账户系统的对接契约（信任模型、租户映射、License/Token 对账）应保持一致，以便跨产品线复用 cloud 能力。

**为什么现在必须插入本方案**：ziwi_school 当前账户系统（HS256 自签 JWT + 自有 User/School 表）与 cloud 之间**没有任何对接契约**。一旦多校区（A1：同 School + CampusID）、B2C 个人版、私有部署 License 心跳等能力扩出，没有这套契约，账户系统会被反复返工。

**目标**：
1. 回答 cloud 文档第 8 节的评审问题（基于真实代码）。
2. 定义 school 侧对接契约（信任模型、用户映射、租户隔离、角色、License、Token）。
3. 给出可落地的改造清单（P0/P1/P2），对齐 cloud 文档第 7.1 节。

---

## 1. school 当前账户系统现状（证据）

### 1.1 用户模型
- `model.User`（`code/backend/internal/model/models.go:36-56`）：
  - 主键 `ID`（zw_ 前缀短 ID）、`SchoolID`（*string，学校即租户）、`Phone`（unique，登录主键）、`PasswordHash`（bcrypt）、`Role`、`Name`、`Email`、`CampusID`（多校区 A1）、`StudentNumber`、`Status`。
  - **无 `cloud_user_id` 字段**。
- `model.School`（`models.go:21-33`）：租户实体，本地字段 `LicenseExpiresAt` / `TokenQuota` / `TokenUsed` 已存在（本地 License 与 Token 配额）。

### 1.2 认证实现
- 登录（`auth_handler.go:53-114`）：手机号 + 密码（bcrypt 校验）→ 签发 **HS256** JWT。
- `generateToken`（`auth_handler.go:159-171`）：claims = `{sub: user.ID, role, school_id, name, exp(+2h), iat}`，密钥为对称 `jwtSecret`。
- 中间件 `JWTAuth`（`middleware/auth.go:11-50`）：验证 HS256，注入 `user_id / user_role / school_id` 到 context。
- 前端（`frontend/src/lib/api.ts:6-18`）：token 存 `localStorage('zhiwei_token')`；已支持 401（过期跳登录）、402/429（Token 不足弹窗）。

### 1.3 角色矩阵
- `rbac.go:40-86`：RoleMatrix 定义 8 角色，**已内置平台角色 `platform_ops` / `platform_devops`**——即 school 当前自己管理平台运营/运维账号。

### 1.4 现状小结
| 维度 | 现状 | 与 cloud 的差异 |
|------|------|----------------|
| 签名算法 | HS256（对称） | cloud 用 RS256（非对称，公钥可分发） |
| Token 语义 | `school_id` + `role` | cloud 用 `tenant_id` + `products[].roles` + `license_exp` |
| 用户标识 | `sub`=zw_ ID，`phone` 主键 | cloud 用 `sub`=UUID，`email` 匹配键 |
| 平台角色 | school 自建 `platform_ops/devops` | cloud 统管，JWT 携带 |
| License | School 本地字段 + 过期只读中间件 | cloud 权威，JWT 带 `license_exp` |
| 多租户 | School = 租户（每校一行） | cloud `tenant_id` 对应 |

---

## 2. 对 cloud 文档第 8 节"待评审问题"的回答

| # | 问题 | school 团队回答 |
|---|------|----------------|
| 1 | 用户模型 / 密码存储 | User 表见 §1.1；密码 bcrypt 哈希（`PasswordHash`）。 |
| 2 | 当前 JWT / 认证 | 自研 HS256（golang-jwt/v5），有效期 2h，无 refresh 机制（前端靠 401 重登）。与 cloud 的 RS256 + 30min access / 7d refresh 不同。 |
| 3 | 是否多租户 | 是。School 即租户（每校一行）；多校区按 A1 = 同 School + `CampusID`（非独立租户）。 |
| 4 | 迁移时间窗口 | 建议**并行期长期保留**旧登录，不强制切换；确切窗口 [待拍板]。 |
| 5 | 私有部署场景 | 是，已有私有部署路径（`api.ts` 注释：SaaS=phone / 私有=username，本地 License）。需对齐 cloud 文档 5.5 心跳上报 `heartbeat.ziwi.cn`。 |
| 6 | 技术栈 | 后端 Go + Gin + golang-jwt/v5（**支持 RS256 验证**）；前端 React + Vite + TS。对接开发无障碍。 |

---

## 3. school 侧对接契约（核心）

### 3.1 信任模型
- school **不再自签业务 JWT**；保留旧 HS256 登录作为并行期兼容通道。
- 新增 `verify_cloud_token` 中间件：验证 **RS256** 签名，信任 cloud 公钥（JWK 格式，缓存 1h，按 `kid` 选钥）。
- 中间件按 token 特征分支：带 `kid` 的 RS256 → cloud 路径；旧 HS256 → 现有路径。两路并存于并行期。

### 3.2 用户映射
- `User` 表新增 `cloud_user_id varchar(50)`（**空字段，不阻塞现有功能**）。
- 绑定规则：cloud 登录后，按 `email` 匹配 school 已有用户；无匹配则由管理员手动绑定（`cloud_user_id` 写入）。
- 业务侧仍用 school 内部 `user.ID`：收到 cloud JWT 后，用 `cloud_user_id` → 反查 school `user.ID`，再注入 context（沿用现有 `user_id` 语义）。

### 3.3 租户隔离映射
- cloud JWT `tenant_id` → school 的 `School` 实体。
- **[待拍板]** School 与 cloud 租户键：复用 `School.ID` 作为 cloud `tenant_id`，还是新增 `School.CloudTenantID` 映射字段？
- 多校区（A1）：`tenant_id` 对应 School 级；校区级 License 由 cloud `products[].license_exp` + Campus 维度承载 [待拍板具体粒度]。

### 3.4 角色映射
- cloud `products[].roles` → school RoleMatrix 角色（teacher/head_teacher/...）。
- **[待拍板]** `platform_ops` / `platform_devops`：建议改由 cloud 签发 JWT 携带，school 端识别即放行，**不再在 school 用户表建平台账号**（避免平台角色双重管理）。

### 3.5 License 校验
- 现状：`School.LicenseExpiresAt` + 过期只读中间件（拦截写操作）。
- 对接后：**优先信任 cloud JWT 的 `products[].license_exp`**；保留本地字段作私有部署/网络中断兜底。
- **[待拍板]** cloud 侧 License 变更（签发/续费/撤销）如何同步到 school：webhook 推送 vs 学校端定时心跳拉取（域名规划已有 `heartbeat.ziwi.cn`，倾向心跳）。

### 3.6 Token 配额对账
- 现有 `tokenQuotaAPI` + `School.TokenQuota/TokenUsed` 已就绪（前端 `api.ts:239-252`）。
- 对接：school 按 cloud 文档 5.1 向 cloud 上报消耗；超额由 cloud 控制或 school 本地拦截（已有 402 处理，无需改动）。

### 3.7 私有部署账户边界（关键约束）
- 私有部署（离线学校）**裁剪 cloud 依赖**：用户登录走本地轻量 IdP（username + 本地 License），**不登录 cloud.ziwi.cn，账号也不与 cloud 互通**（依据 cloud 文档 5.5 + school `api.ts` 注释：SaaS=phone / 私有=username）。
- 因此：私有部署的**非 IT 管理员业务用户（教师/学生/家长/校长等）既不应当、也无法登录 cloud.ziwi.cn**——其账号仅存在于私有部署本地库，cloud 侧无对应身份。
- 私有部署与 cloud 的关联仅为 **License 级**：本地 License 文件 + 可选 `heartbeat.ziwi.cn` 心跳上报（每天 1 次，连续 3 天失联标记）。**不是用户身份级打通**。
- IT 管理员如需在 cloud 端做 License 采购/对账/账单，应持 cloud 侧**独立开立的租户管理员账号**，与私有部署本地账号是两回事，不自动同步。
- 含义：本方案 §3.1–§3.6 的 cloud JWT 对接**仅适用于 SaaS 多租户场景**；私有部署走 §3.7 的本地 IdP 路径，两者账户边界必须清晰，否则账户系统后续会混淆。

### 3.8 私有部署 cloud 租户标准账号（= IT管理员 + 财务人员）
私有部署客户在 cloud.ziwi.cn **只需要 2 类账号**，因为 cloud 侧不承载任何业务页面，只承接 License/对账/发票/账单，业务用户全部在本地 IdP（§3.7）。据此定稿如下：

| cloud 账号角色 | 职责 | 与本地账号关系 |
|---|---|---|
| **IT 管理员**（租户 owner） | License 激活、心跳配置、`heartbeat.ziwi.cn` 对接、可增删本租户下账号、改租户设置 | 与私有部署本地 IT 管理员**独立，不自动同步**（见 §3.7） |
| **财务人员**（账单/发票子角色） | 查看账单、申请/下载发票、操作付款；**可看可操作付款，但无账号管理权** | 仅 cloud 侧存在，本地无对应身份 |

**定稿的 3 个边角决策**：
1. **租户 owner 权限归 IT 管理员**：IT 管理员即租户 owner，可管理本租户账号与设置；财务人员为仅账单/发票子角色（管不了账号）。不另设独立 owner，避免凭空多一个账号。
2. **容灾/备份管理员**：标准对外口径为"2 人"，但允许 IT 管理员再邀 **1 个备份管理员**（bus-factor 防护，防止 IT 管理员离职/失联导致 License 续费卡住）。备份管理员不计入标准 2 人口径。
3. **cloud 账号与本地账号严格独立**：这 2 个（或含备份共 3 个）cloud 账号**不**与私有部署本地 IT 管理员账号自动同步、不共享密码；财务人员的身份只存在于 cloud，本地业务库无对应行。

**多校区（A1）不影响**：cloud 租户是 per-School 维度，无论几个 CampusID，cloud 侧标准账号仍是这 2 类（per-School 一个租户），校区不单独开 cloud 账号。

---

## 4. school 侧改造清单（对齐 cloud 文档 7.1）

| 任务 | 优先级 | 复杂度 | 改动点 |
|------|:-------|:-------|:-------|
| User 表加 `cloud_user_id` | P0 | 低 | migration + model |
| School 表加 `CloudTenantID`（待 §3.3 拍板） | P0 | 低 | model + migration |
| 新增 `verify_cloud_token` 中间件（RS256 + JWK 缓存） | P0 | 中 | middleware |
| 前端增加「知微云登录」入口 | P1 | 中 | LoginPage |
| 首次 cloud 登录按 email 绑定 | P1 | 中 | auth_handler |
| 并行期保留旧 HS256 登录 | 长期 | — | 不移除 |
| 私有部署心跳对齐 `heartbeat.ziwi.cn` | P1/P2 | 中 | cron + 离线 License |
| 逐步关闭旧登录入口 | P2 | 低 | 等迁移完成 |

**不阻塞上线条件**：school 可先上"公钥获取 + cloud JWT 验证"能力，但**不强制**用户使用，对现有用户零影响（继承 cloud 7.2）。

---

## 5. 关键待拍板决策点

1. **School↔cloud 租户映射**：复用 `School.ID` 还是新增 `CloudTenantID`？
2. **License 同步机制**：webhook 推送 vs 心跳拉取（倾向心跳，域名已规划）？
3. **B2C 个人版账户归属**：由 cloud 独立库管，还是 school `User` 表加"无 SchoolID 的个人版标记"？
4. **平台角色**：`platform_ops/devops` 是否从 school 用户表剥离，纯靠 cloud JWT 识别？
5. **迁移节奏**：并行期持续多久？是否有强制切换时间窗？

---

## 6. 风险与对策（继承 cloud 文档 7.3）

| 风险 | 对策 |
|------|------|
| school 与 cloud 的 email 不匹配 | 允许管理员手动绑定 `cloud_user_id` |
| school 用户表已存在大量用户 | 增量迁移，不一次性强迁 |
| 迁移期体验下降 | 并行期保留旧登录 |
| 私有部署离线 | 本地 License 文件 + 心跳失联标记（连续 3 天未上报） |

---

## 7. 与 cloud 文档的关系

本方案即 school 团队对 `multi-product-platform-integration.md` 第 8 节的评审回答 + 落地计划。建议在该 cloud 文档第 9 节「参考文献 / 学校侧对接」补充本方案链接，形成双向引用。

另：`blazing-pulse-turing.md` 是针对早期 V2.0（`nqpf` 命名）域名策略的可执行性评估（7/10），其 4 处断裂中，断裂 1（admin 入口对等）、断裂 2（`nqpf`→`mfg` 改名）、断裂 4（`ai.ziwi.cn` 延后）已被 `域名规划` v2.1-Final 吸收。遗留的“优化 1：cloud 角色变更后全量文档同步”提示——**school 项目内若有旧文档仍把 `cloud.ziwi.cn` 当作“制造门户”，需同步修正**。本方案以 v2.1-Final（cloud = 租户服务中心）为准，不引用 `nqpf` 旧命名。
