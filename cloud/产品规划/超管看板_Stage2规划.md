# 知微统一身份 · 超级管理员看板（Stage 2）产品规划

> 目标：超级管理员（platform / super_admin）通过 cloud.ziwi.cn 掌握**全局运营数据**，支持**自助改密**，且**移动优先自适应**（超管多用手机网页查看操作）。
> 范围：仅 cloud 控制台（IdP），不涉及 school/mfg/heartbeat 业务数据。
> 纪律：克制优先——不引入重型图表库/UI 框架，看板数据走单一聚合端点。

---

## 一、信息架构

`/console` 当前是「账号管理 / 我的工单 / 新增资源 / 系统配置」四 Tab。本期把**运营总览看板**设为 `/console` 默认首屏，并补「设置（改密）」入口：

| 入口 | 内容 | 优先级 |
|---|---|---|
| **总览（看板）** | 全局 KPI + 趋势 + 分布 + 安全 | P0 |
| 账号管理 | 既有（stage1 已做） | 保留 |
| 我的工单 | 既有 License 工单 | 保留 |
| 新增资源 | 既有业务线 | 保留 |
| **设置** | 修改密码、登出 | P0（本期新增） |

移动端导航：**底部 Tab 栏**（总览 / 账号 / 工单 / 我的）；桌面端：**顶部 Tab + 左/顶栏**。当前 AdminConsole 用 scoped CSS，无 UI 框架，维持克制不加框架。

---

## 二、看板数据维度（运营数据统计）

### A. 核心 KPI 卡（顶部一排，移动端 2 列网格）
- 租户用户总数（活跃 / 停用）
- 平台账号数（按角色：super_admin / operator）
- 业务线开通数（education / manufacturing）
- 当前有效会话数（未 revoke 的 refresh token）
- 待处理 License 工单数

### B. 用户与增长
- **注册趋势**（近 7 / 30 天，按 `users.created_at` 按日聚合）→ 折线（内联 SVG）
- **业务线用户分布**（各 `product` code 下用户数）→ 占比条
- **活跃度**（活跃 vs 停用占比）→ 环形（CSS conic-gradient）

### C. 全量工单统计（所有工单类型，一屏掌握）
- **工单总数** + 按状态分布（待支付 / 待审批 / 已通过 / 已驳回 / 已完成）→ 条形/漏斗
- **按类型构成**（新建 / 续费）
- **按产品线分布**（education / manufacturing / …）→ 占比条
- **工单趋势（分时）**：近 7 / 30 天按日聚合的工单量折线（申请量随时间变化，识别业务高峰）
- **临期提醒列表**（按 `requested_expires_at` 在未来 30 / 60 / 90 天）→ 高优列表，超管掌握续费节奏

### D. 安全与登录
- **登录趋势**（近 7 / 30 天，按 `refresh_token_records.issued_at` 聚合）→ 折线
- **安全事件**（近 7 天 `replay_detected` / `revoked` token 数）→ 告警卡
- **异常监测**（同 JTI 复用命中 replay 标记）→ 列表/角标

### E. Token 购销（实时数据 + 分时统计）⭐
> 「购」= 租户申请/支付 License（事件时间 `created_at`）；「销」= 平台审批通过/发放（`approved_at`）。
> 以工单数为计量单位；若需金额/席位价值，需在 `license_tickets` 增加 `requested_seats` / `amount` 字段（列 P2 扩展，不阻塞本期）。

- **实时数据（当前态，看板加载即刷新，可选轮询）**：
  - 今日购（今日新申请/支付工单数）
  - 今日销（今日审批通过/发放工单数）
  - 当前待处理（status ∈ 待支付/待审批）
  - 当前有效授权数（status ∈ 已通过/已完成 且 `requested_expires_at` > 现在）
- **分时统计（双线：购 vs 销）**：
  - **小时级（今日 24h）**：逐小时购/销工单数 → 识别日内高峰
  - **日级（近 30 天）**：逐日购/销工单数 → 看板趋势主线
  - 形态：双线折线（内联 SVG），移动端可纵滑；附「购-销」净额角标

---

## 三、数据可得性评估（证据驱动）

| 维度 | 来源 | 状态 |
|---|---|---|
| 租户用户 / 平台账号 / 业务线 / 全量工单 | 现有表全覆盖 | ✅ 直接可得 |
| 注册趋势 / 业务线分布 / 活跃度 | `users.created_at` / `products` / `is_active` | ✅ 直接可得 |
| 全量工单趋势（分时） | `license_tickets.created_at` 按日聚合 | ✅ 直接可得 |
| **Token 购销** | 购=`created_at`、销=`approved_at`、有效授权=`requested_expires_at` 未过期 | ✅ 直接可得 |
| **Token 购销 分时** | 按 `created_at` / `approved_at` 做小时(今日)/日(30d) `group by` | ✅ 直接可得 |
| 有效会话数 / 登录趋势 | `refresh_token_records` | ⚠️ 近似可得（仅含走 refresh 的会话，不含纯 access token 调用；不含失败登录） |
| 登录成功率 / 失败原因 / 实时在线 | 无审计表 | ❌ 缺失，列 P2 |

