# cloud.ziwi.cn Phase 1 — 极简 IdP 骨架 · 架构设计

> 文档类型：系统架构设计 + 任务分解
> 生成日期：2026-07-09
> 状态：方案稿，待评审
> 架构师：高见远

---

## 目录

- [1. 实现方案与框架选型](#1-实现方案与框架选型)
- [2. 文件列表](#2-文件列表)
- [3. 数据结构与接口](#3-数据结构与接口)
- [4. 程序调用流程](#4-程序调用流程)
- [5. 待明确事项](#5-待明确事项)
- [6. 所需依赖包](#6-所需依赖包)
- [7. 任务列表](#7-任务列表)
- [8. 共享知识](#8-共享知识)
- [9. 任务依赖图](#9-任务依赖图)
- [10. 部署架构简图](#10-部署架构简图)
- [11. 部署风险与检查清单](#11-部署风险与检查清单)

---

## 1. 实现方案与框架选型

### 1.1 核心难点与应对

| 难点 | 应对策略 |
|------|----------|
| RSA 密钥对管理与安全轮换 | 启动时自动检测/生成密钥，支持 kid 版本号机制，旧密钥缓存至过期 |
| 多租户 claims 的 JWT 结构 | 在 JWT payload 中嵌入 `tenant_id` + `products: [{id, roles, license_exp}]`，下游服务统一解析 |
| 公钥分发一致性 | 单一 `/public-key` 端点返回当前 + 未过期旧密钥，下游服务缓存并按 kid 选择 |
| 前后端分离部署 | Nginx 托管前端 SPA + 反向代理后端 API |

### 1.2 框架选型

| 层级 | 选型 | 理由 |
|------|------|------|
| 后端框架 | **FastAPI** | 异步原生，Pydantic 校验，自动 OpenAPI 文档，适合 IdP 场景 |
| ORM | **SQLAlchemy async** | 成熟稳健的异步 ORM，配合 asyncpg 连接 PG |
| JWT | **python-jose[cryptography]** | 支持 RS256，与 cryptography 集成良好 |
| 密码 | **passlib[bcrypt]** | 行业标准的密码哈希 |
| 前端 | **Vue 3 + TypeScript + Vite** | 轻量、类型安全、构建快速 |
| CSS | **Tailwind CSS** | 零运行时，产物极小 |
| 容器 | **python:3.13-slim + nginx:alpine** | 多阶段构建，生产镜像控制在 50MB 以内 |

### 1.3 架构模式

**后端：分层架构（Router → Service → Core → Data）**

```
API Layer (routers) → Service Layer (business logic) → Core Layer (security, crypto) → Data Layer (models, DB)
```

**前端：SPA + 路由守卫**

```
Views (Login/Register) → API Client (axios) → cloud.ziwi.cn/api/v1/auth/*
                                     ↓
                           pinia store (token)
                                     ↓
                           router.beforeEach (login guard)
```

---

## 2. 文件列表

```
cloud/
├── docker-compose.yml                          # 本地开发 + 生产编排
├── .env.example                                 # 环境变量模板
│
├── backend/
│   ├── Dockerfile                               # 多阶段构建（python:3.13-slim）
│   ├── requirements.txt                         # Python 依赖
│   ├── alembic.ini                              # 数据库迁移配置
│   ├── alembic/
│   │   └── versions/                            # 迁移脚本
│   ├── app/
│   │   ├── __init__.py
│   │   ├── main.py                              # FastAPI 入口 + 生命周期
│   │   ├── config.py                            # Settings（env → pydantic）
│   │   ├── models/
│   │   │   ├── __init__.py
│   │   │   └── user.py                          # User ORM 模型
│   │   ├── schemas/
│   │   │   ├── __init__.py
│   │   │   ├── user.py                          # User Pydantic schema
│   │   │   └── auth.py                          # LoginRequest, TokenResponse
│   │   ├── api/
│   │   │   ├── __init__.py                      # APIRouter 聚合
│   │   │   ├── auth.py                          # /api/v1/auth/* 路由
│   │   │   ├── user.py                          # /api/v1/users/* 路由
│   │   │   └── public_key.py                    # /api/v1/auth/public-key
│   │   ├── core/
│   │   │   ├── __init__.py
│   │   │   ├── security.py                      # 密码哈希 + 验证
│   │   │   ├── rsa_key_manager.py               # RSA 密钥对生成/加载/轮换
│   │   │   ├── jwt_service.py                   # JWT 签发 + 验证
│   │   │   └── database.py                      # 异步引擎 + Session 工厂
│   │   └── services/
│   │       ├── __init__.py
│   │       ├── auth_service.py                  # 注册/登录业务逻辑
│   │       └── user_service.py                  # 用户查询业务逻辑
│   └── keys/                                    # RSA 密钥存储目录（gitignore）
│       └── .gitkeep
│
├── frontend/
│   ├── Dockerfile                               # Nginx 多阶段构建
│   ├── package.json
│   ├── tsconfig.json
│   ├── vite.config.ts
│   ├── tailwind.config.ts
│   ├── postcss.config.js
│   ├── index.html
│   ├── nginx/
│   │   └── default.conf                         # Nginx 路由配置
│   ├── src/
│   │   ├── main.ts                              # Vue 入口
│   │   ├── App.vue                              # 根组件
│   │   ├── style.css                            # Tailwind 入口
│   │   ├── router/
│   │   │   └── index.ts                         # 路由配置 + 守卫
│   │   ├── stores/
│   │   │   └── auth.ts                          # Pinia auth store
│   │   ├── api/
│   │   │   └── cloud-auth.ts                    # axios + API 方法
│   │   ├── components/
│   │   │   └── AuthLayout.vue                   # 共享布局
│   │   ├── views/
│   │   │   ├── LoginView.vue                    # 登录页
│   │   │   └── RegisterView.vue                 # 注册页
│   │   └── types/
│   │       └── auth.ts                          # 前端类型定义
│   └── public/
│
└── docs/
    └── cloud-idp-architecture.md                # 本文档
```

---

## 3. 数据结构与接口

### 3.1 User 数据模型

```python
class User(Base):
    __tablename__ = "users"

    id: UUID              = Column(UUID, primary_key=True, default=uuid4)
    email: str            = Column(String(255), unique=True, nullable=False, index=True)
    password_hash: str    = Column(String(255), nullable=False)
    display_name: str     = Column(String(64), nullable=False)
    tenant_id: str | None = Column(String(64), nullable=True)      # Phase 1 可选自填
    products: list[dict]  = Column(JSONB, default=[], nullable=False)  # [{id, roles, license_exp}]
    is_active: bool       = Column(Boolean, default=True)
    is_superuser: bool    = Column(Boolean, default=False)
    created_at: datetime  = Column(DateTime(timezone=True), server_default=func.now())
    updated_at: datetime  = Column(DateTime(timezone=True), onupdate=func.now())
```

### 3.2 JWT 格式

```json
{
  "header": {
    "alg": "RS256",
    "kid": "key_v1",
    "typ": "JWT"
  },
  "payload": {
    "sub": "user-uuid",
    "email": "user@example.com",
    "tenant_id": "acme_factory",
    "products": [
      {"id": "mfg", "roles": ["tenant_admin"], "license_exp": "2026-12-31"},
      {"id": "school", "roles": ["teacher"], "license_exp": "2026-12-31"}
    ],
    "iat": 1700000000,
    "exp": 1700086400
  }
}
```

### 3.3 API 端点规范

| 方法 | 路径 | 认证 | 请求体 | 响应 | 说明 |
|:----|:-----|:----|:-------|:-----|:-----|
| POST | `/api/v1/auth/register` | 无 | `{email, password, display_name, tenant_id?}` | `201 UserResponse` | 用户注册 |
| POST | `/api/v1/auth/login` | 无 | `{email, password}` | `200 TokenResponse` | 登录，返回 JWT |
| POST | `/api/v1/auth/refresh` | 无 | `{refresh_token}` | `200 TokenResponse` | 刷新 access token |
| GET | `/api/v1/auth/me` | Bearer | — | `200 UserResponse` | 当前用户信息 |
| GET | `/api/v1/auth/public-key` | 无 | — | `200 {keys: [JWK]}` | 返回 RSA 公钥集 |
| GET | `/api/v1/users/{id}` | Bearer | — | `200 UserResponse` | 查询用户 |
| PATCH | `/api/v1/users/{id}/products` | Bearer | `{products: [...]}` | `200 UserResponse` | 更新用户产品授权 |

**响应格式：**

```python
# 成功
{"data": { ... }}

# 失败
{"detail": {"code": "ERROR_CODE", "message": "human readable"}}
```

### 3.4 类图

```text
RSAKeyManager ──管理──> KeyPairEntry []
JWTService ──使用──> RSAKeyManager
AuthService ──使用──> JWTService + User ORM
AuthRouter ──调用──> AuthService
PublicKeyRouter ──调用──> RSAKeyManager
```

---

## 4. 程序调用流程

### 4.1 登录 + JWT 签发流程

```
用户浏览器          cloud 后端              RSAKeyMgr          PostgreSQL        mfg 后端
    │                  │                      │                   │                │
    │ POST /login      │                      │                   │                │
    │ {email,password} │                      │                   │                │
    │─────────────────>│                      │                   │                │
    │                  │  SELECT user         │                   │                │
    │                  │──────────────────────────────────────────>│                │
    │                  │<───── User row ───────────────────────────│                │
    │                  │                      │                   │                │
    │                  │  verify password     │                   │                │
    │                  │  (passlib bcrypt)    │                   │                │
    │                  │                      │                   │                │
    │                  │  get_current_key()   │                   │                │
    │                  │─────────────────────>│                   │                │
    │                  │<──── key_v1_private  │                   │                │
    │                  │                      │                   │                │
    │                  │  sign JWT(RS256)     │                   │                │
    │                  │  payload: sub,       │                   │                │
    │                  │  email, tenant_id,   │                   │                │
    │                  │  products, iat, exp  │                   │                │
    │                  │                      │                   │                │
    │<───200 JWT ──────│                      │                   │                │
    │                  │                      │                   │                │
    │ 存储 token        │                      │                   │                │
    │ 跳转 mfg.ziwi.cn │                      │                   │                │
    │─────────────────────────────────────────────────────────────────────────>    │
    │                  │                      │                   │                │
    │                  │                      │   GET /public-key │                │
    │                  │                      │<──────────────────────────────────│
    │                  │                      │─── JWK keys ─────>│                │
    │                  │                      │                   │                │
    │                  │                      │                   │ mfg 验证 JWT   │
    │                  │                      │                   │ 提取 tenant_id │
    │                  │                      │                   │ 提取 products  │
```

### 4.2 密钥轮换流程

```text
Admin/Cron          RSAKeyManager            File System         PublicKey API
    │                    │                       │                    │
    │ rotate_keys()      │                       │                    │
    │───────────────────>│                       │                    │
    │                    │ generate key_v2       │                    │
    │                    │──────────────────────>│                    │
    │                    │<── saved key_v2.pem   │                    │
    │                    │                       │                    │
    │                    │ key_v1 → expired       │                    │
    │ <── new kid=key_v2 │                       │                    │
    │                    │                       │                    │
    │                    │                       │  GET /public-key   │
    │                    │                       │<────────────────────│
    │                    │ get_public_jwks()     │                    │
    │                    │──→ [key_v1(未过期),   │                    │
    │                    │     key_v2(active)]   │                    │
    │                    │                       │── JWK set ───────>│
```

---

## 5. 待明确事项

| 问题 | 现状/建议 |
|------|-----------|
| **tenant_id 全局命名规范（已决）** | 全局唯一、小写字母+数字+下划线、长度 ≤ 40；**前缀区分产品线**：`mfg_`（制造）/ `sch_`（教育）/ `ai_`（AI赋能）/ `fin_`（财税审计），后续新产品线追加前缀；例：`mfg_acme`、`sch_hope`。Phase 1 仍为注册时自填，但必须校验前缀+格式，否则注册拒绝；Phase 2 改为平台分配 + 管理员审核。理由：mfg 先建租户若用自由文本，school 后建必撞车，跨产品线统一租户视图建不起来 |
| **products 数据来源？** | Phase 1 默认为空数组 `[]`，通过预留的 PATCH `/api/v1/users/{id}/products` 接口手动录入，或 Phase 2 对接管理后台 |
| **cloud 前端 Docker 部署方式？** | 采用 **Nginx 托管静态文件** 方案：Vite 构建产物输出到 `dist/`，Nginx 多阶段构建中 COPY |
| **refresh token 存储策略？** | Phase 1 存 localStorage，Phase 2 改 httpOnly cookie + CSRF Token |
| **同一邮箱多 tenant 场景？** | Phase 1 不做 — email 唯一约束，一个用户一个 tenant |

---

## 6. 所需依赖包

### 后端（`requirements.txt`）

```
fastapi>=0.110.0          # Web 框架
uvicorn[standard]>=0.29.0 # ASGI 服务器
sqlalchemy[asyncio]>=2.0  # 异步 ORM
asyncpg>=0.29.0           # PostgreSQL 异步驱动
alembic>=1.13.0           # 数据库迁移
python-jose[cryptography]>=3.3.0  # JWT + RSA
passlib[bcrypt]>=1.7.4    # 密码哈希
pydantic[email]>=2.7.0    # 数据验证
pydantic-settings>=2.2.0  # 环境变量管理
python-multipart>=0.0.9   # FastAPI form 解析
```

### 前端（`package.json`）

```json
{
  "dependencies": {
    "vue": "^3.4.0",
    "vue-router": "^4.3.0",
    "pinia": "^2.1.0",
    "axios": "^1.7.0"
  },
  "devDependencies": {
    "typescript": "^5.4.0",
    "vite": "^5.2.0",
    "@vitejs/plugin-vue": "^5.0.0",
    "tailwindcss": "^3.4.0",
    "postcss": "^8.4.0",
    "autoprefixer": "^10.4.0",
    "vue-tsc": "^2.0.0"
  }
}
```

---

## 7. 任务列表

### T01：项目基础设施 + 后端骨架

| 字段 | 值 |
|:-----|:-----|
| **Task ID** | T01 |
| **名称** | 项目基础设施 + 后端骨架 |
| **优先级** | P0 |
| **依赖** | 无（初始任务） |

**文件：** `docker-compose.yml`, `Dockerfile`, `requirements.txt`, `main.py`, `config.py`, `core/database.py`

**验收：** `docker-compose up` 启动 FastAPI + PostgreSQL；`GET /health` 返回 ok

---

### T02：数据层（User 模型 + 迁移 + Schema）

| 字段 | 值 |
|:-----|:-----|
| **Task ID** | T02 |
| **名称** | 数据层：User 模型 + 迁移 + Schema |
| **优先级** | P0 |
| **依赖** | T01 |

**文件：** `models/user.py`, `schemas/user.py`, `schemas/auth.py`, `alembic.ini`, 迁移脚本

**验收：** 迁移创建 `users` 表；Pydantic schema 校验通过；products 默认 `[]`

---

### T03：核心安全层（RSA + JWT + 密码）

| 字段 | 值 |
|:-----|:-----|
| **Task ID** | T03 |
| **名称** | 核心安全层：RSA 密钥管理 + JWT + 密码哈希 |
| **优先级** | P0 |
| **依赖** | T01 |

**文件：** `core/rsa_key_manager.py`, `core/jwt_service.py`, `core/security.py`

**验收：** 首次启动自动生成密钥对；可签发/验证 RS256 JWT；公钥导出 JWK；旧密钥轮换兼容

---

### T04：API 端点 + 业务服务层

| 字段 | 值 |
|:-----|:-----|
| **Task ID** | T04 |
| **名称** | API 端点 + 业务服务层 |
| **优先级** | P0 |
| **依赖** | T02, T03 |

**文件：** `services/auth_service.py`, `services/user_service.py`, `api/auth.py`, `api/public_key.py`, `api/user.py`

**验收：**
- `POST /register` → 201 / 409
- `POST /login` → 200 + JWT / 401
- `GET /auth/me` → UserResponse / 401
- `GET /public-key` → JWK Set
- `POST /refresh` → 新 access_token

---

### T05：Vue 3 前端 SPA

| 字段 | 值 |
|:-----|:-----|
| **Task ID** | T05 |
| **名称** | Vue 3 前端：登录页 + 注册页 + 路由守卫 |
| **优先级** | P1 |
| **依赖** | T01（仅需 API 存在） |

**文件：** 前端完整文件树（12+ 源文件）

**验收：** 未登录重定向到 `/login`；登录提交 → 存 token → 跳转；注册提交 → 跳登录页；token 过期 → 自动跳回；Docker build 成功

---

## 8. 共享知识

```
- 所有 API 响应格式：成功 → {data: ...}，失败 → {detail: {code, message}}
- JWT 通过 Bearer 传递：Authorization: Bearer <token>
- 所有时间以 ISO 8601 UTC 存储和传输
- RSA 密钥存储在 backend/keys/，.pem 格式，永远不提交 Git
- kid 命名规则：key_v1, key_v2, key_v3...
- 前端 localStorage 存 access_token（短期），Phase 2 改 httpOnly cookie
- PostgreSQL 连接字符串通过 DATABASE_URL 环境变量注入
- 本地开发端口：backend=8000, frontend=5173, db=5432
- 部署时 Nginx 托管前端 SPA + 反向代理 /api/* → FastAPI
```

---

## 9. 任务依赖图

```text
T01 (项目基础设施)
 ├── T02 (数据层)
 │    └── T04 (API + 服务层) ← 依赖 T03
 ├── T03 (核心安全层) ──────┘
 └── T05 (前端 SPA)
```

---

## 10. 部署架构简图

```text
用户浏览器 (cloud.ziwi.cn)
    │ HTTPS
    ▼
Nginx (443) ─── 静态文件 ─── Vue SPA (dist/)
    │ /api/* 反向代理
    ▼
FastAPI Uvicorn (:8000) ─── PostgreSQL (:5432)
    │ /api/v1/auth/public-key
    ▼
mfg.ziwi.cn 后端 (验证 JWT)    school.ziwi.cn 后端 (验证 JWT)
```

---

## 11. 部署风险与检查清单

| 优先级 | 风险点 | 现状 | 对策 | 负责人 |
|:------|:-------|:-----|:-----|:-------|
| 高 | 私钥轮换运维 SOP 缺失 | 代码已支持 kid 双 key 并存（见 §4.2 密钥轮换流程），但缺运维 SOP——何时 rotate、回滚步骤、旧 kid 保留时长未定义 | 部署前实测一次 `rotate_keys`，验证 `/public-key` 同时返回 key_v1+key_v2 且旧 token 仍可验过；补一份轮换运维 SOP | 主理人 |
| 高 | 单点无监控 | Phase 1 无平台监控 | 上线至少配 `/health` 探活 + 基础 uptime 告警（如 uptime-kuma 或腾讯云告警），否则 cloud 挂了 mfg/school 全部无法登录 | mfg 团队 |
| 底线 | 密钥安全 | RS256 私钥需 volume/secret 挂载、不进镜像、不提交 Git、需备份；§8 只说"不提交 Git"，缺备份要求 | 备份到独立密钥保险库或离线介质，记录恢复步骤 | mfg 团队 |
| 中 | Phase 1 能力边界 | License 只能靠 `PATCH /api/v1/users/{id}/products` 手动配，无可视化后台（License 采购/对账/开票 UI 在 Phase 2） | 需提前知会 mfg 团队，别把上线节奏押在 Phase 1 | 主理人 |
| 中 | tenant_id 全局命名规范 | 见 §5，已决 | 按 §5 已决规范执行（前缀+格式校验） | 主理人 |
| 中 | 同机多 PostgreSQL 内存 | 193.112.163.147 上已有 school 的 postgres 容器，再加 cloud-db 需确认内存余量 | 部署前 `free -h` 检查内存余量，否则 OOM 可能拖垮 school | mfg 团队 |
| 中 | 生产 DATABASE_URL | docker-compose 内后端应连 `cloud-db:5432`（容器网络服务名），非 `localhost:5432`；.env 配错会导致 cloud 起得来但连不上库 | 后端连接串使用容器网络服务名 `cloud-db:5432`，部署前核对 .env | mfg 团队 |

> **新增独立服务提醒**：`heartbeat.ziwi.cn` 是一个**全新的独立服务**，不在 cloud Phase 1 任务 T01–T05 范围内。私有部署实例能上报心跳前，必须先把它建出来（接收端点 + 独立容器 + 独立 SSL 证书）。负责人：mfg 团队 / 主理人（待定）。
