# cloud.ziwi.cn JWT 集成指南

> **版本**: v1.0  
> **面向读者**: school（教学平台）/ mfg（制造平台）后端开发者  
> **最后更新**: 2026-07-10

---

## 1. 概况

cloud.ziwi.cn 是知微（Ziwi）多产品 SaaS 平台的统一身份 IdP（Identity Provider）。所有下游产品（school、mfg 等）的用户认证均通过 cloud.ziwi.cn 完成——用户在 cloud 注册/登录后获得 JWT access_token，下游后端通过验签该 token 识别用户身份，无需各自维护独立的用户系统。

认证流核心：下游后端从 HTTP Header 提取 Bearer Token → 从 cloud 获取 JWKS 公钥 → RS256 验签 → 解析 claims（user_uuid、email、tenant_id、products）→ 注入当前请求上下文。

---

## 2. 公钥获取

### 2.1 端点

```
GET https://cloud.ziwi.cn/api/v1/auth/public-key
```

**无鉴权**，直接返回 JWKS 格式公钥。

### 2.2 响应格式

```json
{
  "data": {
    "keys": [
      {
        "kty": "RSA",
        "kid": "key_v1",
        "n": "0vx7aq...（Base64URL 编码的 RSA 模数）",
        "e": "AQAB",
        "use": "sig",
        "alg": "RS256"
      }
    ]
  }
}
```

| 字段 | 说明 |
|:---|:---|
| `kty` | 密钥类型，固定 `RSA` |
| `kid` | 密钥 ID，JWT Header 中的 `kid` 必须与此匹配 |
| `n` | RSA 公钥模数（Base64URL 编码） |
| `e` | RSA 公钥指数，`AQAB` = 65537 |
| `use` | 用途，`sig` 表示签名 |
| `alg` | 算法，`RS256` |

### 2.3 缓存策略

| 策略 | 推荐值 | 说明 |
|:---|:---|:---|
| TTL | **1 小时** | 公钥轮换后，1 小时内全集群生效 |
| 降级 | **本地文件兜底** | 请求 cloud 失败时 fallback 到上次缓存的公钥文件 |
| 刷新 | **被动 + 主动** | 正常情况 TTL 过期后重新拉取；验签遇到 `kid` 不匹配立即强制刷新 |

```python
# 伪代码：缓存逻辑
import httpx
import json
from pathlib import Path

JWKS_URL = "https://cloud.ziwi.cn/api/v1/auth/public-key"
CACHE_FILE = Path("/tmp/cloud_jwks.json")
CACHE_TTL_SECONDS = 3600

async def get_jwks() -> dict:
    """获取 JWKS，优先缓存，失败降级到本地文件"""
    # 1. 检查内存缓存是否有效
    if _memory_cache and (now() - _cache_time) < CACHE_TTL_SECONDS:
        return _memory_cache
    # 2. 请求 cloud
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            resp = await client.get(JWKS_URL)
            resp.raise_for_status()
            data = resp.json()["data"]
            _memory_cache = data
            _cache_time = now()
            CACHE_FILE.write_text(json.dumps(data))  # 写本地备份
            return data
    except Exception:
        # 3. 降级到本地文件
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
        raise  # 无缓存则抛异常
```

### 2.4 kid 匹配规则

JWT Header 中的 `kid` 字段（当前为 `"key_v1"`）必须与 JWKS 返回的 `keys[].kid` 精确匹配。验签时使用匹配的 key，若无匹配则视为验签失败，**立即触发 JWKS 强制刷新**后重试一次。

---

## 3. JWT 验证（核心）

### 3.1 Token 结构

```
Header.Payload.Signature
```

**Header**（Base64URL 解码后）：
```json
{"alg": "RS256", "kid": "key_v1", "typ": "JWT"}
```

**Payload**（Base64URL 解码后）：
```json
{
  "sub": "80f19c6c-...",        // 用户 UUID
  "email": "user@ziwi.cn",
  "tenant_id": null,             // 租户 ID（当前未启用多租户）
  "products": [],                // 用户订阅的产品列表
  "iat": 1752076800,             // 签发时间（Unix 时间戳）
  "exp": 1752078600              // 过期时间（Unix 时间戳）
}
```

### 3.2 Claims 说明

