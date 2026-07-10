"""
认证服务：密码修改。

变更说明 (2026-07-10):
- 移除 login() 方法（前端直接调 cloud.ziwi.cn 登录）
- 移除 refresh_token() 方法（前端直接调 cloud 刷新 token）
- 保留 change_password() 方法（修改 mfg 本地 DB 密码）
- 简化构造函数（不再需要 TenantRepository 参数）
"""

from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.core.security import hash_password, verify_password
from fastapi import HTTPException


class AuthService:
    """认证服务 — 本地密码管理。

    注意：登录和 token 刷新已迁移至 cloud.ziwi.cn 统一 IdP，
    本服务仅保留本地密码修改功能。
    """

    def __init__(self, user_repo: UserRepository, role_repo: RoleRepository):
        """初始化认证服务。

        Args:
            user_repo: 用户仓储
            role_repo: 角色仓储（保留参数兼容性，change_password 暂不使用）
        """
        self.user_repo = user_repo
        self.role_repo = role_repo

    async def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        """修改 mfg 本地用户密码。

        验证旧密码后，将新密码的 bcrypt 哈希写入数据库。
        注意：此方法修改的是 mfg 本地 DB 密码，不涉及 cloud.ziwi.cn 的密码。

        Args:
            user_id: 用户 ID（mfg 本地自增主键）
            old_password: 旧密码明文
            new_password: 新密码明文

        Raises:
            HTTPException 400: 旧密码错误或用户不存在
        """
        user = await self.user_repo.get_with_password_by_id(user_id)
        if not user or not verify_password(old_password, user["password_hash"]):
            raise HTTPException(
                status_code=400,
                detail={"code": "400-0000", "message": "原密码错误"},
            )

        new_hash = hash_password(new_password)
        await self.user_repo.update(user_id, {"password_hash": new_hash})