**结论**：本期看板用现有表 + refresh token 近似即可覆盖全部 P0 维度；精确的「登录成功率 / 失败审计 / 实时在线」需新增 `auth_events` 表，列为 **P2**，不阻塞本期。

---

## 四、超管自助改密（新增能力）

**后端**：新增 `POST /api/v1/auth/change-password`
- Body：`{ old_password, new_password }`
- 逻辑：按当前 JWT 身份（platform / tenant 通用）取用户 → `verify_password` 校验旧密 → 失败返回 **422 具体原因**（沿用 stage1 统一错误拦截，不吞错）→ 通过则 `hash_password` 重设
- **安全**：改密成功后将该用户所有 `refresh_token_records` 置 `revoked=true`，强制重新登录（前端收到 401 跳登录页）

**前端**：「设置」Tab / 顶部头像菜单 → 修改密码弹层（旧 / 新 / 确认三字段；移动端全屏表单，≥44px 触控）。复用 `cloud-auth.ts` 错误解析，旧密错时原位提示。

---

## 五、后端接口设计（单一聚合，避免 N+1）

新增两个端点（均需 platform JWT）：

1. `GET /api/v1/platform/stats`
   返回看板全部数据（一次性聚合）：
   ```json
   {
     "kpi": { "tenant_users": N, "tenant_active": N, "platform_users": N,
              "business_lines": N, "active_sessions": N, "open_tickets": N },
     "user_growth": { "7d": [...], "30d": [...] },
     "by_product": [ { "code": "education", "name": "知微教育", "users": N }, ... ],
     "activity": { "active": N, "inactive": N },
     "license": { "by_status": {...}, "by_type": {"new":N,"renewal":N},
                  "expiring": [ { "id", "company", "product", "expires_at", "days_left" }, ... ] },
     "tickets": { "total": N, "by_status": {...}, "by_type": {"new":N,"renewal":N},
                  "by_product": [ { "product": "education", "count": N }, ... ],
                  "trend": { "7d": [...], "30d": [...] } },
     "token_trade": {
        "realtime": { "buy_today": N, "sell_today": N, "pending": N, "active_licenses": N },
        "by_hour": [ { "hour": "00", "buy": N, "sell": N }, ... ],
        "by_day":  [ { "date": "2026-07-28", "buy": N, "sell": N }, ... ]
     },
     "login_trend": { "7d": [...], "30d": [...] },
     "security": { "replay_7d": N, "revoked_7d": N }
   }
   ```
   实现：几组 `select count(*)` / `group by` 聚合查询（asyncpg），一次返回。

2. `POST /api/v1/auth/change-password`（见第四节）

---

## 六、移动自适应（重点）

- **移动优先**：默认单列堆叠；KPI 卡移动端 2 列网格；图表在手机降级为「横向可纵滑」或简化形态。
- **断点**：`≤768px` 手机单列 + 底部 Tab；`769–1024px` 平板双列；`≥1025px` 桌面多列 + 顶/侧栏。
- **触控友好**：按钮/可点项 ≥44px；表格在手机转为卡片列表（每行一卡）。
- **图表零依赖**：KPI 卡纯 CSS；趋势线用内联 SVG `polyline`（前端据数据点算坐标）；环形用 CSS `conic-gradient`；条形用 flex + 高度百分比。不引入 echarts/antv 等重型库。
- **技术约束**：维持 scoped CSS + media query，不引入 UI 框架（克制纪律）。

---

## 七、落地步骤（待拍板实现顺序）

1. 后端：`GET /api/v1/platform/stats` 聚合端点（含 P0 全部维度：全量工单统计 + Token 购销实时/分时 + 登录趋势用 refresh 近似）
2. 后端：`POST /api/v1/auth/change-password`（旧密校验 + 重设 + revoke token）
3. 前端：`/console` 看板视图（KPI 卡 + SVG/CSS 自绘图表 + 临期/安全列表）
4. 前端：改密弹层 + 改密后 revoke 跳登录
5. 响应式：底部 Tab + 三档断点适配
6. 真浏览器 e2e（含手机视口 375px）验证看板渲染 + 改密闭环

---

## 八、克制提醒（工作纪律）

- 不引入重型图表库 / UI 框架；看板自绘 SVG/CSS。
- 看板走单一聚合端点，杜绝 N+1。
- 高价值信息优先：临期工单、安全事件先做；登录成功率精确统计（P2）不阻塞本期。
- 部署走固化链路：`push → rsync /opt/cloud-idp → docker compose up -d --build`；上线前本地真浏览器 e2e（含手机视口）全绿。
