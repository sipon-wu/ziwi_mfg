"""
FastAPI 依赖注入：获取当前用户、获取 DB session、租户感知的 Repo 工厂。

变更说明 (2026-07-10):
- get_current_user: 改用 cloud JWT (RS256) 验签 + cloud_uuid 查用户
- get_feature_flags: 改为从 DB tenants.package_modules 查询
- get_tenant_repo: 逻辑不变，tenant_id 来源从「本地 JWT」变为「cloud JWT + Header 降级」
"""

from typing import Any, Callable, Dict, Type, TypeVar

from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import verify_cloud_token, classify_jwt_error, TokenVerifyError
from app.repositories.user_repo import UserRepository
from app.repositories.tenant_repo import TenantRepository

T = TypeVar("T")

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_tenant_id: str = Header(default=None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    """验证 cloud JWT 并返回 mfg 本地用户信息。

    流程：
    1. 提取 Bearer token
    2. 调用 cloud JWKS 公钥验签 RS256 JWT
    3. 从 JWT sub (UUID) 查 mfg 本地 users.cloud_uuid
    4. 注入 tenant_id（cloud JWT 优先，X-Tenant-Id Header 降级）
    5. 合并 cloud claims 到 user dict

    Raises:
        HTTPException 401: token 缺失/无效/过期，或用户未在 mfg 注册
        HTTPException 503: cloud JWKS 不可达且无本地缓存
    """
    # 1. 检查 Authorization header
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_TOKEN", "message": "Authorization header 缺失"},
        )

    token = credentials.credentials

    # 2. 验签 cloud JWT
    try:
        payload = await verify_cloud_token(token)
    except Exception as e:
        error_code = classify_jwt_error(e)
        status_map = {
            TokenVerifyError.EXPIRED: (401, "token 已过期，请刷新"),
            TokenVerifyError.JWKS_UNAVAILABLE: (503, "认证服务暂不可用"),
        }
        http_status, message = status_map.get(
            error_code,
            (401, "无效的认证凭证"),
        )
        raise HTTPException(
            status_code=http_status,
            detail={"code": error_code.value, "message": message},
        )

    # 3. 从 cloud JWT 提取用户标识
    cloud_uuid = payload.get("sub")
    if not cloud_uuid:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_TOKEN", "message": "Token 缺少 sub 声明"},
        )

    # 4. 查 mfg 本地用户（按 cloud_uuid 映射）
    repo = UserRepository(db)
    user = await repo.get_by_cloud_uuid(cloud_uuid)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={
                "code": "401-0002",
                "message": f"用户在 mfg 平台未注册 (cloud_uuid={cloud_uuid})",
            },
        )

    # 5. 注入 tenant_id（cloud JWT 优先，X-Tenant-Id Header 降级）
    cloud_tenant = payload.get("tenant_id")
    effective_tenant = cloud_tenant or x_tenant_id
    if effective_tenant and hasattr(repo, "set_tenant_id"):
        repo.set_tenant_id(effective_tenant)

    # 6. 将 cloud claims 合并到 user dict（下游可能依赖）
    user["cloud_uuid"] = cloud_uuid
    user["cloud_email"] = payload.get("email")
    user["cloud_products"] = payload.get("products", [])
    user["tenant_id"] = effective_tenant

    return user


async def get_feature_flags(
    current_user: dict = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
) -> Dict[str, bool]:
    """从 DB tenants.package_modules 查询当前租户的 feature_flags。

    替代旧实现（旧实现从本地 JWT 的 features 字段读取）。
    package_modules 扁平化示例:
        {"M01": ["WORK_ORDER"]} → {"M01_WORK_ORDER": True}

    Args:
        current_user: get_current_user 注入的当前用户 dict
        db: 数据库 session

    Returns:
        扁平化的 feature_flags dict，无租户或无 package_modules 时返回 {}
    """
    tenant_id = current_user.get("tenant_id")
    if not tenant_id:
        return {}

    tenant_repo = TenantRepository(db)
    return await tenant_repo.get_feature_flags_by_tenant_id(tenant_id)


def get_tenant_repo(repo_class: Type[T], require_auth: bool = True) -> Callable[[], T]:
    """统一的租户感知 Repo 依赖工厂。

    自动从当前登录用户提取 tenant_id 并注入到 MultiTenantRepository 实例，
    使 UPDATE/DELETE 操作获得行级租户隔离保护。

    Args:
        repo_class: Repository 类（需继承 MultiTenantRepository）
        require_auth: 是否需要认证。
            True  → 依赖 get_current_user，注入 tenant_id（用于受保护路由）
            False → 仅创建 repo 实例，不设 tenant_id（用于公开路由）

    用法:
        @router.get("/items")
        async def list_items(repo: ItemRepo = Depends(get_tenant_repo(ItemRepo))):
            ...
    """
    if require_auth:

        async def _factory(
            current_user: dict = Depends(get_current_user),
            db: AsyncSession = Depends(get_db),
        ) -> T:
            repo = repo_class(db)
            tenant_id = current_user.get("tenant_id") if current_user else None
            if tenant_id and hasattr(repo, "set_tenant_id"):
                repo.set_tenant_id(tenant_id)
            return repo

    else:

        async def _factory(
            db: AsyncSession = Depends(get_db),
        ) -> T:
            return repo_class(db)

    return _factory
