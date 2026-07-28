# Heartbeat 技术对接文档（INTEGRATION）

> **以当前运行代码为准**（部署于 `heartbeat.ziwi.cn`，预发布容器 2026-07-28 实测）。
> 早期设计稿中描述的机器端事件流 / 状态轮询 / 机器清单 / License 激活等 API **当前未实现**，
> 完整缺口见文末「§7 未实现清单」。本文档即为权威对接参考。

---

## 1. 基础信息

| 项 | 值 |
|----|----|
| Base URL | `https://heartbeat.ziwi.cn` |
| 健康检查 | `GET /health` → `200 {"status":"ok"}` |
| 后端 | FastAPI + SQLAlchemy + SQLite，容器 `heartbeat-backend` 监听 `:8091` |
| 模板 | 服务端 Jinja2 渲染（后台 UI 非 SPA） |

---

## 2. 鉴权模型

系统有两类调用方，**鉴权方式不同**：

### 2.1 机器端（部署实例上报心跳）
- 通过 HTTP Header 携带：`X-Api-Key: <HEARTBEAT_API_KEY>`
- Key 与 `settings.api_key`（环境变量 `HEARTBEAT_API_KEY`）比对，不符 → `401 Invalid API key`。

### 2.2 管理端（后台 UI / 运维脚本）
- 登录：`POST /admin/login`（form: `username`, `password`）→ 下发签名会话 Cookie `hb_session`。
- 会话：HMAC-SHA256 签名，8h 过期，HttpOnly；生产应启用 `Secure`（见 §6 配置项）。
- 页面级：未登录访问 `/admin/*` → `303` 跳 `/admin/login`；已登录但无该页权限 → `303` 跳首个有权限页面。
- API 级：`401` 未认证 / `403` 权限不足（fail-closed）。

---

## 3. 机器端 API

### `POST /api/v1/heartbeat`
鉴权：`X-Api-Key`（必填）。

**请求体**
```json
{
  "tenant_id": "string (必填, 租户标识)",
  "product": "string (必填, 如 mfg / school / cloud)",
  "version": "string (可选, 部署版本)",
  "status": "string (可选)",
  "license_status": "string (可选, 服务端不采信客户端自报)",
  "license_expires_at": "ISO8601 (可选)",
  "details": "object (可选, 自由结构)"
}
```

**服务端行为**
1. 按 `(tenant_id, product)` 查 `License`；不存在则**自动建一条 `status=none`**（需管理员后台激活）。
2. 更新 `License.last_seen` / `last_version` / `heartbeats += 1`。
3. 按 `(tenant_id, product)` 查/建 `Deployment`，置 `status=online`、`last_heartbeat_at=now`、`consecutive_misses=0`。
4. 后台定时任务（间隔 `check_interval_minutes`）扫描：超过 `heartbeat_timeout_minutes` 无心跳 → `status=offline`。

**响应** `200`
```json
{ "status": "ok", "license_status": "<none|trial|active|expired|revoked|...>" }
```

> ⚠️ **已知约束**：当前 `License.tenant_id` 为单列唯一，同一租户仅支持**单一 product**。多 product 租户第二次上报会触发唯一约束冲突（500）。修复中（见产品规格 §6）。

---

## 4. 管理端 API（均须登录会话；权限不足 → 403）

| 方法 | 路径 | 说明 | 所需权限 |
|------|------|------|----------|
| GET | `/api/v1/admin/licenses` | 授权列表 | `license_view` |
| POST | `/api/v1/admin/licenses` | 创建授权（tenant+product 已存在则 409） | `license_manage` |
| PUT | `/api/v1/admin/licenses` | 更新授权（tenant+product 不存在则 404） | `license_manage` |
| DELETE | `/api/v1/admin/licenses?tenant_id=&product=` | 删除授权 | `license_manage` |
| GET | `/api/v1/admin/audit` | 授权变更审计 | `audit` |
| GET | `/api/v1/admin/admin-audit` | 账号/权限变更审计 | `audit` |
| GET | `/api/v1/admin/deployments` | 部署实例列表 | `deployments` |
| GET | `/api/v1/admin/alerts` | 告警列表（离线/临界分级） | `alerts` |
| POST | `/api/v1/admin/check` | 手动触发离线巡检 | `deployments` |
| GET | `/api/v1/admin/users` | 用户列表 | `users` |
| POST | `/api/v1/admin/users` | 创建用户（含角色/额外权限校验、越权防护） | `users` |
| PUT | `/api/v1/admin/users/{id}` | 更新用户（末位超管锁、自操作限制） | `users` |
| DELETE | `/api/v1/admin/users/{id}` | 删除用户（末位超管锁、自操作限制） | `users` |

