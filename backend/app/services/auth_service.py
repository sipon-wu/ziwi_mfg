# 认证服务：登录/登出/Token 刷新
from typing import Dict, Optional
from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.repositories.tenant_repo import TenantRepository
from app.core.security import hash_password, verify_password, create_access_token, create_refresh_token, verify_token
from app.schemas.auth import LoginRequest
from app.schemas.user import UserInfo
from fastapi import HTTPException
from datetime import timedelta

class AuthService:
    def __init__(self, user_repo: UserRepository, role_repo: RoleRepository, tenant_repo: Optional[TenantRepository] = None):
        self.user_repo = user_repo
        self.role_repo = role_repo
        self.tenant_repo = tenant_repo

    async def login(self, req: LoginRequest) -> dict:
        user = await self.user_repo.get_with_password(req.username, req.tenant_id)
        if not user or not verify_password(req.password, user["password_hash"]):
            raise HTTPException(status_code=401, detail={"code": "401-0000", "message": "用户名或密码错误"})
        
        if user["status"] != "active":
            raise HTTPException(status_code=403, detail={"code": "403-0000", "message": "账号已被禁用"})
        
        # 更新最后登录时间
        await self.user_repo.update_last_login(user["id"])
        
        # [rev] 获取租户套餐信息并转换为 feature_flags
        features: Dict[str, bool] = {}
        if self.tenant_repo:
            tenant = await self.tenant_repo.get_by_tenant_id(user["tenant_id"])
            if tenant:
                package_modules = tenant.get("package_modules", {})
                # 将 package_modules 转换为扁平的 feature_flags dict
                # 格式: {"M01": ["WORK_ORDER", "WORK_REPORT"]} → {"M01_WORK_ORDER": True, "M01_WORK_REPORT": True}
                features = {}
                for module_code, sub_modules in package_modules.items():
                    for sub in sub_modules:
                        flag_key = f"{module_code}_{sub}"
                        features[flag_key] = True
        
        # 生成 Token（含 features）
        access_token = create_access_token(
            {"sub": str(user["id"]), "tenant_id": user["tenant_id"]},
            features=features,
        )
        refresh_token = create_refresh_token({"sub": str(user["id"]), "tenant_id": user["tenant_id"]})
        
        # 获取用户信息（含角色）
        user_info = await self.user_repo.get(user["id"])
        
        return {
            "access_token": access_token,
            "token_type": "bearer",
            "expires_in": 1800,
            "refresh_token": refresh_token,
            "user": user_info
        }

    async def refresh_token(self, refresh_token: str) -> dict:
        payload = verify_token(refresh_token)
        if payload.get("type") != "refresh":
            raise HTTPException(status_code=401, detail={"code": "401-1001", "message": "无效的刷新令牌"})
        
        user_id = payload.get("sub")
        user = await self.user_repo.get(int(user_id))
        if not user:
            raise HTTPException(status_code=404, detail={"code": "404-0000", "message": "用户不存在"})
        
        # 保留原 JWT 中的 features（若有）
        features = payload.get("features")
        new_access_token = create_access_token(
            {"sub": str(user_id), "tenant_id": user["tenant_id"]},
            features=features,
        )
        return {"access_token": new_access_token, "token_type": "bearer", "expires_in": 1800}

    async def change_password(self, user_id: int, old_password: str, new_password: str) -> None:
        user = await self.user_repo.get_with_password_by_id(user_id)
        if not user or not verify_password(old_password, user["password_hash"]):
            raise HTTPException(status_code=400, detail={"code": "400-0000", "message": "原密码错误"})
        
        new_hash = hash_password(new_password)
        await self.user_repo.update(user_id, {"password_hash": new_hash})
