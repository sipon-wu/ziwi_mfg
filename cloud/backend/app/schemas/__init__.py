from datetime import datetime
from typing import Optional
from pydantic import BaseModel, EmailStr, Field


# ============================================================
# Platform User
# ============================================================

class PlatformUserCreate(BaseModel):
    email: str = Field(..., max_length=255)
    password: str = Field(..., min_length=6, max_length=128)
    display_name: str = Field(..., max_length=64)
    role: str = Field(...)  # super_admin / operator / sales / devops / finance / implementation
    phone: Optional[str] = None
    business_lines: list[str] = Field(default_factory=list)
    region: Optional[str] = None
    region_province: Optional[str] = None
    region_city: Optional[str] = None


class PlatformUserUpdate(BaseModel):
    display_name: Optional[str] = None
    phone: Optional[str] = None
    is_active: Optional[bool] = None
    business_lines: Optional[list[str]] = None
    region: Optional[str] = None
    region_province: Optional[str] = None
    region_city: Optional[str] = None


class PlatformUserResponse(BaseModel):
    id: str
    email: str
    display_name: str
    role: str
    phone: Optional[str] = None
    is_active: bool
    business_lines: list[str]
    region: Optional[str] = None
    region_province: Optional[str] = None
    region_city: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


# ============================================================
# Business Line
# ============================================================

class BusinessLineCreate(BaseModel):
    id: str = Field(..., max_length=32)
    name: str = Field(..., max_length=64)
    description: Optional[str] = None
    sort_order: int = 0


class BusinessLineResponse(BaseModel):
    id: str
    name: str
    description: Optional[str] = None
    is_active: bool
    sort_order: int


# ============================================================
# Auth
# ============================================================

class PlatformLoginRequest(BaseModel):
    email: str
    password: str


class PlatformLoginResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    user: PlatformUserResponse


# ============================================================
# License Ticket
# ============================================================

class LicenseTicketCreate(BaseModel):
    tenant_id: str = Field(..., max_length=64)
    tenant_name: str = Field(..., max_length=128)
    product: str = Field(default="school", max_length=32)
    ticket_type: str = Field(...)  # new / renewal
    current_expires_at: Optional[datetime] = None
    requested_issued_at: Optional[datetime] = None
    requested_expires_at: datetime
    requested_status: str = Field(default="active", max_length=16)
    remarks: Optional[str] = None


class LicenseTicketApprove(BaseModel):
    remarks: Optional[str] = None


class LicenseTicketResponse(BaseModel):
    id: str
    ticket_no: str
    tenant_id: str
    tenant_name: str
    product: str
    ticket_type: str
    current_expires_at: Optional[str] = None
    requested_issued_at: Optional[str] = None
    requested_expires_at: Optional[str] = None
    requested_status: str
    status: str
    applicant_id: Optional[str] = None
    assignee_id: Optional[str] = None
    approver_id: Optional[str] = None
    finance_confirm_by: Optional[str] = None
    paid_at: Optional[str] = None
    approved_at: Optional[str] = None
    remarks: Optional[str] = None
    created_at: Optional[str] = None
    updated_at: Optional[str] = None