> 注：`/api/v1/admin/roles`、`/api/v1/admin/settings` 配置端点**当前未实现**；角色目录为服务常量（见 §5）。

### 关键字段
- **License**：`tenant_id, product, status(none|trial|active|expired|revoked), issued_at, expires_at, licensee, seats, notes, last_seen, last_version, heartbeats`
- **Deployment**：`deployment_id, tenant_id, product, version, license_issued_at, license_expires_at, last_heartbeat_at, status(online|offline), consecutive_misses`
- **AdminUser**：`id, username, display_name, role, roles[], role_labels, extra_permissions[], effective_permissions[], is_active, created_at, last_login_at`

---

## 5. 管理端页面（服务端渲染）

`/admin`（仪表盘）· `/admin/licenses` · `/admin/customers` · `/admin/deployments` ·
`/admin/alerts` · `/admin/audit` · `/admin/users` · `/admin/settings`(占位) · `/admin/support`(占位)

未登录 → `/admin/login`；无权限页 → `303` 跳首权页。

### RBAC 模型（权威）
- **角色**：`super_admin`(超级管理员) / `ops`(运营) / `sales`(销售) / `finance`(财务) / `support`(实施, 占位)
- **权限点**：`dashboard, license_view, license_manage, deployments, alerts, customers(客户管理：含主数据 CRUD), audit, users, settings`
- **有效权限** = 角色权限并集 + 直接额外授权
- **安全**：末位超管锁（409）/ 越权防护（403）/ 暴力破解锁定 / 签名无状态会话 / 双审计链（`license_audit` + `admin_audit`）

---

## 6. 配置项（环境变量，见 `.env.example`）

| 变量 | 说明 |
|------|------|
| `HEARTBEAT_API_KEY` | 机器端上报密钥（**生产必须修改默认值**） |
| `HEARTBEAT_ADMIN_USERNAME` / `HEARTBEAT_ADMIN_PASSWORD` | 初始超管凭据 |
| `HEARTBEAT_SESSION_SECRET` | 会话签名密钥（未设则回退 admin_password，生产须设强随机值） |
| `HEARTBEAT_ADMIN_SECURE_COOKIE` | 会话 Cookie 是否启 Secure（HTTPS 部署应设 `true`） |
| `HEARTBEAT_DB_URL` | SQLite 路径，默认 `sqlite:///./data/heartbeat.db` |
| `HEARTBEAT_CHECK_INTERVAL_MINUTES` | 后台离线巡检间隔 |
| `HEARTBEAT_HEARTBEAT_TIMEOUT_MINUTES` | 超时判定阈值（超过即 offline） |
| `HEARTBEAT_LOGIN_MAX_ATTEMPTS` / `HEARTBEAT_LOGIN_LOCKOUT_MINUTES` | 暴力破解防护参数 |

---

## 7. 未实现清单（对照早期设计稿）

以下能力在早期设计稿中出现，**当前代码未实现**，仅供产品规划参考：

- 部署事件流上报：`POST /api/v1/events`、`POST /api/v1/events/batch`
- 部署状态轮询：`GET /api/v1/status`
- 机器实例清单：`GET /api/v1/machines`、`POST /api/v1/machines/heartbeat`
- 机器端 License 激活/评估/刷新：`/api/v1/license/activate`、`/evaluate`、`/info`、`/refresh`
- 机器端系统设置：`GET/POST /api/v1/settings`
- 管理员端 角色/设置 配置 API：`/api/v1/admin/roles`、`/api/v1/admin/settings`
- 指标 / 导出（CSV）：`/api/v1/admin/metrics`、`/api/v1/admin/exports/licenses`

---

## 8. 部署

见 `deploy/deploy.sh`：docker compose 构建 `heartbeat-backend` → 健康检查 `/health` → 复用 `*.ziwi.cn` 通配符证书落盘 nginx → reload。
建议 uptime-kuma 监控 `https://heartbeat.ziwi.cn/health`（5min 间隔）。
