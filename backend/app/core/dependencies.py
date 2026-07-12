"""
FastAPI 依赖注入：获取当前用户、获取 DB session、租户感知的 Repo 工厂。

变更说明 (2026-07-12):
- get_current_user: 增加本地 JWT 认证降级（子账号不走 cloud，走本地 bcrypt + HS256 JWT）
"""

from typing import Any, Callable, Dict, Type, TypeVar

from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.security import (
    classify_jwt_error,
    TokenVerifyError,
    verify_cloud_token,
    verify_local_token,
)
from app.repositories.user_repo import UserRepository
from app.repositories.tenant_repo import TenantRepository

T = TypeVar("T")

security_scheme = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(security_scheme),
    x_tenant_id: str = Header(default=None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    """验证 JWT 并返回 mfg 本地用户信息（支持 cloud RS256 + 本地 HS256 双通道）。

    认证顺序：
    1. 先试 cloud RS256 JWT（管理员/cloud 用户）
    2. 如果失败则试本地 HS256 JWT（子账号）

    Raises:
        HTTPException 401: token 缺失/无效/过期
        HTTPException 503: cloud JWKS 不可达（仅限 cloud 用户场景）
    """
    # 1. 检查 Authorization header
    if credentials is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "MISSING_TOKEN", "message": "Authorization header 缺失"},
        )

    token = credentials.credentials

    # ── 尝试 cloud JWT 验签（管理员/cloud 用户） ──
    cloud_error = None
    try:
        payload = await verify_cloud_token(token)
    except Exception as e:
        cloud_error = e

    if cloud_error is None:
        # cloud 验签成功 → 按 cloud 用户流程（原逻辑）
        cloud_uuid = payload.get("sub")
        if not cloud_uuid:
            raise HTTPException(
                status_code=401,
                detail={"code": "MISSING_TOKEN", "message": "Token 缺少 sub 声明"},
            )
        try:
            repo = UserRepository(db)
            user = await repo.get_by_cloud_uuid(cloud_uuid)
        except Exception:
            raise HTTPException(
                status_code=503,
                detail={
                    "code": "AUTH_UNAVAILABLE",
                    "message": "认证服务暂不可用，请稍后重试",
                },
            )
        if not user:
            raise HTTPException(
                status_code=401,
                detail={
                    "code": "401-0002",
                    "message": f"用户在 mfg 平台未注册 (cloud_uuid={cloud_uuid})",
                },
            )
        # 注入 tenant_id
        cloud_tenant = payload.get("tenant_id")
        effective_tenant = cloud_tenant or x_tenant_id or user.get("tenant_id")
        if effective_tenant and hasattr(repo, "set_tenant_id"):
            repo.set_tenant_id(effective_tenant)
        # 合并 cloud claims
        user["cloud_uuid"] = cloud_uuid
        user["cloud_email"] = payload.get("email")
        user["cloud_products"] = payload.get("products", [])
        user["tenant_id"] = effective_tenant
        return user

    # ── cloud 验签失败 → 判断是否可降级 ──
    error_code = classify_jwt_error(cloud_error)
    # cloud JWKS 不可达 → 不可降级（基础设施故障）
    if error_code == TokenVerifyError.JWKS_UNAVAILABLE:
        raise HTTPException(
            status_code=503,
            detail={"code": "JWKS_UNAVAILABLE", "message": "认证服务暂不可用"},
        )

    # ── 尝试本地 JWT 验签（子账号降级） ──
    try:
        local_payload = verify_local_token(token)
    except Exception:
        # 本地 JWT 也失败 → 最终 401
        status_map = {
            TokenVerifyError.EXPIRED: (401, "token 已过期，请刷新"),
        }
        http_status, message = status_map.get(error_code, (401, "无效的认证凭证"))
        raise HTTPException(
            status_code=http_status,
            detail={"code": error_code.value, "message": message},
        )

    # 本地 JWT 验签成功 → 按本地用户流程
    user_id = int(local_payload["sub"])
    tenant_id = local_payload.get("tenant_id")
    repo = UserRepository(db)
    user = await repo.get(user_id)
    if not user:
        raise HTTPException(
            status_code=401,
            detail={"code": "401-0002", "message": "用户不存在或已被禁用"},
        )
    # 设置租户（本地用户在 JWT payload 中已含 tenant_id）
    effective_tenant = tenant_id or x_tenant_id or user.get("tenant_id")
    if effective_tenant and hasattr(repo, "set_tenant_id"):
        repo.set_tenant_id(effective_tenant)
    user["tenant_id"] = effective_tenant
    user["auth_type"] = "local"
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
