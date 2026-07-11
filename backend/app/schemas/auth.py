"""认证模块 Pydantic Schema。

变更说明 (2026-07-10):
- 移除: LoginRequest, LoginResponse, RefreshTokenRequest（不再本地签发 JWT）
- 保留: ChangePasswordRequest
- 变更 (2026-07-11): 恢复 LoginRequest + LoginResponse 作为代理转发用
"""

from pydantic import BaseModel


class LoginRequest(BaseModel):
    """登录请求（代理转发到 cloud.ziwi.cn）。"""
    username: str
    password: str
    tenant_id: str | None = None


class LoginResponse(BaseModel):
    """登录响应（透传 cloud.ziwi.cn 响应）。"""
    token_type: str = "bearer"
    access_token: str
    expires_in: int | None = None


class ChangePasswordRequest(BaseModel):
    """修改密码请求。"""
    old_password: str
    new_password: str
