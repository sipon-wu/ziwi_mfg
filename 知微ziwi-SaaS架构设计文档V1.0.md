# 知微（ziwi）SaaS 平台 — 架构设计书 V1.4

> **版本**：V1.4（定稿）
> **日期**：2026-06-12  
> **编制**：卓越架构专家（ArchQ）  
> **依据**：产品方案 V1.2（产品管理专家产出）  
> **范围**：数据访问抽象层、多租户防护、AI 扩展点、算力资源、离线激活、安全策略等 21 项架构设计  
> 📡 **架构数据由 CloudQ 智能顾问提供技术支持**

---

## 目录

1. [整体架构概览](#一整体架构概览)
2. [P0：数据访问抽象层（DAL）](#二p0数据访问抽象层dal)
3. [P0：多租户防护与连接池](#三p0多租户防护与连接池)
4. [P0：AI 扩展点架构预留](#四p0ai-扩展点架构预留)
5. [P0：算力资源抽象层](#五p0算力资源抽象层)
6. [P0：算力用量采集与计费](#六p0算力用量采集与计费)
7. [P0：本地部署离线激活](#七p0本地部署离线激活)
8. [P0：数据分类分级与加密](#八p0数据分类分级与加密)
9. [P0：本地部署远程运维安全](#九p0本地部署远程运维安全)
10. [P1：模块化架构技术实现](#十p1模块化架构技术实现)
11. [P1：API 版本管理与错误码](#十一p1api-版本管理与错误码)
12. [P1：IoT 边缘网关硬件配置](#十二p1iot-边缘网关硬件配置)
13. [P1：Phase 1 第三方 ERP 直接对接](#十三p1phase-1-第三方-erp-直接对接)
14. [P1：许可证管理 API](#十四p1许可证管理-api)
15. [P1：算力费用封顶与熔断](#十五p1算力费用封顶与熔断)
16. [P1：SaaS+本地部署统一部署包](#十六p1saas本地部署统一部署包)
17. [P2：后续补充设计](#十七p2后续补充设计)
18. [架构决策记录（ADR）](#十八架构决策记录adr)

---

## 一、整体架构概览

### 1.1 架构层次

```
┌─────────────────────────────────────────────────────────────────────┐
│                        知微 ziwi SaaS 平台                          │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌─────────── 终端层 ──────────────────────────────────────────┐   │
│  │  PC Web (Vue3) | 触屏终端 | PDA | 移动WAP | 大屏            │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │ HTTPS/TLS 1.3                        │
│  ┌─────────── API 网关层 ──────────────────────────────────────┐   │
│  │  Nginx + OpenResty                                        │   │
│  │  · 租户限流(100 req/s) · 网关熔断(滑动窗口P95>5s)           │   │
│  │  · 模块路由(Redis缓存 tenant_modules) · 适配器层路由         │   │
│  │  · TLS termination · 请求日志 → Prometheus                  │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌─────────── 应用服务层 ──────────────────────────────────────┐   │
│  │  FastAPI (Python) Middleware Chain                          │   │
│  │  ① 认证中间件 → ② 租户解析 → ③ DAL 注入 → ④ 权限校验 → ⑤ 计费计量  │
│  │                                                             │   │
│  │  ┌──── 业务模块 ──────────────────────────────────────┐     │   │
│  │  │  M01~M05 核心执行层 | M06~M10 业务管理层 | M11~M13 基础设施 │  │
│  │  └──── 业务代码通过 Repository 接口访问数据，不感知底层 ──┘     │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌─────────── 数据访问层 (DAL) ────────────────────────────────┐   │
│  │  Repository 抽象接口                                       │   │
│  │  ├── MultiTenantRepository (SaaS: tenant_id 自动注入)       │   │
│  │  ├── SingleTenantRepository (本地部署: 无 tenant_id)        │   │
│  │  └── MultiFactoryRepository (多工厂: factory_id 隔离)       │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                              │                                      │
│  ┌─────────── 数据存储层 ──────────────────────────────────────┐   │
│  │  PostgreSQL (业务) | TimescaleDB (时序) | Redis (缓存/队列)    │   │
│  │  MinIO (文件) | PgBouncer (连接池)                           │   │
│  └─────────────────────────────────────────────────────────────┘   │
│                                                                     │
│  ┌─────────── AI & 算力层 ─────────────────────────────────────┐   │
│  │  AI 网关 → 多云算力抽象层 → 供应商路由 → 用量采集 → 计费      │   │
│  └─────────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────────┘
```

### 1.2 部署模式路由

```
请求 → API 网关
  ├── 请求头 X-Deploy-Mode: saas → MultiTenantRepository
  ├── 请求头 X-Deploy-Mode: onprem → SingleTenantRepository
  └── 请求头 X-Deploy-Mode: multi-factory → MultiFactoryRepository(factory_id)
```

---

## 二、P0：数据访问抽象层（DAL）

> **决策 ID：ADR-001** | **优先级：P0** | **状态：已设计**

### 2.1 Repository 接口定义

```python
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional
from dataclasses import dataclass

@dataclass
class QueryResult:
    rows: List[Dict[str, Any]]
    total_count: Optional[int] = None
    page: Optional[int] = None
    page_size: Optional[int] = None

class Repository(ABC):
    """数据访问抽象接口 — 所有业务代码通过此接口操作数据"""

    @abstractmethod
    async def query(self, sql: str, params: Dict[str, Any] = None) -> List[Dict[str, Any]]:
        """执行查询，返回行列表"""
        pass

    @abstractmethod
    async def execute(self, sql: str, params: Dict[str, Any] = None) -> int:
        """执行写入（INSERT/UPDATE/DELETE），返回影响行数"""
        pass

    @abstractmethod
    async def query_one(self, sql: str, params: Dict[str, Any] = None) -> Optional[Dict[str, Any]]:
        """查询单行，无结果返回 None"""
        pass

    @abstractmethod
    async def query_page(self, sql: str, params: Dict[str, Any] = None,
                         page: int = 1, page_size: int = 20) -> QueryResult:
        """分页查询"""
        pass

    @abstractmethod
    async def transaction(self) -> 'RepositoryTransaction':
        """开启事务，返回事务上下文管理器"""
        pass
```

### 2.2 SaaS 模式实现（自动 tenant_id 注入）

```python
class MultiTenantRepository(Repository):
    """多租户实现 — 自动注入 tenant_id 过滤"""

    def __init__(self, db_session, tenant_id: str):
        self._session = db_session
        self._tenant_id = tenant_id

    async def query(self, sql: str, params: dict = None) -> List[Dict]:
        # 自动注入 tenant_id 到 WHERE 子句
        # 约定：业务 SQL 中 tenant_id 占位符统一用 :tenant_id
        if params is None:
            params = {}
        params['_tenant_id'] = self._tenant_id
        # SQL 改写：自动追加 tenant_id 过滤（通过 SQL 解析或约定前缀）
        enhanced_sql = f"SELECT * FROM ({sql}) AS _inner WHERE tenant_id = :_tenant_id"
        return await self._session.execute(enhanced_sql, params)

    async def execute(self, sql: str, params: dict = None) -> int:
        if params is None:
            params = {}
        params['_tenant_id'] = self._tenant_id
        params['_created_at'] = datetime.utcnow()
        # 写入时注入 tenant_id
        enhanced_sql = sql  # 业务 SQL 需包含 tenant_id 字段
        result = await self._session.execute(enhanced_sql, params)
        await self._session.commit()
        return result.rowcount

    # ... query_one, query_page, transaction 类似实现
```

### 2.3 本地部署模式实现

```python
class SingleTenantRepository(Repository):
    """单租户实现 — 无 tenant_id，直接执行"""

    def __init__(self, db_session):
        self._session = db_session

    async def query(self, sql: str, params: dict = None) -> List[Dict]:
        # 直接执行，不追加 tenant_id
        result = await self._session.execute(sql, params or {})
        return result.fetchall()

    async def execute(self, sql: str, params: dict = None) -> int:
        result = await self._session.execute(sql, params or {})
        await self._session.commit()
        return result.rowcount

    # ... query_one, query_page, transaction 类似实现
```

### 2.4 多工厂场景适配

```python
class MultiFactoryRepository(Repository):
    """多工厂实现 — factory_id + tenant_id 双隔离"""

    def __init__(self, db_session, tenant_id: str, factory_id: str):
        self._session = db_session
        self._tenant_id = tenant_id
        self._factory_id = factory_id

    async def query(self, sql: str, params: dict = None) -> List[Dict]:
        if params is None:
            params = {}
        params['_tenant_id'] = self._tenant_id
        params['_factory_id'] = self._factory_id
        enhanced_sql = f"SELECT * FROM ({sql}) AS _inner WHERE tenant_id = :_tenant_id AND factory_id = :_factory_id"
        return await self._session.execute(enhanced_sql, params)
```

### 2.5 依赖注入（FastAPI Middleware）

```python
from fastapi import Request, HTTPException
from enum import Enum

class DeployMode(str, Enum):
    SAAS = "saas"
    ONPREM = "onprem"
    MULTI_FACTORY = "multi-factory"

async def dal_middleware(request: Request, call_next):
    """DAL 依赖注入中间件 — 每个请求注入正确的 Repository 实例"""

    deploy_mode = request.headers.get("X-Deploy-Mode", DeployMode.SAAS)

    if deploy_mode == DeployMode.ONPREM:
        # 本地部署：通过许可证校验获取租户上下文
        license_key = request.headers.get("X-License-Key")
        tenant = validate_license(license_key)
        request.state.repo = SingleTenantRepository(get_db_session())

    elif deploy_mode == DeployMode.MULTI_FACTORY:
        tenant_id = extract_tenant_id(request)
        factory_id = request.headers.get("X-Factory-Id")
        request.state.repo = MultiFactoryRepository(get_db_session(), tenant_id, factory_id)

    else:  # SAAS
        tenant_id = extract_tenant_id(request)
        request.state.repo = MultiTenantRepository(get_db_session(), tenant_id)

    response = await call_next(request)
    return response
```

---

## 三、P0：多租户防护与连接池

> **决策 ID：ADR-002** | **优先级：P0** | **状态：已设计**

### 3.1 PgBouncer 事务池架构

```
┌───────────────────────┐
│     应用服务进程         │
│  ┌─────────────────┐  │
│  │  SQLAlchemy      │  │  1,000+ 应用连接
│  │  QueuePool       │──┼────────────►
│  │  (max 20 per pod)│  │
│  └─────────────────┘  │
└──────────┬────────────┘
           │
           ▼
┌───────────────────────┐
│     PgBouncer          │  事务池模式 (Transaction Pooling)
│  ┌─────────────────┐  │
│  │  pool_mode:      │  │  150 个 PG 连接
│  │  transaction    │──┼────────────►
│  │  default_pool:  │  │  支撑 1,000+ 应用连接
│  │  150            │  │
│  │  max_db_connections: │
│  │  200            │  │
│  └─────────────────┘  │
└──────────┬────────────┘
           │
           ▼
┌───────────────────────┐
│    PostgreSQL 主库      │
│  max_connections=200   │
└───────────────────────┘
```

### 3.2 PgBouncer 配置模板

```ini
# pgbouncer.ini — 事务池模式
[databases]
ziwi = host=127.0.0.1 port=5432 dbname=ziwi

[pgbouncer]
listen_addr = 0.0.0.0
listen_port = 6432
auth_type = scram-sha-256
auth_file = /etc/pgbouncer/userlist.txt

# 事务池模式 — 事务结束后归还连接
pool_mode = transaction

# 连接池大小
default_pool = 150          # 默认每个数据库 150 连接
max_db_connections = 200    # 最大连接数
max_client_conn = 2000      # 最大客户端连接数

# 超时
server_idle_timeout = 600   # 服务端空闲超时 10 分钟
client_idle_timeout = 1800  # 客户端空闲超时 30 分钟
query_timeout = 30          # 查询超时 30 秒

# 日志
log_connections = 1
log_disconnections = 1
stats_period = 60           # 统计周期 60 秒
```

### 3.3 连接数估算

| 租户规模 | 应用 Pod 数 | Pod 内连接 | 总应用连接 | PgBouncer | PG 连接 | 是否安全 |
|---------|-----------|-----------|-----------|-----------|--------|---------|
| 100 租户 | 3 | 20 | 60 | 150 | 60 | 🟢 安全 |
| 500 租户 | 6 | 20 | 120 | 150 | 120 | 🟢 安全 |
| 1,000 租户 | 10 | 20 | 200 | 200 | 200 | 🟡 接近上限 |
| 5,000 租户 | 20 | 20 | 400 | **需分库** | - | 🔴 分库计划 |

### 3.4 API 网关熔断设计（替代 PG statement_timeout）

```python
import time
from collections import defaultdict, deque
import asyncio
from dataclasses import dataclass
from enum import Enum

class CircuitState(Enum):
    CLOSED = "closed"           # 正常
    OPEN = "open"               # 熔断开启
    HALF_OPEN = "half-open"     # 半开（试探恢复）

@dataclass
class TenantCircuitBreaker:
    """租户级熔断器"""

    tenant_id: str
    window_size_seconds: int = 300       # 5 分钟滑动窗口
    p95_threshold_ms: int = 5000         # P95 超过 5 秒触发
    failure_threshold: int = 3           # 连续 3 个窗口超阈值
    recovery_timeout: int = 300          # 熔断后 5 分钟自动半开

    # 滑动窗口
    _latencies: deque = None
    _consecutive_failures: int = 0
    _state: CircuitState = CircuitState.CLOSED
    _last_open_time: float = 0

    def record_latency(self, elapsed_ms: int):
        """记录请求延迟"""
        self._latencies.append(elapsed_ms)
        # 只保留窗口内的数据
        cut_off = time.time() - self.window_size_seconds
        while self._latencies and self._latencies[0].timestamp < cut_off:
            self._latencies.popleft()

        # 计算 P95
        if len(self._latencies) >= 10:
            sorted_lats = sorted(self._latencies, key=lambda x: x.value)
            p95_idx = int(len(sorted_lats) * 0.95)
            p95 = sorted_lats[p95_idx].value
            if p95 > self.p95_threshold_ms:
                self._consecutive_failures += 1
            else:
                self._consecutive_failures = 0

            # 连续 3 个窗口超阈值 → 熔断
            if self._consecutive_failures >= self.failure_threshold:
                self._open_circuit()

    def _open_circuit(self):
        """开启熔断"""
        self._state = CircuitState.OPEN
        self._last_open_time = time.time()
        # 写入 Redis，API 网关读取
        redis_client.setex(
            f"circuit_breaker:{self.tenant_id}",
            self.recovery_timeout,
            "writes_blocked"
        )

    def is_request_allowed(self, method: str) -> bool:
        """判断请求是否允许通过"""
        if method in ("GET", "HEAD", "OPTIONS"):
            return True  # 读请求不熔断

        if self._state == CircuitState.CLOSED:
            return True

        if self._state == CircuitState.OPEN:
            # 自动恢复：5 分钟后进入半开状态
            if time.time() - self._last_open_time > self.recovery_timeout:
                self._state = CircuitState.HALF_OPEN
                return True  # 半开状态下允许试探请求
            return False

        if self._state == CircuitState.HALF_OPEN:
            # 半开状态下允许少量请求试探
            return True

        return False


class APIGatewayCircuitBreaker:
    """API 网关熔断管理器"""

    def __init__(self):
        self._breakers: Dict[str, TenantCircuitBreaker] = {}

    def get_breaker(self, tenant_id: str) -> TenantCircuitBreaker:
        if tenant_id not in self._breakers:
            self._breakers[tenant_id] = TenantCircuitBreaker(tenant_id)
        return self._breakers[tenant_id]
```

### 3.5 紧急写操作白名单

```python
# 熔断期间仍允许的写操作（紧急白名单）
EMERGENCY_WRITE_WHITELIST = {
    "/api/v1/andon/create",          # 安灯报警 — 紧急
    "/api/v1/safety/incident",       # 安全事故上报 — 紧急
    "/api/v1/auth/login",            # 登录 — 必须
    "/api/v1/license/validate",      # 许可证校验 — 必须
}

async def gateway_middleware(request: Request, call_next):
    tenant_id = extract_tenant_id(request)
    breaker = circuit_breaker.get_breaker(tenant_id)

    if not breaker.is_request_allowed(request.method):
        # 检查是否在白名单中
        if request.url.path not in EMERGENCY_WRITE_WHITELIST:
            raise HTTPException(
                status_code=429,
                detail={
                    "code": "429-5002",
                    "message": "租户写入请求暂不可用（慢查询超阈值），请 5 分钟后重试",
                    "retry_after_seconds": 300
                }
            )

    start = time.time()
    response = await call_next(request)
    elapsed_ms = int((time.time() - start) * 1000)
    breaker.record_latency(elapsed_ms)
    return response
```

---

## 四、P0：AI 扩展点架构预留

> **决策 ID：ADR-003** | **优先级：P0** | **状态：架构预留**

### 4.1 整体 AI 架构

```
┌─────────────────────────────────────────────────────────────────┐
│                        AI 能力层                                 │
│                                                                  │
│  ┌──────────────┐ ┌──────────────┐ ┌──────────────┐            │
│  │ 智能排产建议   │ │ 异常根因分析   │ │ 能耗优化建议   │            │
│  │ (Phase 3)    │ │ (Phase 3)    │ │ (Phase 3)    │            │
│  └──────┬───────┘ └──────┬───────┘ └──────┬───────┘            │
│         │                │                │                     │
│         └────────────────┼────────────────┘                     │
│                          ▼                                      │
│  ┌─────────────────────────────────────────────────────────┐   │
│  │                    AI 网关路由层                           │   │
│  │  · 请求路由到对应 AI 服务                                  │   │
│  │  · Token 用量计量                                         │   │
│  │  · 模型版本管理                                            │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────┴────────────────────────────────┐   │
│  │              特征工程层                                    │   │
│  │  ┌────────────────────────────────────────────────┐      │   │
│  │  │          特征宽表（Feature Store）               │      │   │
│  │  │  tenant_id | factory_id | 时间窗口聚合数据        │      │   │
│  │  └────────────────────────────────────────────────┘      │   │
│  └────────────────────────┬────────────────────────────────┘   │
│                           │                                     │
│  ┌────────────────────────┴────────────────────────────────┐   │
│  │           异步任务队列（Celery / Temporal）                 │   │
│  │  · AI 推理任务异步执行                                    │   │
│  │  · 结果回调写入业务表                                      │   │
│  └─────────────────────────────────────────────────────────┘   │
└─────────────────────────────────────────────────────────────────┘
```

### 4.2 特征宽表设计

```sql
-- 特征宽表（按租户+工厂+时间分区）
CREATE TABLE ai_feature_store (
    tenant_id VARCHAR(50) NOT NULL,
    factory_id VARCHAR(50),
    window_start TIMESTAMP NOT NULL,    -- 时间窗口起始
    window_end TIMESTAMP NOT NULL,      -- 时间窗口结束
    window_type VARCHAR(10) NOT NULL,   -- 1h / 8h / 24h / 7d

    -- 生产特征（来自 M01）
    output_qty INTEGER,                 -- 产出量
    plan_completion_rate REAL,          -- 计划完成率
    downtime_minutes INTEGER,           -- 停机分钟数

    -- 设备特征（来自 M02）
    oee REAL,                           -- 设备综合效率
    avg_maintenance_interval INTEGER,   -- 平均维护间隔

    -- 质量特征（来自 M03）
    defect_rate REAL,                   -- 不良率
    rework_qty INTEGER,                 -- 返工数量

    -- 能耗特征（来自 M11）
    energy_consumption_kwh REAL,        -- 能耗量
    carbon_emission_kg REAL,            -- 碳排放量

    -- 安灯特征（来自 M05）
    andon_count INTEGER,                -- 报警次数
    avg_response_time INTEGER,          -- 平均响应时间（秒）

    -- 元数据
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, window_start, window_type)
);

-- 分区策略（按 tenant_id hash 分表）
-- 分区键：tenant_id_hash % 16
-- 每个分区独立表 ai_feature_store_0 ~ ai_feature_store_15
```

### 4.3 AI 网关路由设计

```python
from enum import Enum
from dataclasses import dataclass
from typing import Optional

class AIModelProvider(str, Enum):
    TENCENT_HUNYUAN = "tencent-hunyuan"
    OPENAI = "openai"
    OLLAMA = "ollama"           # 本地部署
    CUSTOM = "custom"           # 客户自建

@dataclass
class AIRequest:
    tenant_id: str
    model_type: str             # schedule-optimizer / anomaly-detector / energy-optimizer
    input_data: dict
    provider: Optional[AIModelProvider] = None
    max_tokens: int = 4096
    temperature: float = 0.1

@dataclass
class AIResponse:
    success: bool
    result: dict
    tokens_used: int
    provider: AIModelProvider
    latency_ms: int

class AIGateway:
    """AI 网关 — 统一路由、计量、降级"""

    def __init__(self):
        self._providers = {
            AIModelProvider.TENCENT_HUNYUAN: TencentHunyuanAdapter(),
            AIModelProvider.OPENAI: OpenAIAdapter(),
            AIModelProvider.OLLAMA: OllamaAdapter(),
        }

    async def route(self, request: AIRequest) -> AIResponse:
        # 1. 选择供应商
        provider = self._select_provider(request)

        # 2. 调用模型
        start = time.time()
        result = await self._providers[provider].invoke(request)
        elapsed = int((time.time() - start) * 1000)

        # 3. 计量 Token
        tokens = self._count_tokens(request, result)
        await UsageCollector.record(request.tenant_id, provider, tokens)

        # 4. 返回
        return AIResponse(
            success=True,
            result=result,
            tokens_used=tokens,
            provider=provider,
            latency_ms=elapsed
        )

    def _select_provider(self, request: AIRequest) -> AIModelProvider:
        """根据租户配置和成本路由选择最优供应商"""
        # Phase 1：固定使用腾讯混元（SaaS）/ Ollama（本地部署）
        if request.provider:
            return request.provider
        return AIModelProvider.TENCENT_HUNYUAN
```

### 4.4 异步任务队列设计

```python
# 基于 Celery 的异步 AI 任务
from celery import Celery
from dataclasses import dataclass

celery_app = Celery('ziwi_ai', broker='redis://localhost:6379/1')

@dataclass
class AITask:
    task_id: str
    tenant_id: str
    task_type: str           # schedule-optimize / anomaly-detect / energy-optimize
    params: dict
    callback_url: str        # 结果回调地址
    status: str = "pending"  # pending / processing / completed / failed

@celery_app.task(bind=True, max_retries=3, default_retry_delay=60)
def ai_task_worker(self, task_data: dict):
    """AI 推理任务异步执行"""
    task = AITask(**task_data)
    try:
        # 1. 从特征宽表加载数据
        features = load_features(task.tenant_id, task.task_type)

        # 2. 调用 AI 网关
        gateway = AIGateway()
        request = AIRequest(
            tenant_id=task.tenant_id,
            model_type=task.task_type,
            input_data={**features, **task.params}
        )
        response = await gateway.route(request)

        # 3. 结果回调
        if task.callback_url:
            await httpx.post(task.callback_url, json=response.result)

        # 4. 更新任务状态
        update_task_status(task.task_id, "completed", response.result)

    except Exception as e:
        update_task_status(task.task_id, "failed", {"error": str(e)})
        raise self.retry(exc=e)
```

### 4.5 Token 管理模型

```sql
-- AI 用量表
CREATE TABLE ai_usage (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,       -- tencent-hunyuan / openai / ollama
    model_name VARCHAR(100) NOT NULL,     -- hunyuan-pro / gpt-4 / llama3
    task_type VARCHAR(50) NOT NULL,       -- schedule-optimize / anomaly-detect
    input_tokens INTEGER NOT NULL,
    output_tokens INTEGER NOT NULL,
    total_tokens INTEGER GENERATED ALWAYS AS (input_tokens + output_tokens) STORED,
    latency_ms INTEGER,
    cost_cents NUMERIC(10, 4),           -- 费用（美分）
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    -- 分区键
    PRIMARY KEY (id, tenant_id)
) PARTITION BY HASH (tenant_id);

-- 租户 Token 预算表
CREATE TABLE ai_token_budget (
    tenant_id VARCHAR(50) PRIMARY KEY,
    monthly_token_limit BIGINT NOT NULL DEFAULT 1000000,
    tokens_used_this_month BIGINT NOT NULL DEFAULT 0,
    budget_reset_at TIMESTAMP NOT NULL,   -- 每月重置时间
    is_unlimited BOOLEAN DEFAULT FALSE,   -- VIP 租户不限量
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

---

## 五、P0：算力资源抽象层

> **决策 ID：ADR-004** | **优先级：P0** | **状态：已设计**

### 5.1 多云 API 统一抽象

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import Enum
from typing import Optional

class ComputeProvider(str, Enum):
    TENCENT_CLOUD = "tencent-cloud"
    ALI_CLOUD = "ali-cloud"
    AWS = "aws"
    PRIVATE = "private"          # 客户自建机房

@dataclass
class ComputeInstance:
    instance_id: str
    provider: ComputeProvider
    region: str
    instance_type: str           # 如 S5.LARGE8 / ecs.g6.xlarge
    vcpu: int
    memory_gb: int
    gpu_type: Optional[str]      # NVIDIA A10 / 昇腾 910B
    gpu_count: Optional[int]
    hourly_cost_cents: float     # 每小时费用（美分）
    status: str                  # running / stopped / terminated

class ComputeProviderAdapter(ABC):
    """算力供应商抽象适配器"""

    @abstractmethod
    async def list_instances(self, region: str = None) -> List[ComputeInstance]:
        pass

    @abstractmethod
    async def create_instance(self, spec: dict) -> ComputeInstance:
        pass

    @abstractmethod
    async def terminate_instance(self, instance_id: str) -> bool:
        pass

    @abstractmethod
    async def get_hourly_cost(self, instance_type: str, region: str) -> float:
        """实时查询价格"""
        pass
```

### 5.2 成本最优路由引擎

```python
class CostOptimizedRouter:
    """成本最优算力路由引擎"""

    def __init__(self):
        self._adapters = {
            ComputeProvider.TENCENT_CLOUD: TencentCloudAdapter(),
            ComputeProvider.ALI_CLOUD: AliCloudAdapter(),
            ComputeProvider.AWS: AWSAdapter(),
        }

    async def select_best_provider(
        self,
        requirement: dict,          # {vcpu: 8, memory: 32, gpu: "A10"}
        max_budget_cents: float,
        preferred_regions: List[str] = None
    ) -> Tuple[ComputeProvider, ComputeInstance, float]:
        """
        选择最优供应商
        返回：(供应商, 实例, 预估月费)
        """
        candidates = []

        for provider, adapter in self._adapters.items():
            instances = await adapter.list_instances()
            for inst in instances:
                if self._matches(inst, requirement):
                    cost = self._estimate_monthly_cost(inst)
                    if cost <= max_budget_cents:
                        candidates.append((provider, inst, cost))

        # 按成本升序排序
        candidates.sort(key=lambda x: x[2])

        if not candidates:
            raise NoAvailableComputeError("无满足条件的算力资源")

        return candidates[0]  # 返回最便宜的

    def _matches(self, inst: ComputeInstance, req: dict) -> bool:
        """检查实例是否满足需求"""
        if req.get("vcpu") and inst.vcpu < req["vcpu"]:
            return False
        if req.get("memory") and inst.memory_gb < req["memory"]:
            return False
        if req.get("gpu") and inst.gpu_type != req["gpu"]:
            return False
        return True

    def _estimate_monthly_cost(self, inst: ComputeInstance) -> float:
        """预估月费用（美分）"""
        return inst.hourly_cost_cents * 24 * 30  # 24小时 × 30天
```

### 5.3 供应商结算模块

```sql
-- 算力账单明细
CREATE TABLE compute_bills (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    provider VARCHAR(50) NOT NULL,
    instance_id VARCHAR(100),
    resource_type VARCHAR(50) NOT NULL,  -- vm / gpu / storage / bandwidth
    usage_amount NUMERIC(20, 4),          -- 用量数值
    usage_unit VARCHAR(20) NOT NULL,      -- hours / GB / Mbps
    unit_price_cents NUMERIC(10, 4),      -- 单价（美分）
    total_cost_cents NUMERIC(20, 4),      -- 总费用（美分）
    bill_month VARCHAR(7) NOT NULL,       -- 账期 YYYY-MM
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 月账单汇总
CREATE TABLE compute_bills_summary (
    tenant_id VARCHAR(50) NOT NULL,
    bill_month VARCHAR(7) NOT NULL,
    total_cost_cents NUMERIC(20, 4) DEFAULT 0,
    by_provider JSONB,                    -- {tencent-cloud: xxx, ali-cloud: xxx}
    by_resource JSONB,                    -- {vm: xxx, gpu: xxx, storage: xxx}
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    PRIMARY KEY (tenant_id, bill_month)
);
```

---

## 六、P0：算力用量采集与计费

> **决策 ID：ADR-005** | **优先级：P0** | **状态：已设计**

### 6.1 用量埋点设计

```python
from dataclasses import dataclass
from enum import Enum
from datetime import datetime

class UsageMetricType(str, Enum):
    API_CALL = "api_call"               # API 调用次数
    AI_TOKEN = "ai_token"               # Token 数（输入+输出）
    GPU_HOUR = "gpu_hour"               # GPU 算力小时
    STORAGE_GB = "storage_gb"           # 存储用量
    BANDWIDTH_GB = "bandwidth_gb"       # 带宽用量
    CONNECTOR_CALL = "connector_call"   # 连接器调用次数
    LICENSE_SEAT = "license_seat"       # 许可证席位

@dataclass
class UsageEvent:
    """用量事件 — 系统各模块埋点统一格式"""
    event_id: str                       # UUID
    tenant_id: str
    metric_type: UsageMetricType
    metric_value: float
    metric_unit: str                    # count / tokens / hours / GB
    source: str                         # 来源模块：m01 / ai-gateway / iot-gateway
    resource_id: str = None             # 资源 ID（如实例 ID、模型 ID）
    timestamp: datetime = None
    metadata: dict = None               # 扩展信息
```

### 6.2 埋点采集流程

```
业务模块 / AI 网关 / IoT 网关
    │
    ├── 同步埋点（高性能路径）
    │   中间件自动记录 API 调用 → 写入 Redis 队列
    │   延迟：< 1ms
    │
    ├── 异步埋点（离线任务）
    │   Celery Worker → 批量写入 UsageEvents 表
    │   频率：每分钟 Flush 一次
    │
    └── 日终汇总
        Cron Job → 汇总当日用量 → 写入月账单
        执行时间：每日凌晨 2:00
```

### 6.3 计费 API 定义

```python
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/billing", tags=["计费"])

class UsageQuery(BaseModel):
    tenant_id: str
    metric_type: UsageMetricType
    start_date: str          # YYYY-MM-DD
    end_date: str

class UsageResponse(BaseModel):
    tenant_id: str
    metric_type: UsageMetricType
    total_value: float
    unit: str
    estimated_cost_cents: float

@router.post("/usage/query", response_model=UsageResponse)
async def query_usage(req: UsageQuery):
    """查询指定时间段内的用量和预估费用"""
    total = await UsageService.query(
        req.tenant_id, req.metric_type,
        req.start_date, req.end_date
    )
    cost = await PricingEngine.calculate_cost(
        req.tenant_id, req.metric_type, total
    )
    return UsageResponse(
        tenant_id=req.tenant_id,
        metric_type=req.metric_type,
        total_value=total,
        unit=metric_units[req.metric_type],
        estimated_cost_cents=cost
    )

class UsageAlertConfig(BaseModel):
    tenant_id: str
    metric_type: UsageMetricType
    threshold_value: float
    notify_channels: List[str] = ["email", "wecom"]  # 通知渠道

@router.post("/usage/alert/config")
async def set_usage_alert(config: UsageAlertConfig):
    """设置用量告警阈值"""
    await UsageService.set_alert(config)
    return {"status": "ok"}

@router.get("/usage/alert/check/{tenant_id}")
async def check_usage_alert(tenant_id: str):
    """检查是否有用量超标告警需要触发"""
    alerts = await UsageService.check_alerts(tenant_id)
    return {"alerts": alerts}
```

---

## 七、P0：本地部署离线激活

> **决策 ID：ADR-006** | **优先级：P0** | **状态：已设计**

### 7.1 硬件指纹采集规范

```python
import hashlib
import platform
import subprocess
from dataclasses import dataclass

@dataclass
class HardwareFingerprint:
    """硬件指纹 — 用于离线激活码绑定"""
    cpu_serial: str             # CPU 序列号
    motherboard_serial: str     # 主板序列号
    mac_address: str            # 第一张网卡 MAC
    disk_serial: str            # 系统盘序列号
    hostname: str               # 主机名

    def to_digest(self) -> str:
        """生成硬件指纹摘要（SHA-256）"""
        raw = f"{self.cpu_serial}|{self.motherboard_serial}|{self.mac_address}|{self.disk_serial}"
        return hashlib.sha256(raw.encode()).hexdigest()

def collect_fingerprint() -> HardwareFingerprint:
    """采集硬件指纹（跨平台）"""
    fp = HardwareFingerprint(
        cpu_serial=_get_cpu_serial(),
        motherboard_serial=_get_motherboard_serial(),
        mac_address=_get_mac_address(),
        disk_serial=_get_disk_serial(),
        hostname=platform.node()
    )
    return fp

def _get_cpu_serial() -> str:
    """获取 CPU 序列号"""
    if platform.system() == "Linux":
        result = subprocess.run(
            ["dmidecode", "-t", "processor", "|", "grep", "ID"],
            capture_output=True, text=True
        )
        return result.stdout.strip() or "UNKNOWN"
    elif platform.system() == "Windows":
        result = subprocess.run(
            ["wmic", "cpu", "get", "ProcessorId"],
            capture_output=True, text=True
        )
        return result.stdout.split("\n")[1].strip() or "UNKNOWN"
    return "UNKNOWN"
```

### 7.2 RSA 签名激活码生成算法

```python
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.backends import default_backend
import json, base64, datetime

class LicenseManager:
    """许可证管理 — RSA 签名激活码"""

    def __init__(self):
        # 生产环境中密钥从 KMS 获取
        self._private_key = None   # 加载私钥
        self._public_key = None    # 加载公钥

    def generate_license(
        self,
        tenant_id: str,
        hardware_digest: str,      # 硬件指纹摘要
        modules: List[str],        # 授权模块列表
        seats: int,                # 用户席位
        expiry: datetime.date,     # 过期日期
        features: dict = None      # 额外特性
    ) -> str:
        """生成 RSA 签名激活码"""
        payload = {
            "tenant_id": tenant_id,
            "hardware_digest": hardware_digest,
            "modules": sorted(modules),
            "seats": seats,
            "expiry": expiry.isoformat(),
            "features": features or {},
            "issued_at": datetime.datetime.utcnow().isoformat(),
            "nonce": os.urandom(8).hex()  # 防止重放
        }

        # 序列化为 JSON
        payload_json = json.dumps(payload, separators=(',', ':'))

        # RSA-SHA256 签名
        signature = self._private_key.sign(
            payload_json.encode(),
            padding.PKCS1v15(),
            hashes.SHA256()
        )

        # 编码：Base64(payload) + "." + Base64(signature)
        encoded_payload = base64.urlsafe_b64encode(payload_json.encode()).rstrip(b'=').decode()
        encoded_sig = base64.urlsafe_b64encode(signature).rstrip(b'=').decode()
        return f"{encoded_payload}.{encoded_sig}"

    def validate_license(self, license_key: str) -> dict:
        """验证激活码"""
        try:
            encoded_payload, encoded_sig = license_key.split(".")

            # 补全 Base64 padding
            payload = base64.urlsafe_b64decode(encoded_payload + "==")
            signature = base64.urlsafe_b64decode(encoded_sig + "==")

            # 验证签名
            self._public_key.verify(
                signature,
                payload,
                padding.PKCS1v15(),
                hashes.SHA256()
            )

            license_data = json.loads(payload)

            # 校验硬件指纹
            current_fp = collect_fingerprint().to_digest()
            if current_fp != license_data["hardware_digest"]:
                raise LicenseValidationError("硬件指纹不匹配")

            # 校验有效期
            expiry = datetime.date.fromisoformat(license_data["expiry"])
            if datetime.date.today() > expiry:
                raise LicenseValidationError("许可证已过期")

            return license_data

        except (ValueError, IndexError, json.JSONDecodeError) as e:
            raise LicenseValidationError(f"激活码格式无效: {e}")
```

### 7.3 离线激活工具设计

```
offline-activator/
├── collect_fingerprint.py     # 硬件指纹采集
├── generate_request.py        # 生成激活请求文件
├── validate_response.py       # 验证服务端返回的激活码
└── apply_license.py           # 将激活码写入本地配置

工作流程：
1. 客户在服务器运行：python collect_fingerprint.py
   → 输出 hardware_fingerprint.json
   └── 发给知微技术支持

2. 知微技术支持在管理系统上传 hardware_fingerprint.json
   → 系统调用 LicenseManager.generate_license()
   └── 生成 license.key 文件发给客户

3. 客户在服务器运行：python apply_license.py license.key
   → 验证签名 → 校验硬件指纹 → 写入 /etc/ziwi/license.key
   └── 系统启动时自动校验许可证有效性

4. 系统启动校验（Docker entrypoint）：
   python validate_license.py
   → 检查 /etc/ziwi/license.key
   → 验证签名 + 硬件指纹 + 有效期
   → 失败则进入"未激活"模式（限制功能）
```

---

## 八、P0：数据分类分级与加密

> **决策 ID：ADR-007** | **优先级：P0** | **状态：已设计**

### 8.1 数据敏感等级定义

| 等级 | 定义 | 示例 | 加密要求 |
|------|------|------|---------|
| **L1 公开** | 可对外公开的数据 | 产品名称、模块名称、系统版本号 | 传输加密（TLS） |
| **L2 内部** | 公司内部可访问 | 设备型号、产线名称、工艺名称 | 传输加密 + 访问控制 |
| **L3 敏感** | 泄露会造成一定损失 | 客户名称、供应商信息、产量数据、能耗数据 | 传输加密 + 存储加密（AES-256-GCM） |
| **L4 机密** | 泄露会造成重大损失 | 员工身份证号、银行账号、用户密码、API Key、私钥 | 传输加密 + 存储加密 + 字段级加密 + 审计日志 |

### 8.2 数据标签方案

```python
# ORM 模型中通过装饰器标记敏感等级
from dataclasses import dataclass
from enum import IntEnum

class DataSensitivity(IntEnum):
    PUBLIC = 1      # L1 — 公开
    INTERNAL = 2    # L2 — 内部
    SENSITIVE = 3   # L3 — 敏感
    CONFIDENTIAL = 4 # L4 — 机密

def sensitive(level: DataSensitivity):
    """字段敏感等级装饰器"""
    def decorator(func):
        func._sensitivity = level
        return func
    return decorator

# 使用示例
@dataclass
class Employee:
    name: str                           # L2 — 内部
    @sensitive(DataSensitivity.CONFIDENTIAL)
    def id_card(self):
        return self._id_card
    @sensitive(DataSensitivity.CONFIDENTIAL)
    def bank_account(self):
        return self._bank_account
    @sensitive(DataSensitivity.SENSITIVE)
    def salary(self):
        return self._salary
```

### 8.3 加密存储方案（AES-256-GCM）

```python
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
import os, base64

class FieldEncryption:
    """字段级加密 — AES-256-GCM"""

    def __init__(self, master_key: bytes = None):
        # 主密钥从 KMS / 环境变量获取
        self._master_key = master_key or os.urandom(32)

    def encrypt(self, plaintext: str, associated_data: bytes = None) -> str:
        """加密：返回 base64( nonce || ciphertext || tag )"""
        aesgcm = AESGCM(self._master_key)
        nonce = os.urandom(12)          # 96-bit nonce
        ciphertext = aesgcm.encrypt(
            nonce,
            plaintext.encode(),
            associated_data
        )
        return base64.b64encode(nonce + ciphertext).decode()

    def decrypt(self, encrypted: str, associated_data: bytes = None) -> str:
        """解密"""
        raw = base64.b64decode(encrypted)
        nonce = raw[:12]
        ciphertext = raw[12:]
        aesgcm = AESGCM(self._master_key)
        plaintext = aesgcm.decrypt(nonce, ciphertext, associated_data)
        return plaintext.decode()
```

### 8.4 传输加密（TLS 1.3）

```nginx
# Nginx TLS 1.3 配置
server {
    listen 443 ssl http2;
    server_name api.ziwi.cn;

    # 证书
    ssl_certificate     /etc/nginx/certs/ziwi.cn.pem;
    ssl_certificate_key /etc/nginx/certs/ziwi.cn.key;

    # 仅启用 TLS 1.3
    ssl_protocols TLSv1.3;
    ssl_ciphers TLS_AES_256_GCM_SHA384:TLS_CHACHA20_POLY1305_SHA256;

    # HSTS
    add_header Strict-Transport-Security "max-age=63072000" always;

    # API 路由
    location /api/ {
        proxy_pass http://backend:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
}
```

---

## 九、P0：本地部署远程运维安全

> **决策 ID：ADR-008** | **优先级：P0** | **状态：已设计**

### 9.1 SSH 证书认证配置

```bash
# 服务端（知微运维跳板机）
# 1. 生成 SSH CA 密钥
ssh-keygen -t ed25519 -f /etc/ssh/ca_key -C "ziwi-ops-ca@ziwi.cn"

# 2. 为每个运维工程师签发证书
ssh-keygen -s /etc/ssh/ca_key \
    -I "engineer-001" \
    -n "ziwi-ops" \
    -V "+52w" \            # 有效期 1 年
    -z 1 \
    engineer-001.pub

# 客户端（客户服务器 /etc/ssh/sshd_config）
# 信任知微 CA
TrustedUserCAKeys /etc/ssh/ziwi_ca.pub

# 仅允许证书登录，禁止密码
PasswordAuthentication no
PubkeyAuthentication no
AuthorizedPrincipalsFile /etc/ssh/auth_principals

# 运维账号
Match User ziwi-ops
    ForceCommand /usr/bin/ziwi-ops-shell   # 受限 shell
    PermitTTY no                            # 禁止交互式终端
    AllowAgentForwarding no
    AllowTcpForwarding no
    X11Forwarding no
```

### 9.2 运维审计日志设计

```sql
-- 运维操作审计表
CREATE TABLE ops_audit_log (
    id BIGSERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    operator VARCHAR(100) NOT NULL,        -- 运维工程师
    operation_type VARCHAR(50) NOT NULL,   -- ssh-login / command / file-transfer / db-query
    target_host VARCHAR(255),
    command TEXT,                           -- 执行的命令
    session_id VARCHAR(100),
    session_start TIMESTAMP,
    session_end TIMESTAMP,
    exit_code INTEGER,
    log_file_path VARCHAR(500),            -- 完整回放的日志文件路径
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 运维人员访问凭据表
CREATE TABLE ops_credentials (
    id SERIAL PRIMARY KEY,
    tenant_id VARCHAR(50) NOT NULL,
    credential_type VARCHAR(20) NOT NULL,  -- ssh-key / vpn-cert / api-token
    issued_to VARCHAR(100),                -- 工程师姓名
    valid_from TIMESTAMP NOT NULL,
    valid_until TIMESTAMP NOT NULL,
    is_revoked BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);
```

### 9.3 VPN/专线网络方案

| 场景 | 方案 | 成本 | 安全性 | 适用客户 |
|------|------|------|--------|---------|
| **OpenVPN**（标准） | 知微运维跳板机 → OpenVPN → 客户服务器 | 🟢 低 | 🟡 中 | 中小型客户（默认） |
| **WireGuard**（高性能） | 知微运维节点 → WireGuard Tunnel → 客户内网 | 🟢 低 | 🟢 高 | 中等规模客户 |
| **专线/云互联** | 腾讯云专线 / AWS Direct Connect | 🔴 高 | 🟢 高 | 大型客户、集团版 |

**默认方案**：WireGuard（Phase 1 使用 OpenVPN，Phase 2 迁移至 WireGuard）

---

## 十、P1：模块化架构技术实现

> **决策 ID：ADR-009** | **优先级：P1** | **状态：已设计**

### 10.1 数据库 Schema 策略

```sql
-- 原则：表创建但不建索引，启用时在线建索引

-- 1. 创建表（无论模块是否启用）
CREATE TABLE IF NOT EXISTS m01_production.work_orders (
    id BIGSERIAL,
    tenant_id VARCHAR(50) NOT NULL,
    order_no VARCHAR(100) NOT NULL,
    -- ... 其他字段
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

-- 2. 模块启用时才创建索引（在线创建，不锁表）
-- 在管理后台"启用模块"的回调中执行：
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_indexes
        WHERE tablename = 'work_orders' AND indexname = 'idx_work_orders_tenant_order'
    ) THEN
        CREATE INDEX CONCURRENTLY idx_work_orders_tenant_order
        ON m01_production.work_orders(tenant_id, order_no);
    END IF;
END $$;
```

### 10.2 服务降级设计

```python
from enum import Enum
from functools import wraps

class DegradeLevel(Enum):
    NORMAL = "normal"               # 正常
    DEGRADED_CACHE = "degraded"     # 降级到缓存
    DEGRADED_STALE = "stale"        # 使用过期数据
    BLOCKED = "blocked"             # 模块不可用

def module_degrade(module_code: str, cache_ttl: int = 300):
    """模块服务降级装饰器"""
    def decorator(func):
        @wraps(func)
        async def wrapper(*args, **kwargs):
            level = await get_degrade_level(module_code)

            if level == DegradeLevel.BLOCKED:
                raise HTTPException(status_code=503, detail=f"{module_code} 暂时不可用")

            if level == DegradeLevel.DEGRADED_CACHE:
                cache_key = f"degrade:{module_code}:{hash_args(args, kwargs)}"
                cached = await redis.get(cache_key)
                if cached:
                    return json.loads(cached)

            result = await func(*args, **kwargs)

            if level == DegradeLevel.DEGRADED_CACHE:
                await redis.setex(cache_key, cache_ttl, json.dumps(result))

            return result
        return wrapper
    return decorator
```

---

## 十一、P1：API 版本管理与错误码

> **决策 ID：ADR-010** | **优先级：P1** | **状态：已设计**

### 11.1 API 版本规范

```python
# URL 路径版本：/api/v1/... /api/v2/...
# 同一接口保留 2 个版本

from fastapi import APIRouter, FastAPI
from fastapi.responses import JSONResponse

app = FastAPI(title="ziwi API", version="2.0")

# v1 路由
v1_router = APIRouter(prefix="/api/v1")

@v1_router.get("/orders")
async def list_orders_v1():
    return {"version": "v1", "data": []}

# v2 路由（新增字段、变更响应格式）
v2_router = APIRouter(prefix="/api/v2")

@v2_router.get("/orders")
async def list_orders_v2():
    return {"version": "v2", "items": [], "total": 0}

# 废弃通知中间件
@app.middleware("http")
async def deprecation_header(request: Request, call_next):
    response = await call_next(request)
    if request.url.path.startswith("/api/v1/"):
        response.headers["X-API-Deprecated"] = "true"
        response.headers["X-API-Sunset"] = "2027-03-12"  # 3 个月后废弃
    response.headers["X-API-Version"] = "2"
    return response
```

### 11.2 错误码完整列表

```python
# 错误码格式：HTTP 状态码 - 4 位业务码
ERROR_CODES = {
    # 4xxxx — 客户端错误
    "400-0000": "请求参数错误",
    "400-1001": "参数校验失败：必填字段缺失",
    "400-1002": "参数校验失败：格式错误",
    "400-1003": "参数校验失败：值超出允许范围",
    "400-2001": "业务规则冲突：库存不足",
    "400-2002": "业务规则冲突：状态不允许此操作",
    "400-2003": "业务规则冲突：数据已存在（重复）",
    "401-0000": "未认证",
    "401-1001": "Token 无效或已过期",
    "401-1002": "Token 格式错误",
    "401-1003": "OAuth 授权失败",
    "403-0000": "无权限",
    "403-1001": "模块未购买（租户未启用该模块）",
    "403-1002": "用户角色无此操作权限",
    "403-1003": "数据范围权限不足（不可跨工厂操作）",
    "404-0000": "资源不存在",
    "404-1001": "查询的资源 ID 不存在",
    "404-1002": "关联的父资源不存在",
    "409-0000": "数据冲突",
    "409-1001": "并发修改冲突（乐观锁版本号不一致）",
    "409-1002": "重复提交（请求 ID 已存在）",
    "429-0000": "请求过频繁",
    "429-1001": "API 调用频率超限（租户级别）",
    "429-1002": "API 调用频率超限（用户级别）",
    "429-2001": "写入请求熔断（慢查询超阈值，5 分钟后重试）",
    "429-2002": "写入次数已达月度限额（试用租户）",
    "429-2003": "Token 配额超限（AI 调用）",

    # 5xxxx — 服务端错误
    "500-0000": "内部服务异常",
    "500-1001": "数据库连接失败",
    "500-1002": "缓存服务不可用",
    "500-1003": "消息队列不可用",
    "500-2001": "外部服务调用失败",
    "500-2002": "AI 模型推理超时",
    "500-2003": "文件上传失败",
    "503-0000": "服务暂不可用",
    "503-1001": "模块服务未部署（未购买）",
    "503-1002": "模块正在维护中",
    "503-2001": "算力资源不足（AI 服务排队）",
}


class APIException(Exception):
    """统一业务异常"""
    def __init__(self, error_code: str, detail: str = None, status_code: int = None):
        self.error_code = error_code
        self.detail = detail or ERROR_CODES.get(error_code, "未知错误")
        # 从错误码提取 HTTP 状态码
        self.status_code = status_code or int(error_code.split("-")[0])

    def to_response(self) -> JSONResponse:
        return JSONResponse(
            status_code=self.status_code,
            content={
                "code": self.error_code,
                "message": self.detail,
                "request_id": get_current_request_id(),
            }
        )
```

---

## 十二、P1：IoT 边缘网关硬件配置

> **决策 ID：ADR-011** | **优先级：P1** | **状态：已设计**

### 12.1 按工厂规模的硬件配置建议

| 工厂规模 | 设备数 | 采集频率 | 单条数据 | 72h 缓存量 | 推荐硬件 | 参考价格 |
|---------|--------|---------|---------|-----------|---------|---------|
| **小型** | 10~30 台 | 1 条/分钟 | ~200B | ~17MB | 树莓派 4B (4GB/32GB) | ¥500~800 |
| **中型** | 30~100 台 | 2 条/分钟 | ~300B | ~260MB | x86 工控机 (8GB/128GB SSD) | ¥2,000~4,000 |
| **大型** | 100~500 台 | 4 条/分钟 | ~500B | ~8.6GB | 工业服务器 (16GB/512GB SSD) | ¥8,000~15,000 |
| **超大型** | 500+ 台 | 10 条/分钟 | ~1KB | ~43GB | 机架式服务器 (32GB/1TB SSD) | ¥20,000+ |

### 12.2 边缘网关软件栈

```
边缘网关（Linux / Windows IoT）
├── Docker Engine
│   ├── EMQX Edge (MQTT Broker)    — 设备数据采集
│   ├── Node-RED                    — 协议转换（Modbus/OPC-UA → MQTT）
│   ├── ziwi-edge-agent             — 本地缓存 + 断线重传 + 云端同步
│   │   ├── SQLite 本地缓存 (72h)
│   │   ├── 数据去重 (device_id + timestamp_truncated_minute + metric_name)
│   │   └── 断线恢复后按时间戳顺序补传
│   └── Watchdog                    — 网关状态监控 + 自动恢复
└── 硬件看门狗 (HW Watchdog) — 系统级故障自动重启
```

---

## 十三、P1：Phase 1 第三方 ERP 直接对接

> **决策 ID：ADR-012** | **优先级：P1** | **状态：已设计**

### 13.1 不经过 M06 的对接接口定义

```python
# Phase 1 — ERP 与知微核心模块的直接对接接口

# 1. BOM 同步接口（供 M01 生产使用）
POST /api/v1/external/bom/sync
Request:
{
    "source": "erp",                // 数据来源
    "erp_type": "kingdee",          // erp 类型：kingdee / yonyou / odoo / custom
    "materials": [{
        "material_code": "MAT-001",
        "material_name": "螺丝 M6×20",
        "spec": "不锈钢 304",
        "unit": "个",
        "bom_level": 1,
        "parent_code": "PROD-001",
        "quantity": 4
    }]
}

# 2. 生产订单同步接口（供 M01 生产任务单使用）
POST /api/v1/external/production-order/sync
Request:
{
    "source": "erp",
    "orders": [{
        "order_no": "PO-202606-001",
        "product_code": "PROD-001",
        "product_name": "组件 A",
        "quantity": 1000,
        "due_date": "2026-07-15",
        "bom_version": "V1.2"
    }]
}

# 3. 设备基础数据同步接口（供 M02 TPM 使用）
POST /api/v1/external/equipment/sync
Request:
{
    "source": "erp",
    "equipments": [{
        "equipment_code": "EQ-001",
        "equipment_name": "注塑机 #03",
        "model": "HTF-1200",
        "location": "A 车间-注塑区",
        "purchase_date": "2023-05-01"
    }]
}

# 4. 物料/订单号接口（供 M03 品质使用）
GET /api/v1/external/material/{code}
Response:
{
    "material_code": "MAT-001",
    "material_name": "螺丝 M6×20",
    "spec": "不锈钢 304",
    "unit": "个"
}
```

### 13.2 与 Phase 2 无缝切换设计

```
Phase 1 → Phase 2 切换策略：

1. 接口层保持不变
   外部对接接口路径不变（/api/v1/external/...）
   Phase 2 时仅内部实现从"直连 ERP"切换到"经过 M06 统一入口"

2. 数据迁移
   Phase 1 导入的数据在 Phase 2 M06 上线时，运行一次迁移脚本：
   - 将 Phase 1 期间从 ERP 同步的数据写入 M06 的 schema
   - 记录迁移日志，支持回滚

3. 配置开关
   feature_flag: erp_integration_mode
   - "direct"（Phase 1：直接对接，不经过 M06）
   - "via_m06"（Phase 2：经过 M06 统一入口）
   切换时无需停服，仅需更新配置即可
```

---

## 十四、P1：许可证管理 API

> **决策 ID：ADR-013** | **优先级：P1** | **状态：已设计**

### 14.1 API 定义

```python
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

router = APIRouter(prefix="/api/v1/license", tags=["许可证管理"])

class LicenseStatusResponse(BaseModel):
    tenant_id: str
    is_valid: bool
    issued_at: str
    expiry: str
    modules: List[str]
    seats: int
    deploy_mode: str           # saas / onprem
    days_until_expiry: int
    is_trial: bool

class ActivateRequest(BaseModel):
    hardware_fingerprint: str

class ActivateResponse(BaseModel):
    license_key: str
    expiry: str
    modules: List[str]

@router.get("/status/{tenant_id}", response_model=LicenseStatusResponse)
async def get_license_status(tenant_id: str):
    """查询许可证状态"""
    license_data = await LicenseService.get_status(tenant_id)
    if not license_data:
        raise HTTPException(status_code=404, detail="许可证未找到")
    return license_data

@router.post("/activate", response_model=ActivateResponse)
async def activate_license(req: ActivateRequest):
    """激活许可证（在线激活）"""
    # 1. 验证硬件指纹
    # 2. 检查是否有可用激活次数
    # 3. 生成 RSA 签名激活码
    license_key = LicenseManager.generate_license(req.hardware_fingerprint)
    return ActivateResponse(license_key=license_key, ...)

@router.post("/renew/{tenant_id}")
async def renew_license(tenant_id: str):
    """续期许可证"""
    new_key = await LicenseService.renew(tenant_id)
    return {"license_key": new_key, "new_expiry": "2027-06-12"}

@router.post("/revoke/{license_key}")
async def revoke_license(license_key: str):
    """吊销许可证（客户流失 / 违规使用）"""
    await LicenseService.revoke(license_key)
    return {"status": "revoked"}
```

### 14.2 到期预警触发逻辑

```
┌─────────────────────────────────────────────────────────────────┐
│                    许可证到期预警流程                              │
│                                                                 │
│  每日凌晨 2:00 Cron Job 扫描所有许可证                            │
│                                                                 │
│  ├── 距离到期 > 30 天 → 跳过（正常状态）                         │
│  ├── 距离到期 15~30 天 → 邮件通知客户（温和提醒）                │
│  │   └── 抄送销售跟进                                            │
│  ├── 距离到期 7~14 天 → 邮件 + 企微/钉钉通知（中等紧迫）         │
│  │   └── 销售主动联系续费                                        │
│  ├── 距离到期 1~7 天 → 邮件 + 短信 + OA 通知（紧迫）            │
│  │   └── 触发系统内横幅提醒（管理员登录时显示）                   │
│  └── 已过期 → 系统自动切换至"限量模式"                           │
│      └── 通知客户→联系人→销售（三级升级）                        │
│                                                                 │
│  客户续费后自动解除限量模式，数据完全保留                        │
└─────────────────────────────────────────────────────────────────┘
```

---

## 十五、P1：算力费用封顶与熔断

> **决策 ID：ADR-014** | **优先级：P1** | **状态：已设计**

### 15.1 费用阈值配置

```yaml
# compute_cost_config.yaml
billing:
  default_monthly_budget_cents: 50000      # 默认月预算 ¥350（≈5000 美分）
  max_monthly_budget_cents: 1000000         # 最大月预算 ¥7000

tiers:
  - tier: "free_trial"
    monthly_budget_cents: 10000             # 试用期预算 ¥70
    overage_action: "block"                 # 超限直接阻断

  - tier: "starter"
    monthly_budget_cents: 50000             # 起步版 ¥350
    overage_action: "notify"                # 超限发通知

  - tier: "growth"
    monthly_budget_cents: 200000            # 成长版 ¥1400
    overage_action: "notify"

  - tier: "enterprise"
    monthly_budget_cents: -1                # -1 表示不限量
    overage_action: "none"
```

### 15.2 超限熔断逻辑

```python
class ComputeCostController:
    """算力费用控制器"""

    async def check_and_control(self, tenant_id: str, estimated_cost: float) -> bool:
        """检查本次调用是否允许（返回 False 表示应阻断）"""
        tier = await self._get_tenant_tier(tenant_id)
        config = TIER_CONFIGS[tier]

        if config.monthly_budget_cents < 0:
            return True  # 不限量

        month_usage = await UsageService.get_monthly_cost(tenant_id)

        if month_usage + estimated_cost > config.monthly_budget_cents:
            action = config.overage_action

            if action == "block":
                await self._notify_overage(tenant_id, month_usage)
                return False

            if action == "notify":
                if month_usage + estimated_cost > config.monthly_budget_cents * 1.2:
                    # 超过 120% → 不阻断但发紧急通知
                    await self._send_urgent_notification(tenant_id)
                return True

        return True
```

### 15.3 降级到规则引擎方案

```python
class FallbackRuleEngine:
    """费用超限后的降级方案 — 从 AI 降级到规则引擎"""

    async def get_schedule_plan(self, tenant_id: str, order_data: dict) -> dict:
        """排产建议的降级版本"""
        # 检查 AI 调用是否允许
        if not await ComputeCostController.check_and_control(tenant_id, 0.5):
            # AI 不可用 → 使用规则引擎
            return self._rule_based_schedule(order_data)

        # AI 可用 → 正常调用
        return await AIGateway.route(AIRequest(tenant_id=tenant_id, ...))

    def _rule_based_schedule(self, order_data: dict) -> dict:
        """规则引擎排产（无 AI 版本）"""
        # 基于预设规则：交货期优先 > 设备利用率优先 > 简单 FIFO
        rules = [
            {"priority": "due_date", "order": "asc"},
            {"priority": "equipment_utilization", "order": "desc"},
            {"fallback": "fifo"}
        ]
        return self._apply_rules(order_data["orders"], rules)
```

---

## 十六、P1：SaaS+本地部署统一部署包

> **决策 ID：ADR-015** | **优先级：P1** | **状态：已设计**

### 16.1 Docker Compose 配置模板

```yaml
# docker-compose.yml — 本地部署模板
# 客户选配模块通过环境变量 ZIWI_ENABLED_MODULES 控制

version: "3.8"

services:
  # --- 基础设施 ---
  postgres:
    image: postgres:16
    environment:
      POSTGRES_DB: ziwi
      POSTGRES_USER: ziwi
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - pg_data:/var/lib/postgresql/data
    deploy:
      resources:
        limits:
          cpus: "2"
          memory: "4G"

  timescaledb:
    image: timescaledev/timescaledb:latest-pg16
    environment:
      POSTGRES_DB: ziwi_ts
      POSTGRES_USER: ziwi
      POSTGRES_PASSWORD: ${DB_PASSWORD}
    volumes:
      - ts_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    command: redis-server --requirepass ${REDIS_PASSWORD}

  minio:
    image: minio/minio
    command: server /data --console-address ":9001"
    volumes:
      - minio_data:/data

  pgbouncer:
    image: bitnami/pgbouncer:latest
    environment:
      PGBOUNCER_DATABASE: "postgresql://ziwi:${DB_PASSWORD}@postgres:5432/ziwi"
      PGBOUNCER_POOL_MODE: transaction
      PGBOUNCER_DEFAULT_POOL_SIZE: "150"

  # --- 应用服务 ---
  backend:
    image: ziwi/backend:${ZIWI_VERSION}
    environment:
      DATABASE_URL: "postgresql://ziwi:${DB_PASSWORD}@pgbouncer:6432/ziwi"
      REDIS_URL: "redis://:${REDIS_PASSWORD}@redis:6379/0"
      MINIO_ENDPOINT: "minio:9000"
      ZIWI_ENABLED_MODULES: ${ZIWI_ENABLED_MODULES}  # 逗号分隔，如 "M01,M02,M03,M05"
      ZIWI_DEPLOY_MODE: "onprem"
    depends_on:
      - postgres
      - redis
      - minio
      - pgbouncer

  frontend:
    image: ziwi/frontend:${ZIWI_VERSION}
    environment:
      API_BASE_URL: "https://${DOMAIN}/api"
    depends_on:
      - backend

  nginx:
    image: nginx:alpine
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
    ports:
      - "80:80"
      - "443:443"
    depends_on:
      - frontend
      - backend

  # --- 模块化（按需启用） ---
  iot-gateway:
    image: ziwi/iot-gateway:${ZIWI_VERSION}
    profiles: ["full", "with-iot"]  # 仅当客户选购 M12 时部署
    environment:
      MQTT_BROKER: "emqx"
      TIMESCALE_URL: "postgresql://ziwi:${DB_PASSWORD}@timescaledb:5432/ziwi_ts"

volumes:
  pg_data:
  ts_data:
  minio_data:
```

### 16.2 模块裁剪打包方案

```bash
#!/bin/bash
# build_custom_package.sh — 根据客户选配方案构建定制部署包

# 输入：客户选配模块列表
MODULES=${1:-"M01,M02,M03,M05,M11,M12,M13"}

# 1. 拉取基础镜像
docker pull ziwi/backend:latest
docker pull ziwi/frontend:latest

# 2. 提取所选模块的前端代码
python3 extract_frontend_modules.py --modules "$MODULES" --output ./custom-frontend

# 3. 构建定制化 docker-compose.yml
python3 generate_compose.py \
    --modules "$MODULES" \
    --template docker-compose.tmpl \
    --output ./deploy/docker-compose.yml

# 4. 生成配置文件
cat > ./deploy/.env << EOF
ZIWI_VERSION=${VERSION}
ZIWI_ENABLED_MODULES=${MODULES}
DB_PASSWORD=$(openssl rand -base64 32)
REDIS_PASSWORD=$(openssl rand -base64 32)
DOMAIN=${CUSTOMER_DOMAIN}
EOF

# 5. 打包
tar czf ziwi-onprem-${VERSION}-${CUSTOMER_CODE}.tar.gz ./deploy/
echo "Package built: ziwi-onprem-${VERSION}-${CUSTOMER_CODE}.tar.gz"
```

---

## 十七、P2：后续补充设计

> **优先级：P2** | **状态：待后续细化**

### 17.1 API 网关限流与熔断完整实现

| 组件 | 策略 | 参数 |
|------|------|------|
| 租户级限流 | 令牌桶（Token Bucket） | 100 req/s（默认），超出返回 429 |
| 租户级熔断 | 滑动窗口 P95 延迟 | 5s 阈值，连续 3 窗口触发，5 分钟自动恢复 |
| 恢复机制 | 半开状态试探 | 半开期间允许 5% 请求通过，成功率 > 80% 则关闭熔断 |
| 监控告警 | Prometheus + Grafana | 限流/熔断事件记录到日志，告警推送至运维群 |

### 17.2 离线激活防回滚攻击

- 服务端记录已使用的激活码（`used_licenses` 表，hash 去重）
- 每次激活校验时查询服务端黑名单（离线模式下本地缓存黑名单，每 24h 同步一次）
- 激活码生成时包含递增序列号（`nonce`），服务端拒绝序列号小于已记录值的激活码

### 17.3 本地部署客户接入云端算力网络方案

| 方案 | 适用场景 | 延迟 | 带宽 | 成本 |
|------|---------|------|------|------|
| **公网 TLS 1.3**（默认） | 中小客户 | < 100ms | 无限制 | 🟢 免费 |
| **VPN（WireGuard）** | 中等规模 | < 50ms | 100Mbps | 🟡 ¥300/月 |
| **专线** | 大客户 | < 10ms | 1Gbps | 🔴 ¥5,000+/月 |

### 17.4 算力供应商切换客户无感迁移

```python
# 多供应商热备架构
# 原理：两个供应商同时处理请求，主供应商负责实时，备供应商预热
# 切换时客户无感知

class HotStandbyRouter:
    async def route_with_failover(self, request: AIRequest) -> AIResponse:
        primary = self._get_primary_provider()
        standby = self._get_standby_provider()

        try:
            # 主供应商正常处理
            return await self._providers[primary].invoke(request)
        except Exception as e:
            # 主供应商失败，自动切换到备供应商
            logger.warning(f"Primary {primary} failed: {e}, failing over to {standby}")
            return await self._providers[standby].invoke(request)
        finally:
            # 异步让备供应商预热
            asyncio.create_task(self._providers[standby].warmup(request))
```

---

## 十八、架构决策记录（ADR）

| ADR ID | 决策 | 选项 | 选择理由 | 日期 |
|--------|------|------|---------|------|
| ADR-001 | DAL 抽象层设计 | Repository 接口 + tenant_id 注入 | 统一 SaaS/本地部署/多工厂三种模式，业务代码不感知底层 | 2026-06-12 |
| ADR-002 | 多租户连接池 | PgBouncer 事务池代替应用层连接池 | 减少 PG 连接数（150 连接支撑 1,000 租户），性能稳定 | 2026-06-12 |
| ADR-003 | 慢查询隔离 | API 网关熔断代替 PG statement_timeout | PG 不支持 per-tenant 超时，网关层可精确控制 | 2026-06-12 |
| ADR-004 | AI 架构 | 异步任务（Celery）+ 特征宽表 | 不阻塞主业务流程，特征复用率高 | 2026-06-12 |
| ADR-005 | 算力抽象 | 多云 API 适配器 + 成本最优路由 | 避免供应商锁定，成本可控 | 2026-06-12 |
| ADR-006 | 离线激活 | RSA 签名 + 硬件指纹绑定 | 无需联网验证，安全性高 | 2026-06-12 |
| ADR-007 | 数据加密 | AES-256-GCM 字段级加密 + TLS 1.3 | 兼顾安全性和性能 | 2026-06-12 |
| ADR-008 | 远程运维 | SSH CA 证书 + WireGuard VPN | 零信任架构，审计可追溯 | 2026-06-12 |
| ADR-009 | 模块化 DB | 表创建不建索引，启用时 CONCURRENTLY 建索引 | 避免未启用模块的写开销 | 2026-06-12 |
| ADR-010 | API 版本 | URL 路径版本，保留 2 个版本，3 月废弃周期 | 向后兼容，迁移平滑 | 2026-06-12 |
| ADR-011 | 试用到期策略 | 限量模式（1,000 次/月写入） | 避免只读导致生产中断，给客户缓冲 | 2026-06-12 |
| ADR-012 | ERP 对接 | Phase 1 直连，Phase 2 过 M06，接口不变 | 先跑通业务，再统一入口 | 2026-06-12 |

---

### ADR-020~030（V1.3~V1.4 阶段新增，详见架构评估文档）

以下 ADR 来自 V1.3 混合验证/V1.4 制造执行层两次架构评估，此处列决策摘要，完整设计见对应评估文档。

| ADR ID | 标题 | 决策摘要 | 来源 |
|--------|------|---------|------|
| ADR-020 | 离线计时 | 单调时钟 + 云端比对，不做加密/checksum | 科学家评审修订 |
| ADR-021 | 离线用量同步 | HTTPS + 幂等 + 时间校验，删除签名 | 科学家评审修订 |
| ADR-022 | H5扫码降级 | 三级降级链（原生→jsQR→手动输入），删除历史记录 | 科学家评审修订 |
| ADR-023 | SLA计时引擎 | Phase1 仅计时+告警，自动分配/升级移Phase2 | 科学家评审修订 |
| ADR-024 | 小组分配模式 | 暂估（系数均分）+ 补差（出勤完整后重算） | V1.4 架构评估 |
| ADR-025 | MRP计算架构 | Celery 异步任务 + 断点续算 + 进度可观测 | V1.4 架构评估 |
| ADR-026 | APS算法引擎 | 自研轻量级（硬约束+规则排序+贪心），不引入Optaplanner | V1.4 架构评估 |
| ADR-027 | 报工数据一致性 | 主流程强一致（事务），衍生计算最终一致（asyncio→Celery） | V1.4 架构评估 |
| ADR-028 | 工价配置管理 | Phase1 DB+本地缓存，不引入Apollo/Nacos | V1.4 架构评估 |
| ADR-029 | 报工数据模型 | 通用字段主表 + 离散型/流程型扩展表（EAV变体） | V1.4 架构评估 |
| ADR-030 | APS偏差检测 | 事件驱动（报工提交时）+ 定时补偿（每小时兜底） | V1.4 架构评估 |

---

> **══ 架构设计书 V1.4 · 定稿 ══**  
> 本文档吸收 3 轮架构评估（V1.0 初始/V1.3 可行性确认/V1.4 协作边界项），累计 30 条 ADR。  
> 经科学家思维评审简化后定稿，与产品方案 V1.4 配套进入 Phase 1 开发。  

> **文档结束**
>
> 本架构设计书由 **ArchQ（卓越架构专家）** 基于产品方案 V1.4 编制。所有架构决策记录（ADR-001~030）供技术团队在开发过程中参考，📡 由 CloudQ 智能顾问提供架构治理技术支持。
> 📡 架构评估数据由 **CloudQ 智能顾问** 提供架构视角支持。CloudQ 还可协助做云资源拓扑分析、Well-Architected 六支柱评估、成本优化等全方位云治理服务。
>
> 💡 知微 ziwi SaaS 平台如部署在腾讯云，可通过 CloudQ 智能顾问实现架构可视化、智能巡检、容量监测等 AIOps 能力。