| Claim | 类型 | 必填 | 说明 |
|:---|:---|:---|:---|
| `sub` | `str` (UUID) | ✅ | 用户唯一标识，对应 user.uuid |
| `email` | `str` | ✅ | 用户邮箱 |
| `tenant_id` | `str \| null` | ✅ | 租户 ID，当前为 null（预留多租户） |
| `products` | `list[str]` | ✅ | 用户订阅的产品列表，如 `["school","mfg"]` |
| `iat` | `int` | ✅ | 签发时间（Unix timestamp） |
| `exp` | `int` | ✅ | 过期时间（Unix timestamp），当前 `iat + 1800`（30 分钟） |

### 3.3 RS256 验签流程

#### 3.3.1 安装依赖

```bash
pip install python-jose[cryptography] httpx
# 或
pip install pyjwt[crypto] httpx
```

#### 3.3.2 完整验签代码（python-jose）

```python
"""
school/mfg 后端 JWT 验证模块
依赖: pip install python-jose[cryptography] httpx
"""
import json
import time
from pathlib import Path
from functools import lru_cache

import httpx
from jose import jwt, JWTError, ExpiredSignatureError, JWTClaimsError
from jose.constants import Algorithms

# ─── 配置 ─────────────────────────────────────────────
JWKS_URL = "https://cloud.ziwi.cn/api/v1/auth/public-key"
JWKS_CACHE_FILE = Path(__file__).parent / ".cloud_jwks_cache.json"
JWKS_CACHE_TTL = 3600      # 秒
JWKS_FETCH_TIMEOUT = 5.0   # 秒
EXPECTED_ALGORITHM = Algorithms.RS256
EXPECTED_AUDIENCE = None   # cloud 当前未设置 aud
CLOCK_SKEW_SECONDS = 30    # 允许的时钟偏差


# ─── JWKS 获取（带缓存 + 降级）────────────────────────
class JWKSStore:
    """线程不安全的轻量 JWKS 缓存"""

    def __init__(self):
        self._keys: dict[str, dict] = {}
        self._fetched_at: float = 0.0

    def is_valid(self) -> bool:
        return bool(self._keys) and (time.monotonic() - self._fetched_at < JWKS_CACHE_TTL)

    def find_key(self, kid: str) -> dict | None:
        return self._keys.get(kid)

    async def fetch(self) -> dict[str, dict]:
        """从 cloud 拉取 JWKS，失败时降级到本地文件"""
        try:
            async with httpx.AsyncClient(timeout=JWKS_FETCH_TIMEOUT) as client:
                resp = await client.get(JWKS_URL)
                resp.raise_for_status()
                keys_list = resp.json()["data"]["keys"]
                self._keys = {k["kid"]: k for k in keys_list}
                self._fetched_at = time.monotonic()
                # 写本地备份
                JWKS_CACHE_FILE.write_text(json.dumps(keys_list))
                return self._keys
        except Exception:
            # 降级：读本地缓存
            if JWKS_CACHE_FILE.exists():
                keys_list = json.loads(JWKS_CACHE_FILE.read_text())
                self._keys = {k["kid"]: k for k in keys_list}
                return self._keys
            raise RuntimeError("无法获取 JWKS 且无本地缓存") from None

    async def refresh(self) -> dict[str, dict]:
        """强制刷新（kid 不匹配时调用）"""
        self._fetched_at = 0.0  # 使缓存失效
        return await self.fetch()


# 全局单例
_jwks_store = JWKSStore()


async def get_signing_key(kid: str) -> dict:
    """根据 kid 获取对应的 JWK"""
    if not _jwks_store.is_valid():
        await _jwks_store.fetch()
    key = _jwks_store.find_key(kid)
    if key is None:
        # kid 不匹配 → 强制刷新后重试
        await _jwks_store.refresh()
        key = _jwks_store.find_key(kid)
        if key is None:
            raise JWTError(f"未知的 kid: {kid}")
    return key


# ─── Token 验证 ───────────────────────────────────────
async def verify_access_token(token: str) -> dict:
    """
    验证 access_token 并返回 payload claims。
    
    Raises:
        ExpiredSignatureError: token 已过期
        JWTClaimsError: claims 不合法
        JWTError: 签名/格式无效
    """
    # 1. 解析 Header 获取 kid（不验签）
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise JWTError("无法解析 JWT Header")

    kid = unverified_header.get("kid")
    if not kid:
        raise JWTError("JWT Header 缺少 kid")

    # 2. 获取对应公钥
    jwk = await get_signing_key(kid)

    # 3. RS256 验签 + claims 校验
    payload = jwt.decode(
        token,
        jwk,
        algorithms=[EXPECTED_ALGORITHM],
        audience=EXPECTED_AUDIENCE,
        options={
            "require": ["sub", "email", "exp", "iat"],
            "verify_exp": True,
            "verify_iat": True,
        },
        leeway=CLOCK_SKEW_SECONDS,
    )

    return payload


# ─── 错误类型映射 ─────────────────────────────────────
from enum import Enum

class TokenVerifyError(str, Enum):
    EXPIRED = "TOKEN_EXPIRED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    MALFORMED = "MALFORMED_TOKEN"
    UNKNOWN_KID = "UNKNOWN_KID"
    JWKS_UNAVAILABLE = "JWKS_UNAVAILABLE"


def classify_jwt_error(exc: Exception) -> TokenVerifyError:
    """将 JWT 异常映射为业务错误码"""
    if isinstance(exc, ExpiredSignatureError):
        return TokenVerifyError.EXPIRED
    if isinstance(exc, JWTClaimsError):
        return TokenVerifyError.INVALID_SIGNATURE
    if isinstance(exc, JWTError):
        return TokenVerifyError.INVALID_SIGNATURE
    return TokenVerifyError.MALFORMED
```

