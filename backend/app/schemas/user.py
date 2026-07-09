from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class UserInfo(BaseModel):
    id: int
    tenant_id: str
    username: str
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    avatar_url: Optional[str] = None
    status: str
    roles: List[str] = []
    last_login_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateUserRequest(BaseModel):
    username: str
    password: str
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    role_ids: Optional[List[int]] = None


class UpdateUserRequest(BaseModel):
    real_name: Optional[str] = None
    email: Optional[str] = None
    phone: Optional[str] = None
    status: Optional[str] = None
