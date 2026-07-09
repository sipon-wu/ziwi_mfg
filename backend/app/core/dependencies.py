# FastAPI 依赖注入：获取当前用户、获取DB session、租户感知的Repo工厂
from typing import Any, Callable, Dict, Type, TypeVar
from fastapi import Depends, HTTPException, Header
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from app.core.database import get_db
from app.core.security import verify_token
from app.repositories.user_repo import UserRepository

T = TypeVar("T")

security_scheme = HTTPBearer()

async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(security_scheme),
    x_tenant_id: str = Header(default=None, alias="X-Tenant-Id"),
    db: AsyncSession = Depends(get_db),
):
    payload = verify_token(credentials.credentials)
    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail={"code": "401-1001", "message": "Token 无效"})
    
    repo = UserRepository(db)
    # 如果是SaaS模式，注入tenant_id
    if x_tenant_id:
        repo.set_tenant_id(x_tenant_id)
    
    user = await repo.get(int(user_id))
    if not user:
        raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "用户不存在"})
    
    # [rev] 将从 JWT 解析的 features 合并到返回结果，供 get_feature_flags 使用
    user["features"] = payload.get("features", {})
    return user


def get_feature_flags(
    current_user: dict = Depends(get_current_user),
) -> Dict[str, bool]:
    """从当前用户的 JWT claims 中解析 feature_flags。

    若 JWT 中无 features 字段（旧 Token），返回空 dict（等同无模块可用）。
    套餐变更后需调用 /api/v1/tenant/refresh-features 刷新 JWT。

    Returns:
        Dict[str, bool]: feature_flags dict，如 {"M02_EQUIPMENT": True, ...}
    """
    features = current_user.get("features", {})
    return features


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