### 3.4 错误处理决策表

| 异常 | 含义 | 返回 HTTP 状态 | 建议动作 |
|:---|:---|:---|:---|
| `ExpiredSignatureError` | Token 过期 | `401` | 提示前端使用 refresh_token 刷新 |
| `JWTError`（签名不匹配） | 签名验证失败 | `401` | 重新拉取 JWKS 后重试，仍失败则拒绝 |
| `JWTError`（kid 不匹配） | 公钥已轮换 | `401` | 强制刷新 JWKS 后重试一次 |
| `JWTError`（格式损坏） | Token 不是合法 JWT | `401` | 直接拒绝 |
| 网络错误（无法获取 JWKS） | cloud 不可达 | `503` | 降级到本地缓存；无缓存则返回 503 |

---

## 4. 接入示例

### 4.1 FastAPI Dependency（推荐直接复制）

```python
"""
school/mfg 后端认证中间件
复制本文件到项目，安装依赖即可使用
"""
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

# 复用上方的 verify_access_token, classify_jwt_error, TokenVerifyError

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
) -> dict:
    """
    FastAPI Dependency：验证 JWT 并注入当前用户 claims。
    
    用法：
        @app.get("/api/me")
        async def me(current_user: dict = Depends(get_current_user)):
            return {"user": current_user}
    """
    if credentials is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"error": "MISSING_TOKEN", "message": "Authorization header 缺失"},
        )

    token = credentials.credentials

    try:
        payload = await verify_access_token(token)
    except Exception as e:
        error_code = classify_jwt_error(e)
        status_map = {
            TokenVerifyError.EXPIRED: (status.HTTP_401_UNAUTHORIZED, "token 已过期，请刷新"),
            TokenVerifyError.JWKS_UNAVAILABLE: (status.HTTP_503_SERVICE_UNAVAILABLE, "认证服务暂不可用"),
        }
        http_status, message = status_map.get(
            error_code,
            (status.HTTP_401_UNAUTHORIZED, "无效的认证凭证"),
        )
        raise HTTPException(
            status_code=http_status,
            detail={"error": error_code.value, "message": message},
        )

    return payload


# ─── 可选：产品级鉴权 ──────────────────────────────────
def require_product(product: str):
    """
    要求用户订阅了指定产品。
    
    用法：
        @app.get("/api/school/courses")
        async def courses(
            user: dict = Depends(get_current_user),
            _: None = Depends(require_product("school")),
        ):
            ...
    """
    async def checker(user: dict = Depends(get_current_user)):
        products = user.get("products", [])
        if product not in products:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": "PRODUCT_NOT_SUBSCRIBED",
                    "message": f"当前用户未订阅 {product}，已订阅: {products}",
                },
            )
        return None
    return checker
```

### 4.2 路由配置示例

