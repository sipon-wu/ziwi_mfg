from pydantic import BaseModel, EmailStr
from typing import Optional
import uuid
from datetime import datetime


class UserRegisterRequest(BaseModel):
    email: EmailStr
    password: str
    display_name: str
    tenant_id: Optional[str] = None


class UserResponse(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    tenant_id: Optional[str]
    products: list
    is_active: bool
    created_at: datetime

    model_config = {"from_attributes": True}
