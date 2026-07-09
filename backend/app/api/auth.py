from fastapi import APIRouter, Depends
from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.services.auth_service import AuthService
from app.schemas.auth import LoginRequest, RefreshTokenRequest, ChangePasswordRequest

router = APIRouter(prefix="/api/v1/auth", tags=["M00-认证"])

_no_auth = {"require_auth": False}

@router.post("/login")
async def login(
    req: LoginRequest,
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, **_no_auth)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, **_no_auth)),
):
    svc = AuthService(repo, role_repo)
    return await svc.login(req)

@router.post("/refresh")
async def refresh(
    req: RefreshTokenRequest,
    repo: UserRepository = Depends(get_tenant_repo(UserRepository, **_no_auth)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository, **_no_auth)),
):
    svc = AuthService(repo, role_repo)
    return await svc.refresh_token(req.refresh_token)

@router.post("/logout")
async def logout():
    return {"code": 0, "message": "退出成功"}

@router.post("/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    svc = AuthService(repo, role_repo)
    await svc.change_password(current_user["id"], req.old_password, req.new_password)
    return {"code": 0, "message": "密码修改成功"}

@router.get("/me")
async def get_me(
    current_user: dict = Depends(get_current_user),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    """获取当前登录用户的完整信息（含角色和权限）。"""
    user_id = current_user["id"]
    user = await repo.get(user_id)
    if not user:
        return {"code": 0, "message": "success", "data": current_user}
    roles = await role_repo.get_user_roles(user_id)
    permissions = await role_repo.get_user_permissions(user_id)
    user["roles"] = roles
    user["permissions"] = permissions
    return {"code": 0, "message": "success", "data": user}
