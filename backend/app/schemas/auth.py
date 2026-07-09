from pydantic import BaseModel, ConfigDict
from typing import Optional


class LoginRequest(BaseModel):
    username: str
    password: str
    tenant_id: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    refresh_token: str
    user: "UserInfo"


class RefreshTokenRequest(BaseModel):
    refresh_token: str


class ChangePasswordRequest(BaseModel):
    old_password: str
    new_password: str