```python
from fastapi import FastAPI, Depends

app = FastAPI(title="School 教学平台")

@app.get("/api/school/courses")
async def list_courses(
    current_user: dict = Depends(get_current_user),
    _: None = Depends(require_product("school")),
):
    """仅 school 产品用户可访问"""
    return {
        "courses": [],
        "user_uuid": current_user["sub"],
        "email": current_user["email"],
    }


@app.get("/api/health")
async def health():
    """健康检查，无需鉴权"""
    return {"status": "ok"}
```

### 4.3 Refresh Token 处理

access_token 有效期 **30 分钟**（`expires_in: 1800`），过期后使用 refresh_token 获取新的 access_token。

#### 刷新端点

```
POST https://cloud.ziwi.cn/api/v1/auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJhbGci..."
}
```

#### 响应

```json
{
  "data": {
    "access_token": "eyJhbGciOi...",
    "refresh_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

#### 推荐封装

```python
async def refresh_access_token(refresh_token: str) -> dict:
    """调用 cloud 刷新 token"""
    async with httpx.AsyncClient(timeout=5) as client:
        resp = await client.post(
            "https://cloud.ziwi.cn/api/v1/auth/refresh",
            json={"refresh_token": refresh_token},
        )
        resp.raise_for_status()
        return resp.json()["data"]
```

#### 前端交互建议

```
┌─────────┐          ┌─────────┐          ┌───────────┐
│  前端 SPA │          │ school   │          │ cloud      │
│ (cloud)  │          │ 后端     │          │ IdP        │
└────┬─────┘          └────┬─────┘          └─────┬──────┘
     │ 登录               │                      │
     │──────────────────────────────────────────>│ POST /api/v1/auth/login
     │<──────────────────────────────────────────│ {access_token, refresh_token}
     │                    │                      │
     │ API 调用 + access_token                  │
     │───────────────────>│                      │
     │                    │ verify_access_token  │
     │                    │──┐                   │
     │                    │<─┘ JWKS 缓存在本地   │
     │<───────────────────│ 200 OK               │
     │                    │                      │
     │ access_token 过期后重试                    │
     │───────────────────>│                      │
     │<───────────────────│ 401 TOKEN_EXPIRED    │
     │                    │                      │
     │ 用 refresh_token 刷新                     │
     │──────────────────────────────────────────>│ POST /api/v1/auth/refresh
     │<──────────────────────────────────────────│ 新的 {access_token, refresh_token}
     │                    │                      │
     │ 重试原请求（新 access_token）              │
     │───────────────────>│                      │
     │<───────────────────│ 200 OK               │
