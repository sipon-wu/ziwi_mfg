from pydantic import BaseModel, ConfigDict
from typing import Optional, List, Any
from datetime import datetime

class ApprovalTemplateResponse(BaseModel):
    id: int; name: str; code: str; biz_type: Optional[str] = None
    form_schema: Optional[Any] = None; created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateApprovalTemplateRequest(BaseModel):
    name: str; code: str; biz_type: Optional[str] = None; form_schema: Optional[Any] = None

class ApprovalNodeResponse(BaseModel):
    id: int; node_order: int; approver_id: Optional[int] = None
    node_type: str; status: str; comment: Optional[str] = None
    operated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ApprovalInstanceResponse(BaseModel):
    id: int; template_id: int; title: str; biz_type: Optional[str] = None
    biz_id: Optional[str] = None; applicant_id: int; status: str
    form_data: Optional[Any] = None; nodes: List[ApprovalNodeResponse] = []
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class CreateApprovalRequest(BaseModel):
    template_id: int; title: str; biz_type: Optional[str] = None
    biz_id: Optional[str] = None; form_data: Optional[Any] = None; approver_ids: List[int]

class ApproveActionRequest(BaseModel):
    action: str = "approve"  # approve/reject
    comment: Optional[str] = None
