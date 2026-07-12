"""
M00-认证 路由模块。

变更说明 (2026-07-12):
- POST /login 增加本地认证分支：子账号（用户名不含 @）走本地 bcrypt 验密降级
"""

import httpx
from fastapi import APIRouter, Depends, HTTPException

from app.core.database import get_db
from app.core.dependencies import get_current_user, get_tenant_repo
from app.core.security import create_local_token, verify_password
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.services.auth_service import AuthService
from app.schemas.auth import ChangePasswordRequest, LoginRequest
from sqlalchemy.ext.asyncio import AsyncSession

router = APIRouter(prefix="/api/v1/auth", tags=["M00-认证"])

CLOUD_LOGIN_URL = "https://cloud.ziwi.cn/api/v1/auth/login"


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    """登录（支持本地认证降级 + cloud 代理联登）。

    子账号（用户名不含 @）：走本地 bcrypt 验密 → 签发本地 JWT
    管理员（用户名含 @）：代理转发到 cloud.ziwi.cn → 返回 cloud JWT
    """
    # ── 本地认证降级：子账号走本地 bcrypt 验密 ──
    if '@' not in req.username:
        repo = UserRepository(db)
        user = await repo.get_with_password(req.username, req.tenant_id)
        if not user:
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        if not verify_password(req.password, user.get("password_hash", "")):
            raise HTTPException(status_code=401, detail="用户名或密码错误")
        token = create_local_token(user["id"], user["tenant_id"])
        return {"access_token": token, "token_type": "bearer", "refresh_token": ""}

    # ── cloud 代理登录（原有逻辑） ──
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
