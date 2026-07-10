"""认证模块 Pydantic Schema。

变更说明 (2026-07-10):
- 移除: LoginRequest, TokenResponse, RefreshTokenRequest（不再本地签发 JWT）
- 保留: ChangePasswordRequest
"""

from pydantic import BaseModel


class ChangePasswordRequest(BaseModel):
    """修改密码请求。"""
    old_password: str
    new_password: str
