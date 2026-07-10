"""
M00-认证 路由模块。

变更说明 (2026-07-10):
- 移除 POST /login（前端直接调 cloud.ziwi.cn 登录）
- 移除 POST /refresh（前端直接调 cloud 刷新 token）
- 保留 POST /logout, GET /me, POST /change-password
- GET /me 适配新 get_current_user（cloud JWT 验签）
"""

from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.services.auth_service import AuthService
from app.schemas.auth import ChangePasswordRequest

router = APIRouter(prefix="/api/v1/auth", tags=["M00-认证"])


@router.post("/logout")
async def logout():
    """登出。

    服务端无状态（JWT 不存储在后端），客户端自行清理本地 token 即可。
    """
    return {"code": 0, "message": "退出成功"}


@router.get("/me")
async def get_me(
    current_user: dict = Depends(get_current_user),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    """获取当前登录用户的完整信息（含角色和权限）。

    认证方式：cloud.ziwi.cn RS256 JWT 验签。
    """
    user_id = current_user["id"]
    user = await repo.get(user_id)
    if not user:
        return {"code": 0, "message": "success", "data": current_user}

    roles = await role_repo.get_user_roles(user_id)
    permissions = await role_repo.get_user_permissions(user_id)
    user["roles"] = roles
    user["permissions"] = permissions
    user["cloud_uuid"] = current_user.get("cloud_uuid")
    return {"code": 0, "message": "success", "data": user}


@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    """修改当前用户密码（mfg 本地 DB）。

    注意：仅修改 mfg 本地密码，cloud.ziwi.cn 密码请通过 cloud 接口修改。
    """
    svc = AuthService(repo, role_repo)
    await svc.change_password(current_user["id"], req.old_password, req.new_password)
    return {"code": 0, "message": "密码修改成功"}
