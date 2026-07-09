from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


class TenantResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    status: str
    industry: Optional[str] = None
    region: Optional[str] = None
    expire_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateTenantRequest(BaseModel):
    name: str
    code: str
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None


class UpdateTenantRequest(BaseModel):
    name: Optional[str] = None
    contact_name: Optional[str] = None
    contact_phone: Optional[str] = None
    industry: Optional[str] = None
    region: Optional[str] = None
