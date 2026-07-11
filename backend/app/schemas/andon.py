from pydantic import BaseModel, ConfigDict, Field
from typing import Optional, List
from datetime import datetime


# ==================== 安灯呼叫 ====================

class AndonCallResponse(BaseModel):
    id: int
    tenant_id: str
    call_no: str
    call_type: str
    source: Optional[str] = "manual"
    equipment_id: Optional[int] = None
    work_order_id: Optional[int] = None
    station: Optional[str] = None
    caller_id: int
    caller_name: Optional[str] = None
    description: str
    call_title: str = Field(validation_alias="description", serialization_alias="call_title")
    source_desc: Optional[str] = Field(validation_alias="station", default=None, serialization_alias="source_desc")
    priority: str = "normal"
    status: str = "pending"
    acknowledged_at: Optional[datetime] = None
    acknowledged_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    resolved_by: Optional[int] = None
    resolution: Optional[str] = None
    escalation_level: int = 0
    response_count: int = 0
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateAndonCallRequest(BaseModel):
    call_type: str
    source: Optional[str] = "manual"
    equipment_id: Optional[int] = None
    work_order_id: Optional[int] = None
    station: Optional[str] = None
    caller_name: Optional[str] = None
    description: str
    priority: Optional[str] = "normal"
    response_deadline: Optional[datetime] = None
    resolve_deadline: Optional[datetime] = None


class UpdateAndonCallStatusRequest(BaseModel):
    status: str
    resolution: Optional[str] = None


# ==================== 安灯响应 ====================

class AndonResponseResponse(BaseModel):
    id: int
    tenant_id: str
    andon_call_id: int
    responder_id: int
    responder_name: Optional[str] = None
    action: str
    comment: Optional[str] = None
    response_time_seconds: Optional[int] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class CreateAndonResponseRequest(BaseModel):
    action: str
    comment: Optional[str] = None


# ==================== M11 升级规则 ====================

class AndonEscalationRuleCreate(BaseModel):
    rule_name: str
    call_type: str
    priority: str = "all"
    level: int
    timeout_minutes: int
    notify_role: Optional[str] = None
    notify_users: Optional[str] = None
    notify_channels: Optional[str] = None
    is_active: bool = True


class AndonEscalationRuleUpdate(BaseModel):
    rule_name: Optional[str] = None
    call_type: Optional[str] = None
    priority: Optional[str] = None
    level: Optional[int] = None
    timeout_minutes: Optional[int] = None
    notify_role: Optional[str] = None
    notify_users: Optional[str] = None
    notify_channels: Optional[str] = None
    is_active: Optional[bool] = None


class AndonEscalationRuleResponse(BaseModel):
    id: int
    tenant_id: str
    rule_name: str
    call_type: str
    priority: str = "all"
    level: int
    timeout_minutes: int
    notify_role: Optional[str] = None
    notify_users: Optional[str] = None
    notify_channels: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)


class AndonEscalationLogResponse(BaseModel):
    id: int
    tenant_id: str
    andon_call_id: int
    escalation_level: int
    triggered_at: Optional[datetime] = None
    timeout_minutes: Optional[int] = None
    notified_users: Optional[str] = None
    notify_channels: Optional[str] = None
    response_status: str = "pending"
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)
