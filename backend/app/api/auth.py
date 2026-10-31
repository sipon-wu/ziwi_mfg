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
from app.services.audit_service import AuditService, AuditAction
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
        # A-S1 第三环：把「首登必须改密」标志回传给前端。
        # 前端据此弹改密弹窗 —— 不回传的话，用户会被后端的写操作拦截挡住却不知道为什么。
        must_change = bool(user.get("must_change_password"))
        token = create_local_token(user["id"], user["tenant_id"])
        return {
            "access_token": token, "token_type": "bearer", "refresh_token": "",
            "must_change_password": must_change,
        }

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
    db: AsyncSession = Depends(get_db),
    repo: UserRepository = Depends(get_tenant_repo(UserRepository)),
    role_repo: RoleRepository = Depends(get_tenant_repo(RoleRepository)),
):
    """修改当前用户密码（mfg 本地 DB）。

    注意：仅修改 mfg 本地密码，cloud.ziwi.cn 密码请通过 cloud 接口修改。
    """
    svc = AuthService(repo, role_repo)
    try:
        await svc.change_password(current_user["id"], req.old_password, req.new_password)
    except Exception as e:
        # ★失败审计：谁在什么时候尝试改密没成功。**口令错误尝试**本身就是
        # 安全事件，只记成功的审计会完全看不见这类行为。
        audit = AuditService(db)
        await audit.log_fail(
            AuditAction.PASSWORD_CHANGE,
            message=str(e),
            tenant_id=current_user.get("tenant_id"),
            actor_id=current_user["id"],
            actor_name=current_user.get("username"),
            object_type="user",
            object_id=current_user["id"],
        )
        raise
    # A-S1 第三环：改密成功即清除「首登改密」标志。
    # 放在改密之后而不是之前：改密失败却把标志清了，等于给了一个永久免改密的旁路。
    cleared = await repo.clear_must_change_password(current_user["id"])
    audit = AuditService(db)
    await audit.log(
        AuditAction.PASSWORD_CHANGE,
        tenant_id=current_user.get("tenant_id"),
        actor_id=current_user["id"],
        actor_name=current_user.get("username"),
        object_type="user",
        object_id=current_user["id"],
        after={"must_change_password_cleared": cleared},
        message="修改密码",
    )
    return {"code": 0, "message": "密码修改成功", "data": {"must_change_password_cleared": cleared}}
