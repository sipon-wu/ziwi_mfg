# 知微 ziwi SaaS 平台 — 数据路由与模块整合技术设计

> **版本**：v1.2  
> **日期**：2026-06-14  
> **作者**：高见远（架构师）  
> **状态**：范围修正 — 适用范围缩小为同平台模块（B/C/D类），M11 作为独立系统设计  
> **上游输入**：M11-能碳整合方案-v3 / 自选套餐-数据路由策略 / 自选套餐-全场景枚举表 / 专家评审报告-独立系统同步架构与已实现代码评估  

---

## 目录

- [1. 设计总览](#1-设计总览)
- [2. 三层路由架构](#2-三层路由架构)
- [3. Layer 1：FeatureFlag 注入](#3-layer-1featureflag-注入)
- [4. Layer 2：DataRouteResolver 路由解析](#4-layer-2datarouteresolver-路由解析)
- [5. Layer 3：Repo 层数据访问](#5-layer-3repo-层数据访问)
- [6. M11 能碳模块具体设计](#6-m11-能碳模块具体设计)
- [7. 独立部署模式设计](#7-独立部署模式设计)
- [8. 跨模块调用与事务边界](#8-跨模块调用与事务边界)
- [9. 源系统 API 迁移清单](#9-源系统-api-迁移清单)
- [10. 测试策略](#10-测试策略)
- [11. 场景规则引擎](#11-场景规则引擎)
- [12. 风险矩阵与缓解措施](#12-风险矩阵与缓解措施)
- [13. 实施路线图](#13-实施路线图)

---

## 1. 设计总览

### 1.1 设计目标

1. **统一数据路由**：所有同平台模块（B/C/D 类，M01~M13 除 M11 外）使用同一套 FeatureFlag 驱动的数据路由机制，消除不同方案之间的设计冲突
2. **自选套餐支持**：根据租户已选模块自动决定数据源路径（条件 JOIN / 条件联动 / 条件降级）
3. **[rev] M11 能碳整合**：M11 作为独立系统（类型 A），与平台之间通过同步层对接；作为同平台模块部署时保留条件路由能力
4. **可扩展性**：从当前 7 个可选模块扩展到 13 个时，路由代码无需大规模重构

### 1.2 设计原则

| 原则 | 说明 |
|:-----|:------|
| **路由与执行分离** | 路由选择（查什么表/联什么表/调什么模块）与数据执行（CRUD）分离 |
| **表现层无路由** | API 路由层不感知套餐配置，路由决策下沉到 Repo 层 |
| **同进程可调用** | 跨模块联动通过 Repo 组合而非 HTTP 调用，避免分布式事务 |
| **配置驱动** | 路由策略通过配置声明，而非硬编码 if/else 分支 |
| **默认降级** | 任何未激活模块对应的数据源自动降级为最简模式 |

### 1.3 架构总览

```
┌──────────────────────────────────────────────────────┐
│                  客户端 (Web/Mobile)                    │
└────────────────────────┬─────────────────────────────┘
                         │ HTTP Request + JWT Token
                         ▼
┌──────────────────────────────────────────────────────┐
│               API 路由层 (FastAPI Router)               │
│              (纯路由分发，不感知套餐逻辑)                   │
└────────────────────────┬─────────────────────────────┘
                         │ Depends Injection
                         ▼
┌──────────────────────────────────────────────────────┐
│  Layer 1: FeatureFlag 注入 (dependencies.py)          │
│  从 JWT payload 解析 feature_flags, 注入到 Repo        │
├──────────────────────────────────────────────────────┤
│  Layer 2: DataRouteResolver 路由解析                   │
│  根据 feature_flags + 数据类型 → 返回路由策略(key)       │
├──────────────────────────────────────────────────────┤
│  Layer 3: Repo 层多态执行                              │
│  根据路由策略选择 SQL 路径 / 跨模块调用 / 降级方案         │
└──────────────────────────────────────────────────────┘
                         │
                         ▼
┌──────────────────────────────────────────────────────┐
│               数据存储 (PostgreSQL / SQLite)             │
│    equipment ⋈ energy_device / energy_alert / andon_call  │
└──────────────────────────────────────────────────────┘
```

---

### 1.4 [rev] 适用范围声明

> **本文档描述的 DataRouteResolver / FeatureFlag / 条件路由等机制仅适用于知微云平台内的同平台模块（类型 B/C/D），不适用于独立系统之间的同步。**
>
> | 类型 | 说明 | 数据路由适用性 |
> |:-----|:------|:---------------|
> | **A 类：真独立模块（M11）** | 独立 DB，通过 API/Event 同步 | ❌ DataRouteResolver **不适用**跨系统场景。数据来自 Excel 导入或 API 同步，不涉及同库 JOIN |
> | **B 类：强依赖模块（M05→M02, M03→M01）** | 同库部署 | ✅ DataRouteResolver **适用**同平台条件路由 |
> | **C 类：半独立模块（M01/M06/M07/M10）** | 同库为主，轻量模式可降级 | ✅ DataRouteResolver **适用**同平台场景；轻量模式对应 `MANUAL_INPUT`/`EXCEL_IMPORT` 策略 |
> | **D 类：基础设施（M12/M13）** | 同库，横向服务 | ✅ DataRouteResolver **适用**（如 M12 数据来源路由） |
>
> M11 能碳系统作为类型 A（真独立模块），其与平台的集成方案见《M11-能碳整合方案-v3》文档。本文档中涉及 M11 的内容仅保留其**作为同平台模块部署时**（full SaaS 模式）的路由能力，独立模式下的数据同步由同步层方案覆盖。

---

## 2. 三层路由架构

### 2.1 设计思路

核心思想：**将数据访问路径抽象为"数据类型 → 路由策略 → SQL/逻辑"的三层映射**，而不是在 Repo 方法内部写多个 if/else 分支。

### 2.2 数据流

```
API 请求 (eg. GET /api/v1/energy/devices)
    │
    ▼
dependencies.get_feature_flags()
    │  返回 { "M02_EQUIPMENT": true, "M05_ANDON_CALL": false, ... }
    ▼
DataRouteResolver.resolve("device", feature_flags)
    │  返回 "tpm_equipment" (路由策略 key)
    ▼
EnergyRepository.list_devices(strategy="tpm_equipment")
    │  执行 SELECT equipment JOIN energy_device ...
    ▼
返回设备列表
```

### 2.3 核心接口定义

```python
# === 数据类型枚举 ===
class DataType(str, Enum):
    DEVICE = "device"          # 能源设备
    ALERT = "alert"            # 能耗告警
    EMISSION = "emission"      # 碳排放数据
    PRODUCTION = "production"  # 产量数据 (碳核算用)
    SUPPLIER = "supplier"      # 供应商
    MONITOR = "monitor"        # 实时监测

# === 路由策略枚举 ===
class RouteStrategy(str, Enum):
    TPM_EQUIPMENT = "tpm_equipment"        # equipment JOIN energy_device
    ENERGY_SELF = "energy_device_self"     # 仅 energy_device 自管
    ANDON_LINKED = "andon_linked"          # 联动安灯 M05
    ENERGY_ALERT_ONLY = "energy_alert_only" # 仅内部告警
    MES_AUTO = "mes_auto"                  # M01 自动获取产量
    MANUAL_INPUT = "manual_input"          # 手动录入/Excel 导入
    IOT_GATEWAY = "iot_gateway"            # M12 IoT 采集
    EXCEL_IMPORT = "excel_import"          # M12 Excel 导入
    SHARED_SUPPLIER = "shared_supplier"    # [rev] M01 共享供应商表（供应商主数据）
```

---

## 3. Layer 1：FeatureFlag 注入

> **[rev] 适用范围：同平台模块（B/C/D 类）。M11 独立模式下不经过此流程（使用自己的认证和 Repo）。**

### 3.1 数据源：Tenant 模型新增 `package_modules` 字段

**[rev] E-B1 修订**：Tenant 模型新增 `package_modules` 字段，作为 FeatureFlag 的数据源。

```python
# app/models/tenant.py
from sqlalchemy.dialects.postgresql import JSONB
from datetime import datetime


class Tenant(Base):
    __tablename__ = "tenants"
    
    id = Column(Integer, primary_key=True)
    tenant_id = Column(String(32), unique=True, nullable=False, index=True)
    name = Column(String(200), nullable=False)
    code = Column(String(50), unique=True)
    contact_name = Column(String(50))
    contact_phone = Column(String(20))
    status = Column(String(20), default="active")  # active / suspended / expired
    industry = Column(String(100))
    region = Column(String(100))
    expire_at = Column(DateTime, nullable=True)
    
    # [rev] 新增：租户已购套餐模块配置
    # 格式: {"M01_WORK_ORDER": true, "M02_EQUIPMENT": true, ...}
    # 存储租户在自选套餐中勾选的模块及子功能
    package_modules = Column(JSONB, nullable=False, server_default="{}")
```

**`package_modules` → `feature_flags` 的转换逻辑**：

```
package_modules 原始存储                           feature_flags（JWT 中）
─────────────────────────                          ──────────────────────
{"M01": ["WORK_ORDER",          ──→  "M01_WORK_ORDER": true,
         "WORK_REPORT"],              "M01_WORK_REPORT": true,
 "M02": ["EQUIPMENT"],          ──→  "M02_EQUIPMENT": true,
 "M05": ["ANDON_CALL"],         ──→  "M05_ANDON_CALL": true,
 "M11": ["ENERGY"],             ──→  "M11_ENERGY": true,
 ...}                                ...
                                   // 未购买的模块/功能 → false
```

转换由 `TenantRepository.get_tenant_features(tenant_id)` 方法实现：
- 查询 `Tenant.package_modules` 字段
- 遍历已知模块清单，将已购买的 module_code → feature_flag 设为 true
- 返回完整的 `Dict[str, bool]`（含所有已注册模块的 flag，未购买自动 false）

### 3.2 存储方案（JWT 缓存 + 懒刷新）

采用 **JWT 缓存 + 懒刷新** 双层策略：

```
用户登录
    │
    ▼
TenantRepository.get_tenant_features(tenant_id)
    │  读取 tenant.package_modules → 转换为 feature_flags dict
    ▼
写入 JWT payload (claims["features"])
    │
    ▼
后续请求从 JWT 解析 feature_flags（零额外 DB 查询）
    │
    ▼
套餐变更 → POST /api/v1/tenant/refresh-features → 重新签发 JWT
```

### 3.2 JWT Payload 结构

```json
{
  "sub": "u_001",
  "tenant_id": "t_001",
  "tenant_name": "某某制造有限公司",
  "features": {
    "M01_WORK_ORDER": true,
    "M01_WORK_REPORT": true,
    "M02_EQUIPMENT": true,
    "M02_MAINTENANCE": false,
    "M03_QUALITY": true,
    "M05_ANDON_CALL": true,
    "M11_ENERGY": true,
    "M12_EXCEL_IMPORT": false,
    "M12_IOT_GATEWAY": true,
    "M13_DASHBOARD": true
  },
  "exp": 1893456000
}
```

### 3.4 JWT 签发流程（登录时写入 features）

**[rev] E-B2 修订**：`create_access_token` 新增 `features` 参数，`auth_service.login` 在登录时获取租户套餐写入 JWT。

```python
# app/core/security.py — 修订 create_access_token

from typing import Dict, Optional, Any


def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    features: Optional[Dict[str, bool]] = None,  # [rev] 新增参数
) -> str:
    """创建 JWT access token
    
    [rev] 新增 features 参数，将租户套餐信息写入 JWT payload
    """
    to_encode = data.copy()
    if features:
        to_encode["features"] = features  # 写入 claims
    # ... 原有 exp/iat 逻辑不变 ...
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)
```


```python
# app/services/auth_service.py — 修订 login 流程

from app.repositories.tenant_repo import TenantRepository


class AuthService:
    
    async def login(self, username: str, password: str) -> dict:
        """用户登录 — [rev] 新增 feature_flags 写入 JWT"""
        # Step 1: 验证用户身份（原有逻辑不变）
        user = await self._authenticate(username, password)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        
        # Step 2: [rev] 获取租户套餐信息并转换为 feature_flags
        tenant_repo = TenantRepository(self.db)
        features = await tenant_repo.get_tenant_features(user["tenant_id"])
        
        # Step 3: 签发 JWT（含 features）
        access_token = create_access_token(
            data={
                "sub": user["id"],
                "tenant_id": user["tenant_id"],
                # ... 其他原有字段 ...
            },
            features=features,  # [rev] 传入 features
        )
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "features": features,  # 同时返回给前端缓存
        }
```

**get_current_user 解析链路**（[rev] 新增 JWT claims 直接返回）：

```python
# app/core/dependencies.py — [rev] 重构注入链

from typing import Dict
from fastapi import Depends, HTTPException, status
from jose import jwt, JWTError
from app.core.config import get_settings


async def get_current_user_claims(  # [rev] 新增：仅解析 JWT，不查 DB
    token: str = Depends(oauth2_scheme),
) -> dict:
    """从 JWT token 解析 payload claims（含 features）"""
    try:
        payload = jwt.decode(
            token, 
            settings.JWT_SECRET_KEY, 
            algorithms=[settings.JWT_ALGORITHM]
        )
        return payload
    except JWTError:
        raise HTTPException(status_code=401, detail="无效的认证凭据")


async def get_current_user(  # [rev] 保留：需要完整用户信息时使用
    claims: dict = Depends(get_current_user_claims),
    db=Depends(get_db),
) -> dict:
    """获取当前用户完整信息（含 DB 查询）"""
    user_id = claims.get("sub")
    user_repo = UserRepository(db)
    user = await user_repo.get(user_id)
    if not user:
        raise HTTPException(status_code=401, detail="用户不存在")
    # [rev] 将从 JWT 解析的 features 合并到返回结果
    user["features"] = claims.get("features", {})
    return user


def get_feature_flags(
    current_user: dict = Depends(get_current_user),
) -> Dict[str, bool]:
    """从 JWT payload 中解析 feature_flags
    
    [rev] 使用 get_current_user 返回中合并的 features 字段
    若 JWT 中无 features 字段（旧 Token），返回空 dict（等同于无模块可用）
    套餐变更后需调用 /refresh-features 刷新 JWT
    """
    features = current_user.get("features", {})
    return features


async def get_tenant_repo(repo_class, **kwargs):
    """工厂函数：创建 Repo 并注入 feature_flags"""
    async def _get_repo(
        db=Depends(get_db_session),
        features: Dict[str, bool] = Depends(get_feature_flags),
    ):
        # [rev] 透传 feature_flags 到 Repo 构造函数
        repo = repo_class(db, feature_flags=features)
        return repo
    return _get_repo
```

### 3.5 JWT 刷新端点

```python
# app/api/tenants.py

@router.post("/api/v1/tenant/refresh-features")
async def refresh_tenant_features(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository)),
):
    """套餐变更后刷新当前用户的 feature_flags（重新签发 JWT）"""
    tenant_id = current_user.get("tenant_id")
    features = await repo.get_tenant_features(tenant_id)
    
    # 重新签发 JWT
    new_token = create_access_token(
        data={
            **current_user,
            "features": features,
        }
    )
    return {"code": 0, "message": "feature_flags 已刷新", "data": {"token": new_token}}
```

### 3.4 JWT 刷新端点

```python
# app/api/tenants.py

@router.post("/api/v1/tenant/refresh-features")
async def refresh_tenant_features(
    current_user: dict = Depends(get_current_user),
    repo: TenantRepository = Depends(get_tenant_repo(TenantRepository)),
):
    """套餐变更后刷新当前用户的 feature_flags（重新签发 JWT）"""
    tenant_id = current_user.get("tenant_id")
    features = await repo.get_tenant_features(tenant_id)
    
    # 重新签发 JWT
    new_token = create_access_token(
        data={
            **current_user,
            "features": features,
        }
    )
    return {"code": 0, "message": "feature_flags 已刷新", "data": {"token": new_token}}
```

---

## 4. Layer 2：DataRouteResolver 路由解析

> **[rev] 适用范围：仅用于同平台模块（B/C/D 类），不适用于独立系统同步（A 类 M11↔平台）。跨系统数据同步由同步层方案（Event Push + API Pull）覆盖。**

### 4.1 设计说明

`DataRouteResolver` 是一个纯函数式路由解析器，**无状态、无副作用**。它的输入是 `(数据类型, feature_flags)`，输出是 `路由策略 key`。

核心思想是**"声明式路由"**——路由规则用字典表达，而不是 if/else 代码。

### 4.2 代码实现

```python
# app/core/route_resolver.py

from typing import Dict, Optional
from enum import Enum


class DataType(str, Enum):
    DEVICE = "device"
    ALERT = "alert"
    EMISSION = "emission"
    PRODUCTION = "production"
    SUPPLIER = "supplier"
    MONITOR = "monitor"


class RouteStrategy(str, Enum):
    TPM_EQUIPMENT = "tpm_equipment"
    ENERGY_SELF = "energy_device_self"
    ANDON_LINKED = "andon_linked"
    ENERGY_ALERT_ONLY = "energy_alert_only"
    MES_AUTO = "mes_auto"
    MANUAL_INPUT = "manual_input"
    IOT_GATEWAY = "iot_gateway"
    EXCEL_IMPORT = "excel_import"


class DataRouteResolver:
    """数据路由解析器 — 声明式路由规则"""
    
    # 路由规则表
    # 格式：{数据类型: [(flag, 路由策略), ...], "default": 默认策略}
    ROUTES = {
        DataType.DEVICE: [
            ("M02_EQUIPMENT", RouteStrategy.TPM_EQUIPMENT),
            ("default", RouteStrategy.ENERGY_SELF),
        ],
        DataType.ALERT: [
            ("M05_ANDON_CALL", RouteStrategy.ANDON_LINKED),
            ("default", RouteStrategy.ENERGY_ALERT_ONLY),
        ],
        DataType.EMISSION: [
            ("M01_WORK_REPORT", RouteStrategy.MES_AUTO),
            ("M12_IOT_GATEWAY", RouteStrategy.IOT_GATEWAY),
            ("default", RouteStrategy.MANUAL_INPUT),
        ],
        DataType.PRODUCTION: [
            ("M01_WORK_REPORT", RouteStrategy.MES_AUTO),
            ("default", RouteStrategy.MANUAL_INPUT),
        ],
        DataType.SUPPLIER: [
            ("M01_WORK_ORDER", RouteStrategy.SHARED_SUPPLIER),   # [rev] 有 M01 → 共享供应商表（供应商主数据）
            ("default", RouteStrategy.EXCEL_IMPORT),             # [rev] 无 M01 → Excel 导入降级
        ],
        DataType.MONITOR: [
            ("M12_IOT_GATEWAY", RouteStrategy.IOT_GATEWAY),
            ("default", RouteStrategy.MANUAL_INPUT),
        ],
    }
    
    @classmethod
    def resolve(cls, data_type: DataType, feature_flags: Dict[str, bool]) -> RouteStrategy:
        """解析数据类型 → 路由策略"""
        route_map = cls.ROUTES.get(data_type)
        if not route_map:
            raise ValueError(f"未知数据类型: {data_type}")
        
        for flag_or_default, strategy in route_map:
            if flag_or_default == "default":
                return strategy
            if feature_flags.get(flag_or_default, False):
                return strategy
        
        # [rev] Q-B2: 删除死代码段（原第二遍 for 循环不可达）
        return RouteStrategy.MANUAL_INPUT  # 极兜底
```

### 4.3 使用示例

```python
# EnergyRepository.list_devices()
strategy = DataRouteResolver.resolve(DataType.DEVICE, self.feature_flags)
if strategy == RouteStrategy.TPM_EQUIPMENT:
    sql = "SELECT e.*, ed.* FROM equipment e LEFT JOIN energy_device ed ON e.id = ed.equipment_id WHERE ..."
elif strategy == RouteStrategy.ENERGY_SELF:
    sql = "SELECT * FROM energy_device WHERE ..."
```

### 4.4 扩展新模块

当 Phase 2 新增模块时（如 M04 / M06 / M07 等），只需在 `ROUTES` 字典中新增条目：

```python
DataType.QUALITY_ANALYSIS = "quality_analysis"
ROUTES = {
    # ... 原有映射 ...
    DataType.QUALITY_ANALYSIS: [
        ("M03_QUALITY", RouteStrategy.QUALITY_MODULE),
        ("M12_IOT_GATEWAY", RouteStrategy.IOT_GATEWAY),
        ("default", RouteStrategy.MANUAL_INPUT),
    ],
}
```

无需修改任何 Repo 方法内部的 if/else 结构。

### 4.5 [rev] 画像驱动的路由模板（Item 10）

**引入动机**（PM-🟡-1）：当前 DataRouteResolver 基于单个 FeatureFlag 的线性判断，丢失了"画像级别的组合策略"。新增套餐组合时需要逐条验证 ROUTES 表的每条规则。

**解决方案**：在 `DataRouteResolver` 之上增加 `PersonaRouter` 层，将预定义的客户画像映射到路由策略模板。

```python
# app/core/persona_router.py
"""画像驱动的路由模板 — 将客户套餐组合映射为路由策略集合"""

from typing import Dict, List
from app.core.route_resolver import DataType, RouteStrategy


class PersonaRouter:
    """画像路由模板解析器"""
    
    # 预定义画像模板
    # {画像编码: {数据类型: 路由策略}}
    PERSONA_TEMPLATES = {
        "A04": {  # 纯制造（M01+M02+M03+M05）
            DataType.DEVICE: RouteStrategy.TPM_EQUIPMENT,
            DataType.ALERT: RouteStrategy.ANDON_LINKED,
            DataType.PRODUCTION: RouteStrategy.MES_AUTO,
        },
        "B01": {  # 仅能碳（仅 M11）
            DataType.DEVICE: RouteStrategy.ENERGY_SELF,
            DataType.ALERT: RouteStrategy.ENERGY_ALERT_ONLY,
            DataType.EMISSION: RouteStrategy.MANUAL_INPUT,
            DataType.PRODUCTION: RouteStrategy.MANUAL_INPUT,
            DataType.SUPPLIER: RouteStrategy.EXCEL_IMPORT,
            DataType.MONITOR: RouteStrategy.MANUAL_INPUT,
        },
        "C04": {  # 制造+能碳（M01+M02+M05+M11）
            DataType.DEVICE: RouteStrategy.TPM_EQUIPMENT,
            DataType.ALERT: RouteStrategy.ANDON_LINKED,
            DataType.EMISSION: RouteStrategy.MES_AUTO,
            DataType.PRODUCTION: RouteStrategy.MES_AUTO,
            DataType.SUPPLIER: RouteStrategy.SHARED_SUPPLIER,  # [rev] 有 M01 → 共享供应商表
            DataType.MONITOR: RouteStrategy.MANUAL_INPUT,
        },
    }
    
    @classmethod
    def resolve(cls, feature_flags: Dict[str, bool]) -> Dict[DataType, RouteStrategy]:
        """根据 feature_flags 匹配画像模板，返回完整路由策略集合"""
        match = cls._match_persona(feature_flags)
        if match:
            return match
        # 无精确匹配 → 回退到逐个 DataRouteResolver 解析
        return {}
    
    @classmethod
    def _match_persona(cls, feature_flags: Dict[str, bool]) -> Dict[DataType, RouteStrategy]:
        """匹配最合适的画像模板"""
        activated = {k for k, v in feature_flags.items() if v}
        for persona_id, template in cls.PERSONA_TEMPLATES.items():
            template_flags = cls._persona_to_flags(persona_id)
            if activated == template_flags:
                return template
        return None
    
    @classmethod
    def _persona_to_flags(cls, persona_id: str) -> set:
        """画像编码 → 对应 feature_flag 集合"""
        mapping = {
            "A04": {"M01_WORK_ORDER", "M02_EQUIPMENT", "M03_QUALITY", "M05_ANDON_CALL"},
            "B01": {"M11_ENERGY"},
            "C04": {"M01_WORK_ORDER", "M02_EQUIPMENT", "M05_ANDON_CALL", "M11_ENERGY"},
        }
        return mapping.get(persona_id, set())
```

**画像模板的作用流程**：

```
套餐配置
    │
    ▼
feature_flags dict
    │
    ├──→ PersonaRouter.match() — 匹配画像模板
    │      如果匹配 → 直接返回模板中的路由策略集合
    │
    └──→ DataRouteResolver.resolve() — 逐个解析（作为 fallback）
           当无画像模板匹配时，回退到原始的 flat flag 判断
```

**Phase 1 实施**：仅定义 `PERSONA_TEMPLATES` 常量，由工程师在 Repo 方法中按需引用。Phase 2 可进一步自动化为"新套餐→自动匹配最近画像"的智能路由。

---

## 5. Layer 3：Repo 层数据访问

### 5.1 MultiTenantRepository 基类改造

```python
# app/repositories/base.py

from typing import Dict, Optional, List
from app.core.route_resolver import DataRouteResolver, RouteStrategy


class MultiTenantRepository:
    """多租户 Repo 基类，[rev] 新增 feature_flags 支持（E-B5）"""
    
    _tenant_id: Optional[str] = None
    feature_flags: Dict[str, bool] = {}  # [rev] 新增：类型注解 + 默认空 dict
    
    def __init__(self, db, feature_flags: Optional[Dict[str, bool]] = None):
        self.db = db
        self.feature_flags = feature_flags or {}  # [rev] 构造函数注入
    
    def resolve(self, data_type) -> RouteStrategy:
        """快速获取某数据类型对应的路由策略"""
        return DataRouteResolver.resolve(data_type, self.feature_flags)
    
    # ... 原有 query_page, query_one, execute 等方法保持不变 ...
```

**[rev] 子类获取 feature_flags 的方式**：
- 子类通过 `self.feature_flags` 直接读取（已由 `get_tenant_repo` 工厂注入）
- 子类通过 `self.resolve(DataType.DEVICE)` 快捷获取路由策略
- 所有现有子类（TenantRepo, UserRepo, RoleRepo, AndonRepo）需适配 `__init__` 签名：
  - 子类应定义为 `def __init__(self, db, feature_flags=None, **kwargs)` 并透传
  - 或由工厂统一注入，子类不需要修改

### 5.2 Feature Flag 的默认值策略

JWT 中未携带的 flag 视为 `False`（安全默认）：

```python
# dependencies.py 中的 get_feature_flags
def get_feature_flags(current_user):
    raw = current_user.get("features", {})
    # 所有已知模块默认 False
    DEFAULT_FEATURES = {
        "M01_WORK_ORDER": False,
        "M01_WORK_REPORT": False,
        "M02_EQUIPMENT": False,
        "M02_MAINTENANCE": False,
        "M03_QUALITY": False,
        "M05_ANDON_CALL": False,
        "M11_ENERGY": False,
        "M12_EXCEL_IMPORT": False,
        "M12_IOT_GATEWAY": False,
        "M13_DASHBOARD": False,
    }
    DEFAULT_FEATURES.update(raw)
    return DEFAULT_FEATURES
```

---

## 6. [rev] M11 能碳模块设计（独立系统前提）

> **[rev] 核心前提修正**：M11 能碳是**独立系统（类型 A）**，与知微云平台之间通过同步层对接。本文档仅描述 M11 **作为同平台模块部署时**的条件路由能力。独立系统架构详见《M11-能碳整合方案-v3》。

### 6.1 [rev] 独立系统架构概览

M11 能碳系统与知微云平台之间是**独立系统相互同步**的关系，而非同平台模块之间的同库 JOIN 关系：

```
┌──────────────────────┐         ┌──────────────────────────┐
│    知微云平台         │         │  M11 能碳独立系统         │
│                      │         │                          │
│  ┌────────────────┐  │  Event  │  ┌────────────────────┐  │
│  │ M01 生产管理   │──┼─────────┼─▶│ 事件消费服务        │  │
│  │ M02 TPM 设备  │  │  Push   │  │ (Event Consumer)   │  │
│  │ M05 安灯      │  │         │  └────────┬───────────┘  │
│  └────────────────┘  │         │           │              │
│         │            │         │           ▼              │
│         ▼            │         │  ┌────────────────────┐  │
│  ┌────────────────┐  │         │  │ M11 本地 DB        │  │
│  │ change_log 表  │  │──API───┼─▶│ (SQLite/PG)        │  │
│  │ (事件记录)      │  │  Pull  │  │                    │  │
│  └────────────────┘  │  兜底   │  │ energy_device      │  │
│                      │         │  │ carbon_record      │  │
│                      │         │  │ energy_alert       │  │
│                      │         │  └────────────────────┘  │
│                      │         │                          │
│                      │         │  ┌────────────────────┐  │
│                      │         │  │ Excel 导入         │  │
│                      │         │  │ (独立模式数据源)    │  │
│                      │         │  └────────────────────┘  │
└──────────────────────┘         └──────────────────────────┘
```

**架构模式**：Hybrid Sync（Event Push + API Pull 混合）
- **主通道**：Event Push（平台数据变更 → 写入 change_log 表 → M11 定时拉取）
- **兜底通道**：API Pull（T+1 全量对账，修复不一致）
- **离线模式**：M11 独立运行（本地 SQLite + Excel 导入），联网后自动同步

### 6.2 [rev] 同步层设计概要

#### Phase 1 轻量实现（无消息中间件）

```
知微云平台                          M11 能碳系统
──────────                          ────────────
数据变更
    │
    ▼
写入本地 change_log 表              HTTP POST /api/v1/sync/pull
(记录: table, row_id, action, ts)  (M11 定时轮询, 默认 60s)
    │                                    │
    └─── 等待 M11 拉取 ──────────────────▶
                                         │
                                         ▼
                                    M11 解析 change_log
                                    → 调用平台 API 获取完整数据
                                    → 写入本地 DB

定时对账(每日 02:00):
  平台: SELECT count(*) FROM equipment WHERE updated_at > last_sync
  M11: 对比本地数据量 → 不一致时全量拉取
```

#### 数据主权矩阵

基于"谁创建谁主责"原则：

| 数据类型 | 数据主权方 | M11 角色 | 同步方向 |
|:---------|:----------|:---------|:---------|
| **设备档案** | M02 TPM（设备台账唯一权威来源） | 🔴 只读消费 | M02 → M11（单向） |
| **供应商主数据** | M01 生产管理 | 🔴 只读消费 | M01 → M11（单向） |
| **产量数据（报工）** | M01 生产管理 | 🔴 只读消费 | M01 → M11（单向） |
| **能耗数据** | M11 能碳 | 🟢 数据所有者 | M11 自有，不同步回平台 |
| **碳排放核算结果** | M11 能碳 | 🟢 数据所有者 | M11 自有 |
| **能耗告警** | M11 能碳 | 🟢 数据所有者 | M11 自有（告警可触发平台安灯） |
| **IoT 时序数据** | M12 IoT 网关 | 🟡 半消费 | M12 → M11（若 M12 存在且连接） |

#### M11 本地 DB 来源字段补充

```sql
ALTER TABLE energy_device ADD COLUMN data_source VARCHAR(20) DEFAULT 'excel';
  -- 'excel' = Excel 导入（独立模式）
  -- 'sync'  = 从平台同步（全平台模式）
  -- 'manual' = 手动录入

ALTER TABLE energy_device ADD COLUMN source_id VARCHAR(64);
  -- 平台端对应记录的 ID（如 equipment.id），用于同步关联

ALTER TABLE energy_device ADD COLUMN sync_version INTEGER DEFAULT 0;
  -- 乐观锁，用于检测同步冲突
```

### 6.3 [rev] 同平台场景下的数据路由（保留）

当 M11 **作为平台模块部署时**（即 full SaaS 部署，非独立系统），保留条件路由能力：

#### `list_devices`：DataRouteResolver 条件路由（可选的平台内 JOIN）

```python
# 仅在同平台部署时使用
async def list_devices(self, page=1, page_size=20, **filters):
    strategy = self.resolve(DataType.DEVICE)
    
    if strategy == RouteStrategy.TPM_EQUIPMENT:
        # 同平台模式：equipment JOIN energy_device
        return await self._list_devices_tpm_mode(page, page_size, filters)
    else:
        # 独立/轻量模式：仅 energy_device（数据来自同步层或 Excel 导入）
        return await self._list_devices_standalone_mode(page, page_size, filters)
```

#### `create_alert`：告警联动安灯

```python
async def create_alert(self, data: dict) -> int:
    """创建能耗告警 — 联动安灯由路由策略决定"""
    strategy = self.resolve(DataType.ALERT)
    
    alert_id = await self.execute(
        "INSERT INTO energy_alert (...) VALUES (...) RETURNING id",
        data,
    )
    
    if strategy == RouteStrategy.ANDON_LINKED:
        # 同平台模式：联动创建安灯呼叫
        andon_data = self._build_andon_call_data(data)
        await self._create_andon_call(andon_data)
    
    return alert_id
```

**路由决策表（同平台部署时）**：

| 数据操作 | 同平台模式 (has TPM/MES/安灯) | 独立部署模式 (仅 M11) |
|:---------|:------------------------------|:---------------------|
| 设备列表 | `equipment LEFT JOIN energy_device`（同库查询） | `energy_device` 自管（数据由同步层填充） |
| 设备创建 | `equipment` 创建 → 同步后 M11 消费 | `energy_device` 直写 |
| 碳排放核算 | 从 M01 `work_report` 取产量，计算排放强度 | 用户手动录入能耗数据，无产量维度 |
| 能耗告警 | 创建告警 → 联动安灯呼叫 | 仅写入 `energy_alert` |
| 供应商 | M01 共享供应商表 / Excel 导入降级 | Excel 导入 |
| IoT 数据 | 通过 M12 IoT 网关采集能耗时序数据 | 仅 Excel 导入 |
| 看板 | 跨模块数据聚合看板 | 仅能碳模块看板 |

### 6.4 [rev] 独立模式下的 I/O

当 M11 以独立系统模式运行时：

| 能力 | 方式 | 说明 |
|:-----|:-----|:------|
| **数据导入** | Excel 导入为核心（日更操作） | 标准化模板 + 三层校验（模板→字段→业务） |
| **看板** | 内嵌看板（推荐） | 同部署同数据源，直接从 M11 本地 DB 查询 |
| **认证** | 独立认证（`standalone_auth`） | 内置管理员账户，JWT 复用 `security.py` 统一密钥 |
| **数据路由** | 不依赖 DataRouteResolver | 所有数据从 M11 本地 DB 读取，数据来源由同步层负责 |
| **数据来源** | 同步层获取（Event Push + API Pull）+ Excel 导入 | 统一写入 M11 本地 DB |

---

## 7. [rev] M11 独立部署模式设计

> **[rev] 核心前提修正**：M11 是**独立系统部署**，而非"平台模块的独立部署"。M11 拥有自己的数据库、认证体系和部署生命周期，与知微云平台之间通过同步层交换数据。

### 7.1 [rev] 独立系统定位

M11 能碳系统独立于知微云平台部署，适用于以下场景：

| 场景 | 描述 | 数据来源 |
|:-----|:------|:---------|
| **仅能碳客户** | 客户仅购买能碳模块，无其他知微模块 | Excel 导入（核心数据源） |
| **离线工厂** | 无网络环境，数据本地存储 | Excel 导入 + 本地录入 |
| **能碳+平台** | 同时购买能碳与其他知微模块 | 同步层（Event Push + API Pull）+ Excel 导入 |

**与平台的关系**：M11 是独立的系统身份，通过同步层与平台交换数据，而非同库部署的模块。

### 7.2 [rev] 独立部署架构

```
┌──────────────────────────────────┐
│  M11 能碳独立系统                  │
│                                  │
│  ┌────────────────────────────┐  │
│  │  独立认证 (standalone_auth) │  │
│  │  ─ 内置管理员账户           │  │
│  │  ─ JWT 复用 security.py    │  │
│  └──────────┬─────────────────┘  │
│             │                     │
│  ┌──────────▼─────────────────┐  │
│  │  API 路由层                  │  │
│  │  (仅 M11 自身端点)          │  │
│  └──────────┬─────────────────┘  │
│             │                     │
│  ┌──────────▼─────────────────┐  │
│  │  Repo 层                     │  │
│  │  ─ 不依赖 DataRouteResolver │  │
│  │  ─ 统一从本地 DB 读取       │  │
│  └──────────┬─────────────────┘  │
│             │                     │
│  ┌──────────▼─────────────────┐  │
│  │  独立 DB (SQLite / PG)      │  │
│  │  energy_device              │  │
│  │  carbon_record              │  │
│  │  energy_alert               │  │
│  └────────────────────────────┘  │
│                                  │
│  ┌────────────────────────────┐  │
│  │  同步层                      │  │
│  │  ─ Event Consumer           │  │
│  │  ─ API Pull (兜底)          │  │
│  │  ─ T+1 对账                 │  │
│  └────────────────────────────┘  │
│                                  │
│  ┌────────────────────────────┐  │
│  │  导入层                      │  │
│  │  ─ Excel Importer          │  │
│  │  ─ 模板校验引擎             │  │
│  └────────────────────────────┘  │
└──────────────────────────────────┘
```

**关键区别**：
- ❌ 不依赖 DataRouteResolver（数据不涉及同库跨模块 JOIN）
- ❌ 不经过平台 FeatureFlag 注入链
- ✅ 数据通过同步层从平台获取，或通过 Excel 导入
- ✅ 拥有独立 DB、独立认证、独立前端

### 7.3 [rev] 独立 DB 配置

```python
# app/core/config.py
class Settings(BaseSettings):
    # ... 其他配置 ...
    
    # M11 部署模式标识
    M11_STANDALONE: bool = True  # M11 独立系统部署
    
    # 独立数据库配置
    STANDALONE_DB_URL: str = "sqlite+aiosqlite:///./m11_energy.db"
    # 支持 PostgreSQL（生产环境推荐）
    # STANDALONE_DB_URL: str = "postgresql+asyncpg://user:pass@localhost/m11_energy"
    
    # 统一密钥（独立系统也使用同一 JWT_SECRET_KEY）
    JWT_SECRET_KEY: str = "change-in-production"
    JWT_ALGORITHM: str = "HS256"
```

```python
# app/core/database.py — M11 独立数据库连接
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from app.core.config import get_settings

settings = get_settings()

# M11 独立系统仅连接自己的数据库
engine = create_async_engine(settings.STANDALONE_DB_URL)

async def ensure_tables():
    """M11 独立部署自动建表"""
    from app.models.energy import Base as EnergyBase
    async with engine.begin() as conn:
        await conn.run_sync(EnergyBase.metadata.create_all)
```

**数据来源字段补充**（M11 本地 `energy_device` 表）：

```sql
ALTER TABLE energy_device ADD COLUMN data_source VARCHAR(20) DEFAULT 'excel';
  -- 'excel' = Excel 导入（独立模式核心数据源）
  -- 'sync'  = 从平台同步
  -- 'manual' = 手动录入

ALTER TABLE energy_device ADD COLUMN source_id VARCHAR(64);
  -- 平台端对应记录的 ID（如 equipment.id），用于同步关联

ALTER TABLE energy_device ADD COLUMN sync_version INTEGER DEFAULT 0;
  -- 乐观锁，用于检测同步冲突
```

### 7.4 [rev] 独立认证（standalone_auth）

M11 独立系统使用精简认证方案，但与平台共享 JWT 密钥体系：

```python
# app/core/standalone_auth.py
"""M11 独立系统认证

JWT 签发与验签统一复用 security.py，使用同一 JWT_SECRET_KEY。
standalone_auth.py 仅负责用户身份验证（校验用户名密码）。
"""

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from app.core.security import create_access_token, verify_token
from datetime import datetime, timezone, timedelta
from app.core.config import get_settings

security = HTTPBearer()
settings = get_settings()

# 内置管理员账户（从环境变量读取）
STANDALONE_USERS = {
    "admin": {
        "password": settings.STANDALONE_ADMIN_PASSWORD or "admin123",
        "name": "系统管理员",
    }
}

def authenticate_standalone(username: str, password: str) -> dict:
    """M11 独立系统认证 — 返回用户信息供 JWT 签发"""
    user = STANDALONE_USERS.get(username)
    if not user or user["password"] != password:
        raise HTTPException(status_code=401, detail="用户名或密码错误")
    
    return {
        "id": "standalone_admin",
        "username": username,
        "name": user["name"],
        "tenant_id": "standalone",
        "features": {
            "M11_ENERGY": True,
            # 独立模式下所有其他模块均为 False
        },
    }

def get_authenticator(standalone: bool = False):
    """根据部署模式返回不同的认证依赖注入函数
    
    全平台模式：使用 JWT token 验证（security.py verify_token）
    M11 独立模式：使用内置账户验证（authenticate_standalone）
    两种模式均使用统一密钥 JWT_SECRET_KEY 签发/验签
    """
    if standalone:
        return authenticate_standalone
    from app.core.dependencies import get_current_user
    return get_current_user
```

### 7.5 [rev] 前端独立构建

M11 独立系统有自己独立的前端入口：

```yaml
frontend/
  src/
    modules/
      energy/                  # M11 能碳模块代码
        pages/                 # 页面组件
        components/            # 通用组件
        api/                   # API 调用
  config/
    vite.config.ts             # 全平台构建配置
    vite.config.standalone.ts  # M11 独立构建配置
```

- **全平台模式**：`vite build` → 构建完整的 SaaS 前端
- **M11 独立模式**：`vite build --config vite.config.standalone.ts` → 仅构建能碳模块前端 + 精简 Shell

```typescript
// vite.config.standalone.ts
import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  build: {
    outDir: 'dist-standalone',
    rollupOptions: {
      input: {
        main: 'src/modules/energy/index.html',  // 独立入口
      },
    },
  },
  define: {
    'import.meta.env.VITE_STANDALONE': 'true',
  },
});
```

### 7.6 [rev] 运行时判定与启动

```python
# app/main.py — M11 独立系统入口

from app.core.config import get_settings
from app.core.standalone_auth import get_authenticator

settings = get_settings()

# M11 独立系统启动
# 注册 M11 自身路由
from app.api.standalone import router as standalone_router
app.include_router(standalone_router)

# 注入独立认证
app.dependency_overrides[get_current_user] = get_authenticator(standalone=True)

# 使用独立 DB（SQLite/PG），不连接平台数据库
# 数据通过同步层获取或 Excel 导入
# 不注册其他模块路由
```

---

## 8. 跨模块调用与事务边界

### 8.1 问题定义

当 M11 能碳模块联动 M05 安灯模块创建 `andon_call` 时，存在两个操作属于同一个事务还是独立事务的问题。

### 8.2 方案选型

| 方案 | 描述 | 优点 | 缺点 |
|:-----|:------|:-----|:------|
| **A. 同事务联动** | EnergyRepo 和 AndonRepo 共享同 session | 数据一致性保证 | 安灯失败导致告警回滚 |
| **B. 独立事务** | 告警和安灯各用独立事务，先写告警再写安灯 | 互不影响 | 告警先成功但安灯后失败 → 数据不一致 |
| **C. 异步消息 (推荐)** | 告警写入后发消息队列，安灯模块异步消费 | 完全解耦 | 需要消息队列基础设施 |

### 8.3 [rev] 推荐方案与事务边界决策

**Phase 1 采用方案 A（同事务联动），Phase 2 演进为方案 C（异步消息）。**

**[rev] Q-B6 决策**：`create_alert` 中安灯调用失败时 → **不 raise + 日志记录 + 异步重试**。

理由：
- **业务优先原则**：告警是核心操作，安灯联动是增值操作。核心操作不应因增值操作失败而回滚。
- 日志记录保证可追溯性（`logger.error` + 告警ID关联）
- 异步重试机制（简单重试队列或定时任务）保证安灯最终可达
- Phase 1 先实现"不 raise + 日志"；Phase 2 升级为完整重试队列

```python
# app/repositories/energy_repo.py
# Phase 1 实现：同 session 传递 AndonRepository

from app.repositories.andon_repo import AndonRepository
import logging

logger = logging.getLogger(__name__)


class EnergyRepository(MultiTenantRepository):
    
    # [rev] E-B3: Python 不支持 async __init__ → 改用 @property 惰性初始化
    @property
    def _andon_repo(self):
        """惰性初始化 AndonRepository，共享 db session"""
        if not hasattr(self, '_andon_repo_instance'):
            self._andon_repo_instance = AndonRepository(self.db, self.feature_flags)
        return self._andon_repo_instance
    
    async def create_alert(self, data: dict) -> int:
        """
        创建能耗告警
        [rev] 事务边界决策: 🔴 同一事务（但安灯失败不阻断）
        - energy_alert (M11) ← 主操作
        - andon_call (M05)   ← 联动操作（失败不阻断）
        行为: 安灯联动失败 → 记录日志 + 标记异步重试，告警仍成功
        后续演进: Phase 2 改为消息队列异步解耦
        """
        strategy = self.resolve(DataType.ALERT)
        
        # Step 1: 创建告警（始终执行，主操作）
        alert_id = await self.execute(
            "INSERT INTO energy_alert (...) VALUES (...) RETURNING id",
            data,
        )
        
        # Step 2: 联动安灯（根据路由策略）
        if strategy == RouteStrategy.ANDON_LINKED:
            try:
                andon_data = self._build_andon_call_data(data)
                await self._andon_repo.create_call(andon_data)
            except Exception as e:
                # [rev] Q-B6: 不 raise → 仅记录日志 + 标记异步重试
                logger.error(
                    f"安灯联动失败 (告警ID={alert_id}, 数据={andon_data}): {e}",
                    exc_info=True
                )
                # 记录到重试表（供定时任务重试）
                await self._schedule_andon_retry(alert_id, andon_data)
        
        return alert_id
    
    async def _schedule_andon_retry(self, alert_id: int, andon_data: dict):
        """记录安灯联动失败的重试任务"""
        await self.execute(
            "INSERT INTO andon_retry_queue (alert_id, andon_data, retry_count, status) "
            "VALUES (:alert_id, :andon_data, 0, 'pending')",
            {"alert_id": alert_id, "andon_data": andon_data},
        )
```

### 8.4 [rev] 异步重试机制

```python
# app/services/retry_service.py
"""安灯联动失败的异步重试服务"""


class AndonRetryService:
    """重试队列消费服务 — 定时任务调用"""
    
    MAX_RETRIES = 3
    RETRY_INTERVAL_MINUTES = 5
    
    async def process_retry_queue(self):
        """处理待重试的安灯联动任务"""
        retry_items = await self.db.execute(
            "SELECT * FROM andon_retry_queue "
            "WHERE status = 'pending' AND retry_count < :max_retries "
            "AND updated_at < NOW() - :interval * INTERVAL '1 minute'",
            {"max_retries": self.MAX_RETRIES, "interval": self.RETRY_INTERVAL_MINUTES},
        )
        for item in retry_items:
            try:
                result = await self._andon_repo.create_call(item.andon_data)
                if result:
                    await self.db.execute(
                        "UPDATE andon_retry_queue SET status = 'success' WHERE id = :id",
                        {"id": item.id},
                    )
            except Exception as e:
                await self.db.execute(
                    "UPDATE andon_retry_queue SET retry_count = retry_count + 1 "
                    "WHERE id = :id",
                    {"id": item.id},
                )
```

### 8.5 事务边界文档化

每个涉及跨模块调用的方法必须明确标注事务边界：

```python
async def create_alert(self, data):
    """
    [rev] 事务边界: 🔴 同一事务（非阻断）
    - energy_alert (M11) ← 主操作（始终成功）
    - andon_call (M05)   ← 联动操作（失败不阻断主操作）
    行为: 若 andon_call 创建失败 → 记录日志 + 写入重试队列，告警仍成功
    后续演进: Phase 2 改为消息队列异步解耦
    """
```

### 8.6 事务边界标注规范

| 标注 | 含义 |
|:----|:------|
| 🔴 同一事务（阻断） | 所有操作在同一个 DB 事务中，任一失败全部回滚 |
| 🔴 同一事务（非阻断） | **[rev] 新增** 同事务但增值操作失败不阻断主操作，记录日志+异步重试 |
| 🟡 独立事务 | 每个操作使用独立事务，前序成功不会被后续失败影响 |
| 🟢 异步消息 | 操作之间通过消息队列异步解耦 |

---

## 9. [rev] 源系统 API 迁移清单

> **[rev] 迁移方向说明**：源系统的能碳相关 API（analysis / carbon / dashboard / monitoring 等）迁移到 **M11 独立系统**（`m11-energy/backend`），而非整合入知微云平台。M11 独立系统拥有自己的 API 服务，与平台之间通过同步层交换数据。下文表格中的"SaaS 状态"指代目标系统为 M11 独立系统。

### 9.1 源系统 API 总览

源系统（`ziwi_project_dna/backend`）共有 **14 个路由器、63 个 API 端点**。以下按功能模块逐条盘点迁移状态。

### 9.2 按模块迁移清单

#### ✅ 已迁移至 SaaS（11 个端点）

| 源系统文件 | 源路径 | 方法 | SaaS 状态 | 验证方式 |
|:----------|:-------|:----:|:---------|:---------|
| carbon.py | `/api/carbon/accounting` | GET | ✅ energy.py | 已通过测试 |
| device_mgmt.py | `/list` | GET | ✅ energy.py | 已通过测试 |
| device_mgmt.py | `/workcenters` | GET | ✅ energy.py | 已通过测试 |
| auth_router.py | `/login` | POST | ✅ auth.py | 复用 SaaS 认证 |
| auth_router.py | `/me` | GET | ✅ auth.py | 复用 SaaS 认证 |
| auth_router.py | `/logout` | POST | ✅ auth.py | 复用 SaaS 认证 |
| dict_router.py | 全部 5 个端点 | GET/POST/DELETE | ✅ dictionary.py | 复用 SaaS 字典 |
| 设备 CRUD | 详情/更新/删除 | GET/PUT/DELETE | ✅ energy.py | 已通过测试 |

#### 🔄 待迁移（52 个端点）

| 模块 | 路由文件 | 端点数量 | 工作量评估 | 优先级 | 说明 |
|:-----|:---------|:--------:|:----------|:------|:------|
| **能效分析** | analysis.py | 4 | 4h | P1 | 含复杂 SQL 聚合（强度分析/基准对比/能量平衡/能流图），需使用路由策略 |
| **碳足迹** | carbon.py(部分) | 6 | 6h | P1 | 产品碳足迹/供应链碳/碳预算/碳审计，数据来源涉及 M01+M02 |
| **大屏** | bigscreen.py | 7 | 3h | P1 | 7 个大屏展示端点，纯查询，数据来源需路由策略判断 |
| **Dashboard** | dashboard.py | 3 | 2h | P1 | 概要/趋势/排名，需与 M13 看板模块整合 |
| **能效优化** | efficiency.py | 3 | 3h | P2 | 效率趋势/概览/优化任务，业务逻辑较重 |
| **实时监测** | monitoring.py | 4 | 4h | P1 | 实时数据/告警/告警规则 CRUD，涉及 IoT 时序数据 |
| **供应商** | supplier.py | 5 | 3h | P2 | [rev] PM-🔴-1 已决策（归 M01）：见 §9.5 |
| **数据源配置** | datasource.py | 4 | 2h | P2 | 数据源管理（创建/列表/删除/日志） |
| **数据源配置** | datasource.py | 4 | 2h | P2 | 数据源管理（创建/列表/删除/日志） |
| **数据导入** | import_api.py | 3 | 2h | P1 | Excel 导入增强，需与 M12 整合 |
| **系统管理** | system.py | 11 | 0.5h | P2 | 碳资产配额/交易/CCER/组织管理/用户管理—大部分功能被SaaS替代，仅碳资产相关需迁移 |

### 9.3 工作量汇总（[rev] 修正版）

| 优先级 | 端点数 | 预估工时 | 说明 |
|:-------|:------:|:---------|:------|
| P0 | - | 0h | 本次不涉及新增 P0（CRUD 已在 Phase 1 完成） |
| P1 | 24 | **19h** | 能效分析/碳足迹/大屏/Dashboard/监测/数据导入 |
| P2 | 28 | **9h** | 供应商/效率优化/系统管理/数据源 |
| 编码小计 | **52** | **28h** | — |
| 测试 | — | **+10~12h** | [rev] 新增：32 种场景路由测试 + 集成测试 |
| 文档 | — | **+2~3h** | [rev] 新增：API 文档、迁移记录 |
| **总计** | **52** | **~40-43h** | [rev] 较原 28h 增加约 50% |

> **[rev] Item 13 修正**：原方案估计 "P2 迁移剩余路由(~3h)" 与实际情况（约 **28h**）存在约 **9 倍** 的差距。测试（10-12h）和文档（2-3h）在原估算中完全缺失，修订后总工时约为 **40-43h**。

### 9.4 迁移优先级原则

1. **P1 优先迁移**：核心能碳业务功能（分析/碳足迹/监测），这些功能直接影响能碳模块的完整度
2. **P2 后续迁移**：供应商/效率优化等非核心或可降级功能
3. **非能碳专属**：system.py 中的碳资产相关功能（配额/交易/CCER）需判断是否确实属于 M11，还是应该提取为独立的 Mxx 模块

### 9.5 [rev] 供应商模块归属分析（PM-🔴-1 已决策 → 归 M01）

**问题**：supplier.py（5 个端点）归属 M11 专用还是全平台通用？

**产品决策结果（详见 `docs/decisions/supplier-and-standalone-decision-assessment.md` §5）**：

✅ **决策：方案 B（归 M01 基础主数据）**
- 供应商如同 BOM，是基础数据而非某个执行模块的属性
- 有 ERP 时，供应商主数据在 ERP 管理，经 M06 桥接层同步到 M01
- 无 ERP 时，M01 自行管理供应商主数据
- M09 SRM 剥离"供应商主数据管理"职责，聚焦全生命周期管理（准入/评价/协同/门户）

**修订后的路由设计**：

| 维度 | 最终设计 |
|:-----|:---------|
| 业务含义 | 供应商作为生产基础主数据（原料供应商、物料供应商）跨模块共享 |
| 数据模型 | 与 M01 共享供应商表关联，M02/M03/M05/M11 通过 Repo 组合读取 |
| 路由判定 | `DataType.SUPPLIER` 路由判定依赖 `M01_WORK_ORDER` flag |
| EXCEL_IMPORT 降级 | 无 M01 时 → Excel 导入（如仅 M11 独立部署场景） |
| 有 ERP 时的数据流 | ERP 供应商主数据 → M06 桥接层同步 → M01 共享供应商表 |
| 对 M11 的影响 | 能碳模块通过 M01 报工关联获取供应商数据，用于供应链碳足迹核算 |
| P2 迁移影响 | supplier.py 纳入 M01 扩展迁移批次 |

---

## 10. 测试策略

### 10.1 测试挑战

32 种有意义的场景组合 × 每场景 N 个数据操作 = 大量组合需要测试。传统的手写测试用例不可行。

### 10.2 场景驱动的测试架构

```
tests/
  scenarios/
    conftest.py                  # 场景测试的共享 fixture
    profiles/
      A_pure_manufacturing.py    # 画像 A 测试
      B_energy_carbon.py         # 画像 B 测试
      C_manufacturing_energy.py  # 画像 C 测试
      D_data_collection.py       # 画像 D 测试
      E_dashboard.py             # 画像 E 测试
    routes/
      test_device_routes.py      # 设备路由策略测试
      test_alert_routes.py       # 告警路由策略测试
      test_emission_routes.py    # 碳排放路由策略测试
```

### 10.3 参数化测试策略

```python
# tests/scenarios/conftest.py

import pytest

# 6 大画像的 feature_flags 配置
SCENARIO_FIXTURES = {
    "A01": {"M01_WORK_ORDER": True},
    "A02": {"M01_WORK_ORDER": True, "M02_EQUIPMENT": True},
    "A04": {"M01_WORK_ORDER": True, "M02_EQUIPMENT": True,
            "M03_QUALITY": True, "M05_ANDON_CALL": True},
    "B01": {"M11_ENERGY": True},
    "B04": {"M02_EQUIPMENT": True, "M11_ENERGY": True, "M12_IOT_GATEWAY": True},
    "C04": {"M01_WORK_ORDER": True, "M02_EQUIPMENT": True,
            "M05_ANDON_CALL": True, "M11_ENERGY": True},
    "C05": {"M01_WORK_ORDER": True, "M02_EQUIPMENT": True,
            "M03_QUALITY": True, "M05_ANDON_CALL": True, "M11_ENERGY": True},
    "D01": {"M12_EXCEL_IMPORT": True},
}
```

```python
# tests/scenarios/routes/test_device_routes.py

@pytest.mark.parametrize("scenario,expected_strategy", [
    ("B01", "energy_device_self"),     # 仅 M11 → 自管设备
    ("A02", "tpm_equipment"),          # M01+M02 → TPM 设备 JOIN
    ("C05", "tpm_equipment"),          # 全制造+能碳 → TPM 设备 JOIN
])
async def test_device_list_routing(scenario, expected_strategy):
    flags = SCENARIO_FIXTURES[scenario]
    strategy = DataRouteResolver.resolve(DataType.DEVICE, flags)
    assert strategy == expected_strategy
```

### 10.4 6 大画像的端到端测试场景

| 画像 | 场景编码 | FeatureFlags | 测试覆盖点 |
|:-----|:--------|:-------------|:-----------|
| A-纯制造 | A04 | M01+M02+M03+M05 | 设备走 TPM，告警走安灯联动 |
| B-能碳驱动 | B01 | 仅 M11 | 独立部署模式，设备自管，内部告警 |
| B-能碳+设备 | B04 | M02+M11+M12 | 设备走 TPM，能耗 IoT 采集 |
| C-制造+能碳 | C04 | M01+M02+M05+M11 | **推荐套餐**：TPM 设备 + MES 产量 + 安灯联动 |
| D-数据采集 | D01 | 仅 M12 | 纯采集模式 |
| E-看板增强 | C04+M13 | M01+M02+M05+M11+M13 | 看板聚合数据 |

---

## 11. 场景规则引擎

### 11.1 动机

原"全场景枚举表"是手工维护的 Markdown 表格，当模块扩展到 13 个时无法持续。引入规则引擎替代枚举。

### 11.2 规则定义

```yaml
# app/core/scenario_rules.yaml
# 场景规则引擎：将枚举表转化为"规则 + 约束"

rules:
  # === 约束规则 [rev] 从 3 条扩展到 12 条（Item 11） ===
  constraints:
    - name: "看板需要数据源"
      description: "M13 看板不能独立存在，需要至少一个业务模块"
      condition: "M13_DASHBOARD == True AND sum(M01..M12) == 0"
      action: "BLOCK"
      message: "看板模块需要至少一个业务模块提供数据源"
    
    - name: "M03 品质建议关联 M01 生产"
      condition: "M03_QUALITY == True AND M01_WORK_ORDER == False"
      action: "WARN"
      message: "品质模块与生产模块存在强关联，建议同时选配 M01 生产管理"
    
    - name: "M11 能碳建议关联 M02 设备"
      condition: "M11_ENERGY == True AND M02_EQUIPMENT == False"
      action: "WARN"
      message: "能碳模块与设备管理存在强关联，建议同时选配 M02 TPM"
    
    # [rev] 以下 9 条为新增约束规则
    - name: "M05 安灯需要 M02 设备"
      description: "安灯呼叫必须关联设备"
      condition: "M05_ANDON_CALL == True AND M02_EQUIPMENT == False"
      action: "BLOCK"
      message: "安灯模块必须关联 M02 设备管理模块"
    
    - name: "M11 实时监测需要 M12 IoT"
      description: "无 IoT 网关时实时监测不可用"
      condition: "M11_ENERGY == True AND M12_IOT_GATEWAY == False"
      action: "WARN"
      message: "能碳模块的实时监测功能需搭配 M12 IoT 网关，当前功能将降级为手动录入"
    
    - name: "M11 能效分析需要 M12 数据采集"
      description: "能效分析依赖时序数据"
      condition: "M11_ENERGY == True AND M12_EXCEL_IMPORT == False AND M12_IOT_GATEWAY == False"
      action: "WARN"
      message: "能效分析功能需至少一种数据采集方式（Excel 导入或 IoT 网关），当前功能受限"
    
    - name: "M11 碳足迹需要 M01 生产"
      description: "产品碳足迹需要产量数据"
      condition: "M11_ENERGY == True AND M01_WORK_REPORT == False"
      action: "WARN"
      message: "产品碳足迹核算需搭配 M01 报工管理以获取产量数据，否则将降级为手动录入"
    
    - name: "M03 品质检测需要 M02 设备"
      description: "品质检测需关联检测设备"
      condition: "M03_QUALITY == True AND M02_EQUIPMENT == False"
      action: "BLOCK"
      message: "品质检测模块必须关联 M02 设备管理模块"
    
    - name: "M02 保养计划需要 M02 设备"
      description: "保养计划依赖于设备档案"
      condition: "M02_MAINTENANCE == True AND M02_EQUIPMENT == False"
      action: "BLOCK"
      message: "保养计划模块必须关联 M02 设备管理模块"
    
    - name: "M12 IoT 网关建议关联业务模块"
      description: "IoT 采集的数据需要业务模块消费"
      condition: "M12_IOT_GATEWAY == True AND sum(M01..M11) == 0"
      action: "WARN"
      message: "IoT 网关采集的数据需要至少一个业务模块消费，当前无模块可接收数据"
    
    - name: "M01 报工需要 M01 工单"
      description: "报工必须关联工单"
      condition: "M01_WORK_REPORT == True AND M01_WORK_ORDER == False"
      action: "BLOCK"
      message: "报工管理模块必须关联 M01 工单管理模块"
    
    - name: "M11 Excel 数据导入建议关联采集模块"
      description: "Excel 导入的数据需要数据采集模块处理"
      condition: "M11_ENERGY == True AND M12_EXCEL_IMPORT == False AND M12_IOT_GATEWAY == False"
      action: "WARN"
      message: "能碳模块建议搭配 M12 数据采集模块，当前仅支持手动录入"
  
  # === 数据路由规则 ===
  routing:
    - data_type: "device"
      rules:
        - when: "M02_EQUIPMENT == True"
          strategy: "tpm_equipment"
        - default: "energy_device_self"
    
    - data_type: "alert"
      rules:
        - when: "M05_ANDON_CALL == True"
          strategy: "andon_linked"
        - default: "energy_alert_only"
```

### 11.3 [rev] 模块间依赖矩阵（Item 12）

已实现模块（M00~M13）间的正式依赖关系表：

| # | 模块 | 依赖模块 | 依赖强度 | 说明 |
|:-:|:-----|:---------|:---------|:------|
| 1 | M01 报工管理 | M01 工单管理 | 🔴 BLOCK | 报工必须关联工单 |
| 2 | M02 保养计划 | M02 设备档案 | 🔴 BLOCK | 保养计划依赖于设备档案 |
| 3 | M03 品质检验 | M02 设备档案 | 🔴 BLOCK | 品质检测需关联检测设备 |
| 4 | M03 品质检验 | M01 工单管理 | 🟡 WARN | 品质管理与生产管理存在强关联 |
| 5 | M05 安灯呼叫 | M02 设备档案 | 🔴 BLOCK | 安灯呼叫必须关联设备 |
| 6 | M11 能碳管理 | M02 设备档案 | 🟡 WARN | 无设备时能碳功能受限（设备联动不可用） |
| 7 | M11 能碳管理 | M01 报工管理 | 🟡 WARN | 碳足迹核算需要产量数据 |
| 8 | M11 能碳管理 | M12 IoT 网关 | 🟡 WARN | 实时监测需要 IoT 时序数据 |
| 9 | M11 能碳管理 | M12 数据采集 | 🟡 WARN | 能效分析需要数据采集输入 |
| 10 | M12 IoT 网关 | 任一业务模块 | 🟡 WARN | IoT 采集数据需要业务模块消费 |
| 11 | M13 看板 | 任一业务模块 | 🔴 BLOCK | 无数据源时无法展示 |
| 12 | M00 系统管理 | 无 | 🟢 独立 | 全平台基础模块，无外部依赖 |

**依赖强度说明**：
- 🔴 BLOCK：强依赖，选择该模块时必须同时选择依赖模块
- 🟡 WARN：建议依赖，未选择时功能受限或降级运行
- 🟢 独立：无外部依赖，可独立运行

### 11.4 规则解析器

```python
# app/core/scenario_engine.py

import yaml
from typing import Dict, List
from app.core.route_resolver import DataType, RouteStrategy


class ScenarioEngine:
    """场景规则引擎 — 替代枚举表"""
    
    def __init__(self, rules_path: str = "app/core/scenario_rules.yaml"):
        with open(rules_path, "r") as f:
            self._rules = yaml.safe_load(f)
    
    def validate(self, feature_flags: Dict[str, bool]) -> List[Dict]:
        """验证套餐配置，返回约束违规列表"""
        violations = []
        for constraint in self._rules.get("constraints", []):
            if self._eval_condition(constraint["condition"], feature_flags):
                violations.append({
                    "type": constraint["action"],
                    "message": constraint["message"],
                })
        return violations
```

---

## 12. 风险矩阵与缓解措施

### 12.1 风险总表

| # | 风险描述 | 级别 | 发生概率 | 影响 | 缓解措施 |
|:-:|:---------|:----:|:--------:|:----|:---------|
| R1 | FeatureFlag 无缓存导致频繁 DB 查询 | 🟡 中 | 中 | JWT 方案零额外查询，无需额外缓存 |
| R2 | 条件分支随模块增长爆炸 | 🔴 高 | 高 | 引入 DataRouteResolver 声明式路由，新增模块只需加一行配置 |
| R3 | 跨模块调用导致不期望的事务回滚 | 🟡 中 | 低 | [rev] 已明确为非阻断模式（Q-B6），告警成功 + 安灯异步重试 |
| R4 | 独立部署模式下源系统功能遗漏 | 🟡 中 | 高 | 逐条盘点 52 个待迁移端点，按优先级排期 |
| R5 | Excel 导入兜底方案不可用（M12 未就位） | 🔴 高 | 中 | 确认 M12 Excel 导入模块的完成状态，若未完成需 Markdown 表格导入等替代方案 |
| R6 | SaaS 代码与源系统代码同步维护的负担 | 🟡 中 | 中 | 明确定义"能碳是知微云的一个模块"，源系统仅保留作为独立部署版本的基线 |
| R7 | **[rev] 独立部署认证密钥不一致导致 401** | 🔴 高 | 中 | 已统一密钥方案（Item 14），standalone_auth.py 复用 security.py JWT 逻辑 |

### 12.2 缓解措施详情

**R2（条件分支爆炸）**：
- 引入 `DataRouteResolver`（见第 4 节），将条件路由从 Repo 方法中抽离
- 新增模块时只需在 `ROUTES` 字典中添加一个条目

**R3（跨模块事务回滚）**：
- 明确标注每个跨模块方法的事务边界类型
- Phase 1 接受同事务联动；Phase 2 升级为消息队列

**R5（Excel 导入依赖）**：
- 验证 M12 模块的当前完成状态
- 若 M12 未就位，提供备选方案：在 M11 内部实现轻量 CSV 导入功能

---

## 13. [rev] 实施路线图（修正版）

> **[rev] 基于"独立系统同步"新认知，路线图修正为 Phase 1a/1b/2 三段结构。** Phase 1a 聚焦架构修正和同步层建设，Phase 1b 迁移核心功能，Phase 2 增强。

### 13.1 [rev] Phase 1a（当前 Sprint）— 架构修正

| 优先级 | 任务 | 工时 | 前置依赖 |
|:------|:-----|:----|:---------|
| P0 | Tenant 模型新增 package_modules JSONB + Alembic 迁移 | 1h | 无 |
| P0 | 修改 security.py + auth_service.py（JWT 写入 features） | 2h | Tenant 模型改造 |
| P0 | 搭建测试基础设施（conftest.py + pytest-asyncio + 场景 fixture） | 2h | 无 |
| P0 | 实现 FeatureFlag JWT 注入 + 依赖注入改造（dependencies.py） | 2h | security.py 改造 |
| P0 | 引入 DataRouteResolver 路由解析器（含 PersonaRouter 模板） | 1h | 无 |
| P0 | [rev] 实现 change_log 事件表（平台端同步基础） | 2h | 无 |
| P0 | [rev] 实现事件拉取 API（供 M11 调用） | 2h | change_log 表 |
| P0 | [rev] 实现 M11 端事件消费服务（定时拉取 change_log） | 3h | 事件拉取 API |
| P0 | MultiTenantRepository 基类支持 feature_flags | 0.5h | 无 |
| P0 | [rev] 修正 EnergyRepository：简化读路径，本地 DB 优先 | 2h | FeatureFlag + RouteResolver |
| P0 | [rev] 定义标准 Excel 导入模板规范 (V1) | 2h | 无 |
| P0 | [rev] 实现 M11 Excel 导入功能（独立模式核心） | 4h | 模板规范 |
| P1 | RouteResolver 单元测试（覆盖全部 15+ 路由组合） | 2h | RouteResolver 完成 |
| P1 | M11 独立部署模式（SQLite + 统一认证 + 前端构建） | 4h | 条件路由改造完成 |
| | **Phase 1a 小计** | **~29-32h** | — |

### 13.2 [rev] Phase 1b（下个 Sprint）— 核心功能迁移

| 优先级 | 任务 | 工时 | 前置依赖 |
|:------|:-----|:----|:---------|
| P1 | 迁移能效分析（analysis.py 4 个端点）+ 集成测试 | 5h | Phase 1a 完成 |
| P1 | 迁移实时监测（monitoring.py 4 个端点）+ 集成测试 | 5h | Phase 1a 完成 |
| P1 | 迁移 Dashboard（dashboard.py 3 个端点）+ 集成测试 | 3h | Phase 1a 完成 |
| P1 | 迁移碳足迹（carbon.py 6 个端点）+ 集成测试 | 8h | Phase 1a 完成 |
| P1 | 跨模块事务测试（内存 SQLite：告警联动场景） | 2h | EnergyRepository 改造 |
| P1 | [rev] FeatureFlag 体系落地（同平台模块路由测试） | 2h | Phase 1a 完成 |
| | **Phase 1b 小计** | **~25h** | — |

### 13.3 [rev] Phase 2（后续 Sprint）— 增强

| 优先级 | 任务 | 工时 | 前置依赖 |
|:------|:-----|:----|:---------|
| P2 | 告警联动异步化（消息队列解耦 + 完整重试队列机制） | 5h | Phase 1b 完成 |
| P2 | 迁移大屏（bigscreen.py 7 个端点）+ 集成测试 | 5h | Phase 1b 完成 |
| P2 | 迁移供应商（supplier.py 5 个端点）+ 集成测试 | 5h | 供应商归属决策完成 |
| P2 | 迁移能效优化（efficiency.py 3 个端点）+ 集成测试 | 5h | Phase 1b 完成 |
| P2 | 迁移数据源配置（datasource.py 4 个端点）+ 集成测试 | 4h | Phase 1b 完成 |
| P2 | 迁移碳资产（system.py 碳资产相关）+ 集成测试 | 2h | 碳资产模块归属决策完成 |
| P2 | [rev] T+1 数据对账机制 | 3h | Phase 1b 完成 |
| P2 | [rev] 事件推送升级为 Redis Stream / 消息队列 | 4h | Phase 1b 完成 |
| P2 | 5 大画像端到端测试（A~E） | 4h | Phase 1b 测试基础设施 |
| | **Phase 2 小计** | **~37h** | — |

### 13.4 [rev] 修正影响分析

| 原计划 | 修正后 | 影响 |
|:-------|:-------|:-----|
| DataRouteResolver 覆盖所有模块 | 限于同平台模块（B/C/D） | 代码复用度降低 30%，但架构清晰度提升 |
| EnergyRepo 用路由做 JOIN/自查切换 | EnergyRepo 统一读本地 DB | `energy_repo.py` 代码量减少约 40% |
| 没有同步层设计 | 需新增 sync 层（3 个文件） | 新增约 400-600 行代码 |
| Excel 导入为兜底方案 | Excel 导入为独立模式核心能力 | 优先级从 P2 提升至 P0 |
| 7 个模块 FeatureFlag 全覆盖 | 先做 M11 同步 + Excel 导入 | FeatureFlag 体系延后到 Phase 1b |
| 源系统 API 迁移 52 个端点 | 先迁移核心能碳功能（~24 个端点） | 范围不变，顺序微调 |

### 13.5 [rev] 依赖清单

| 依赖 | 版本要求 | 用途 | 新增/原有 |
|:-----|:---------|:------|:----------|
| `python-jose[cryptography]` | ≥3.3.0 | JWT 编解码 | 原有 |
| `aiosqlite` | ≥0.20.0 | SQLite 异步引擎（独立部署模式） | **新增** |
| `pyyaml` | ≥6.0 | 场景规则引擎 YAML 解析 | **新增** |
| `openpyxl` | ≥3.1.0 | Excel 文件解析（导入核心） | **新增** |
| `pytest` | ≥8.0 | 测试框架 | **新增**（dev） |
| `pytest-asyncio` | ≥0.24 | 异步测试支持 | **新增**（dev） |
| `httpx` | ≥0.27 | HTTP 测试客户端 | **新增**（dev） |

### 13.6 [rev] 交付物检查清单（修正版）

- [ ] `app/models/tenant.py` — [rev] 新增 package_modules JSONB 字段
- [ ] `app/core/security.py` — [rev] create_access_token 新增 features 参数
- [ ] `app/services/auth_service.py` — [rev] login 写入 features 到 JWT
- [ ] `app/core/dependencies.py` — [rev] FeatureFlag JWT 注入 + get_current_user_claims
- [ ] `app/core/route_resolver.py` — [rev] DataRouteResolver + PersonaRouter（加适用范围注释）
- [ ] `app/repositories/energy_repo.py` — [rev] 简化读路径 + 条件路由（同平台场景）
- [ ] `app/repositories/base.py` — [rev] MultiTenantRepository 支持 feature_flags
- [ ] `app/core/standalone_auth.py` — [rev] 复用 security.py 统一密钥
- [ ] `app/core/config.py` — [rev] 统一 JWT_SECRET_KEY，移除 STANDALONE_JWT_SECRET
- [ ] `app/sync/change_log_service.py` — **[rev] 新增** 平台端变更日志服务
- [ ] `app/sync/event_pull_api.py` — **[rev] 新增** M11 拉取变更的 API 端点
- [ ] `app/sync/sync_consumer.py` — **[rev] 新增** M11 端事件消费服务
- [ ] `app/sync/sync_reconciler.py` — **[rev] 新增** T+1 对账服务
- [ ] `app/import/excel_importer.py` — **[rev] 新增** 统一 Excel 导入服务
- [ ] `app/import/templates/` — **[rev] 新增** 导入模板定义目录
- [ ] `app/import/validator_factory.py` — **[rev] 新增** 分层校验器工厂
- [ ] `app/core/scenario_rules.yaml` — [rev] 扩展至 12 条约束规则
- [ ] `app/core/scenario_engine.py` — 场景规则解析器
- [ ] `app/core/persona_router.py` — [rev] 新增画像路由模板
- [ ] `app/services/retry_service.py` — [rev] 新增安灯联动异步重试服务
- [ ] `backend/requirements.txt` — [rev] 新增 aiosqlite + pyyaml + openpyxl
- [ ] `tests/scenarios/` — 场景驱动的集成测试
- [ ] `docs/architecture/sync-integration-design.md` — **[rev] 新增** 同步层架构设计文档
- [ ] `docs/standards/excel-import-template-spec.md` — **[rev] 新增** Excel 模板规范文档
- [ ] P1 端点迁移完成（24 个端点，~19h）+ 测试覆盖
- [ ] P2 端点迁移完成（28 个端点，~9h）+ 测试覆盖

---

## 附录 A：文件变更汇总

| 文件路径 | 操作 | 说明 |
|:---------|:----|:------|
| `app/core/dependencies.py` | 修改 | 新增 `get_feature_flags` 依赖注入；[v1.2] 加适用范围注释 |
| `app/core/route_resolver.py` | **新增** | DataRouteResolver 路由解析器；[v1.2] 加适用范围注释（仅同平台模块） |
| `app/core/scenario_rules.yaml` | **新增** | 场景规则引擎配置 |
| `app/core/scenario_engine.py` | **新增** | 场景规则解析器 |
| `app/core/config.py` | 修改 | 新增 M11_STANDALONE / STANDALONE_DB_URL 等配置 |
| `app/core/standalone_auth.py` | **新增** | M11 独立系统精简认证 |
| `app/core/database.py` | 修改 | 支持 SQLite 引擎切换 |
| `app/repositories/base.py` | 修改 | MultiTenantRepository 支持 feature_flags |
| `app/repositories/energy_repo.py` | 修改 | [v1.2] 简化读路径，本地 DB 优先；同平台场景保留条件路由 |
| `app/repositories/andon_repo.py` | 无修改 | 被 EnergyRepo 复用 |
| `app/api/energy.py` | 修改 | 端点适配条件路由 |
| `app/main.py` | 修改 | 支持独立部署模式启动 |
| `app/models/energy.py` | 修改 | [v1.2] 新增 data_source/source_id/sync_version 来源字段 |
| `app/sync/change_log_service.py` | **[v1.2] 新增** | 平台端变更日志服务（同步层基础） |
| `app/sync/event_pull_api.py` | **[v1.2] 新增** | M11 拉取变更的 API 端点 |
| `app/sync/sync_consumer.py` | **[v1.2] 新增** | M11 端事件消费服务 |
| `app/sync/sync_reconciler.py` | **[v1.2] 新增** | T+1 对账服务 |
| `app/import/excel_importer.py` | **[v1.2] 新增** | 统一 Excel 导入服务 |
| `app/import/templates/` | **[v1.2] 新增** | 导入模板定义目录 |
| `app/import/validator_factory.py` | **[v1.2] 新增** | 分层校验器工厂 |
| `migrations/standalone/v001_initial.sql` | **新增** | 独立部署 SQLite 迁移 |
| `tests/scenarios/conftest.py` | **新增** | 场景测试 fixture |
| `tests/scenarios/routes/test_device_routes.py` | **新增** | 设备路由策略测试 |
| `tests/scenarios/routes/test_alert_routes.py` | **新增** | 告警路由策略测试 |
| `tests/scenarios/routes/test_emission_routes.py` | **新增** | 碳排放路由策略测试 |
| `app/core/persona_router.py` | **[rev] 新增** | 画像驱动的路由模板（Item 10） |
| `app/services/retry_service.py` | **[rev] 新增** | 安灯联动异步重试服务（Q-B6） |
| `app/models/tenant.py` | **[rev] 修改** | 新增 package_modules JSONB 字段（E-B1） |
| `app/core/security.py` | **[rev] 修改** | create_access_token 新增 features 参数（E-B2） |
| `app/services/auth_service.py` | **[rev] 修改** | login 写入 features 到 JWT（E-B2） |
| `backend/requirements.txt` | **[rev] 修改** | 新增 aiosqlite + pyyaml + openpyxl（E-B4） |
| `docs/architecture/sync-integration-design.md` | **[v1.2] 新增** | 同步层架构设计文档 |
| `docs/standards/excel-import-template-spec.md` | **[v1.2] 新增** | Excel 模板规范文档 |

---

## 附录 B：FeatureFlag 命名规范

所有 FeatureFlag 遵循以下命名规范，新增模块严格按此格式：

```
M{两位模块号}_{英文功能描述}
```

| Flag 名 | 含义 | 对应模块 |
|:--------|:-----|:---------|
| M01_WORK_ORDER | 工单管理 | M01 生产 |
| M01_WORK_REPORT | 报工管理 | M01 生产 |
| M02_EQUIPMENT | 设备档案 | M02 TPM |
| M02_MAINTENANCE | 保养计划 | M02 TPM |
| M03_QUALITY | 品质检验 | M03 品质 |
| M05_ANDON_CALL | 安灯呼叫 | M05 安灯 |
| M11_ENERGY | 能碳管理 | M11 能碳 |
| M12_EXCEL_IMPORT | Excel 导入 | M12 数据采集 |
| M12_IOT_GATEWAY | IoT 网关 | M12 数据采集 |
| M13_DASHBOARD | 看板 | M13 看板 |

---

*文档结束*