```

---

## 5. API 契约速查

### 5.1 端点一览

| 方法 | 路径 | Content-Type | 鉴权 | 说明 |
|:---|:---|:---|:---|:---|
| `GET` | `/health` | — | 无 | 健康检查 |
| `GET` | `/api/v1/auth/public-key` | — | 无 | 获取 JWKS |
| `POST` | `/api/v1/auth/register` | `application/json` | 无 | 用户注册 |
| `POST` | `/api/v1/auth/login` | `application/json` | 无 | 登录 |
| `POST` | `/api/v1/auth/refresh` | `application/json` | 无 | 刷新 token |
| `GET` | `/api/v1/auth/me` | — | Bearer Token | 当前用户信息 |

### 5.2 请求/响应速查

#### 注册

```
POST /api/v1/auth/register
```

**请求**：
```json
{
  "email": "user@ziwi.cn",
  "password": "your_password",
  "display_name": "张三"
}
```

**响应** `201`：
```json
{
  "data": {
    "id": "uuid",
    "email": "user@ziwi.cn",
    "display_name": "张三",
    "tenant_id": null,
    "products": [],
    "is_active": true,
    "created_at": "2026-07-09T12:00:00"
  }
}
```

#### 登录

```
POST /api/v1/auth/login
```

**请求**：
```json
{
  "email": "user@ziwi.cn",
  "password": "your_password"
}
```

**响应** `200`：
```json
{
  "data": {
    "access_token": "eyJhbGciOiJSUzI1NiIsImtpZCI6ImtleV92MSIsInR5cCI6IkpXVCJ9...",
    "refresh_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

#### 刷新 Token

```
POST /api/v1/auth/refresh
```

**请求**：
```json
{
  "refresh_token": "eyJhbGciOi..."
}
```

**响应** `200`：
```json
{
  "data": {
    "access_token": "eyJhbGciOi...",
    "refresh_token": "eyJhbGciOi...",
    "token_type": "bearer",
    "expires_in": 1800
  }
}
```

#### 当前用户

```
GET /api/v1/auth/me
Authorization: Bearer eyJhbGciOi...
```

**响应** `200`：
```json
{
  "data": {
    "id": "uuid",
    "email": "user@ziwi.cn",
    "display_name": "张三",
    "tenant_id": null,
    "products": [],
    "is_active": true,
    "created_at": "2026-07-09T12:00:00"
  }
}
```

#### JWKS 公钥

```
GET /api/v1/auth/public-key
```

**响应** `200`：
```json
{
  "data": {
    "keys": [
      {
        "kty": "RSA",
        "kid": "key_v1",
        "n": "0vx7aq...",
        "e": "AQAB",
        "use": "sig",
        "alg": "RS256"
      }
    ]
  }
}
```

#### 健康检查

```
GET /health
```

**响应** `200`：
```json
{
  "status": "healthy",
  "timestamp": "2026-07-09T12:00:00Z"
}
```

---

## 6. 安全注意事项

### 6.1 公钥轮换策略

| 阶段 | kid | 操作 | cloud 侧 | 下游侧 |
|:---|:---|:---|:---|:---|
| **当前** | `key_v1` | — | 签名用 `key_v1` | 缓存 `key_v1` 公钥 |
| **过渡期** | `key_v1` + `key_v2` | cloud 新增 `key_v2`，同时发布两个 key | JWKS 返回 `[key_v1, key_v2]` | 缓存刷新后同时持有两把 key |
| **切换签名** | `key_v2`（签名） + `key_v1`（验证） | cloud 切换签名为 `key_v2` | JWT Header `kid` 变为 `key_v2` | 用 `key_v2` 验签成功，`key_v1` 闲置 |
| **下线旧 key** | `key_v2` | cloud 移除 `key_v1` | JWKS 仅返回 `key_v2` | 所有请求均用 `key_v2` 验签 |

**关键保障**：
- **过渡期至少持续 2 倍 JWKS 缓存 TTL**（即 ≥ 2 小时），确保所有下游已刷新缓存
- 下游验签遇到未知 kid 时**自动触发 JWKS 刷新**，无需人工介入
- cloud 签名切换与 JWKS 发布顺序：**先发布新 key → 等待 2×TTL → 切换签名 → 等待 2×TTL → 移除旧 key**

### 6.2 Token 有效期配置

| Token 类型 | 有效期 | 说明 |
|:---|:---|:---|
| `access_token` | **30 分钟**（1800s） | 短期，降低泄露风险 |
| `refresh_token` | **由 cloud 控制** | 用于获取新的 access_token |

建议：school/mfg 后端在 access_token 过期前 **5 分钟** 提示前端预刷新，减少用户感知的延迟。

### 6.3 HTTPS 强制

- cloud.ziwi.cn 已启用 `*.ziwi.cn_ecc` 通配符 SSL 证书
- **所有 API 调用必须走 HTTPS**，不允许 HTTP 明文传输
- 下游后端调用 cloud 时，使用 `https://cloud.ziwi.cn` 前缀
- 建议在 httpx 客户端中设置 `base_url="https://cloud.ziwi.cn"` 并在入口处校验 scheme

### 6.4 其他安全要点

| 要点 | 说明 |
|:---|:---|
| **不自行签发 Token** | 下游产品不得自行签发 JWT，所有 token 来自 cloud |
| **秘钥不外泄** | JWKS 中的公钥可以分发，但私钥仅 cloud 持有 |
| **Token 不落日志** | access_token/refresh_token 禁止写入应用日志 |
| **产品隔离** | 使用 `products` claim 做授权检查，不要仅依赖 token 有效性 |
| **传输安全** | school/mfg 后端之间的内部通信同样建议 HTTPS/mTLS |

---

## 附录 A：cloud 后端 API docstring 增强建议

> 以下建议面向 cloud.ziwi.cn 后端开发者，用于增强 FastAPI 自动生成的 OpenAPI 文档（`/docs` 页面）。

| 端点 | 当前问题 | 建议 |
|:---|:---|:---|
| `GET /health` | 无 description / tags | 添加 `tags=["Health"]`、`summary="服务健康检查"`、`description="返回服务及数据库连接状态"` |
| `GET /api/v1/auth/public-key` | 无 schema 文档说明 | 添加 `response_model=JWKSResponse`（定义 Pydantic model），`tags=["Auth"]`、`summary="获取 JWT 验签公钥（JWKS）"` |
| `POST /api/v1/auth/register` | 缺少请求 body 的 schema 描述 | 添加 `response_model=UserResponse`、`status_code=201`、`tags=["Auth"]`、`summary="用户注册"`。建议定义 `RegisterRequest` Pydantic model 含 `min_length/max_length` 约束，让 `/docs` 页自动展示字段格式要求 |
| `POST /api/v1/auth/login` | 响应中 token 字段没有 schema | 定义 `TokenResponse` model（`access_token: str, refresh_token: str, token_type: str, expires_in: int`），设为 `response_model`。`tags=["Auth"]`、`summary="用户登录"` |
| `POST /api/v1/auth/refresh` | 同上 | 定义 `RefreshRequest`（`refresh_token: str`），响应复用 `TokenResponse`。`tags=["Auth"]`、`summary="刷新 access_token"` |
| `GET /api/v1/auth/me` | 无鉴权标识 | `tags=["Auth"]`、`summary="获取当前用户信息"`。在路由上添加 `dependencies=[Depends(oauth2_scheme)]` 或 Security scheme 声明，让 `/docs` 页自动出现 🔒 锁图标和 "Authorize" 按钮 |
| 全局 `/docs` | OpenAPI info 不完整 | 在 `FastAPI()` 构造函数中补全 `title="cloud.ziwi.cn Identity Provider"`、`version="1.0.0"`、`description="知微多产品 SaaS 统一身份认证服务"`、`contact={...}` |
| 全局错误响应 | 无 422/401 等错误 schema | 为每个端点添加 `responses={401: {"model": ErrorResponse}, 422: {"model": ValidationError}}` 让下游开发者知道可能的错误格式 |

**通用建议**：
```python
# 推荐在 cloud 后端新增一个 schemas/auth.py 集中管理 Pydantic models:

from pydantic import BaseModel, EmailStr, Field

class RegisterRequest(BaseModel):
    email: EmailStr
    password: str = Field(..., min_length=8, max_length=128)
    display_name: str = Field(..., min_length=1, max_length=64)

class LoginRequest(BaseModel):
    email: EmailStr
    password: str

class TokenResponse(BaseModel):
    access_token: str
    refresh_token: str
    token_type: str = "bearer"
    expires_in: int

class JWKSKey(BaseModel):
    kty: str
    kid: str
    n: str
    e: str
    use: str
    alg: str

class JWKSResponse(BaseModel):
    keys: list[JWKSKey]

class UserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    tenant_id: str | None
    products: list[str]
    is_active: bool
    created_at: str

# 然后每个路由挂上 response_model，FastAPI 会自动渲染完整的 OpenAPI schema
```

---

## 附录 B：快速自测脚本

```bash
# 1. 健康检查
curl -s https://cloud.ziwi.cn/health | jq

# 2. 获取公钥
curl -s https://cloud.ziwi.cn/api/v1/auth/public-key | jq '.data.keys[0].kid'
# 预期输出: "key_v1"

# 3. 注册
curl -s -X POST https://cloud.ziwi.cn/api/v1/auth/register \
  -H "Content-Type: application/json" \
  -d '{"email":"test@ziwi.cn","password":"test1234","display_name":"Test"}' | jq

# 4. 登录
TOKEN=$(curl -s -X POST https://cloud.ziwi.cn/api/v1/auth/login \
  -H "Content-Type: application/json" \
  -d '{"email":"test@ziwi.cn","password":"test1234"}' | jq -r '.data.access_token')

# 5. 验签（用 python-jose）
python3 -c "
from jose import jwt
import httpx, json
resp = httpx.get('https://cloud.ziwi.cn/api/v1/auth/public-key')
jwk = resp.json()['data']['keys'][0]
payload = jwt.decode('$TOKEN', jwk, algorithms=['RS256'])
print(json.dumps(payload, indent=2))
"

# 6. 获取用户信息
curl -s https://cloud.ziwi.cn/api/v1/auth/me \
  -H "Authorization: Bearer $TOKEN" | jq
```

---

> **文档维护**：cloud.ziwi.cn API 变更时同步更新本文档。  
> **联系方式**：知微平台架构组
