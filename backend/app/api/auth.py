"""
M00-认证 路由模块。

变更说明 (2026-07-10):
- 移除 POST /login（前端直接调 cloud.ziwi.cn 登录）→ 2026-07-11 恢复为代理转发
- 移除 POST /refresh（前端直接调 cloud 刷新 token）
- 保留 POST /logout, GET /me, POST /change-password
- GET /me 适配新 get_current_user（cloud JWT 验签）
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.dependencies import get_current_user, get_tenant_repo
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.services.auth_service import AuthService
from app.schemas.auth import ChangePasswordRequest, LoginRequest

router = APIRouter(prefix="/api/v1/auth", tags=["M00-认证"])

CLOUD_LOGIN_URL = "https://cloud.ziwi.cn/api/v1/auth/login"


@router.post("/login")
async def login(req: LoginRequest):
    """代理登录：转发凭证到 cloud.ziwi.cn IdP，返回 JWT。

    前端保持原有 /auth/login 调用不变，后端代理转发（避免 CORS 问题）。
    cloud 登录使用 email 字段，前端传 username（实际就是 email 地址）。
    """
    async with httpx.AsyncClient(timeout=15) as client:
        try:
            resp = await client.post(
                CLOUD_LOGIN_URL,
                json={"email": req.username, "password": req.password},
            )
        except httpx.RequestError:
            raise HTTPException(status_code=502, detail="认证服务不可达，请稍后重试")

    if resp.status_code != 200:
        body = resp.json()
        detail = body.get("message", body.get("detail", "登录失败"))
        raise HTTPException(status_code=resp.status_code, detail=detail)

    return resp.json()


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
