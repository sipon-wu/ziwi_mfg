from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime


# ── 等级 ────────────────────────────────────────────────────

class PpapLevelResponse(BaseModel):
    id: int
    level_no: int
    level_name: str
    is_default: bool = False
    is_custom: bool = False
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreatePpapLevelRequest(BaseModel):
    level_no: int
    level_name: str
    is_default: bool = False
    is_custom: bool = False
    remark: Optional[str] = None


class UpdatePpapLevelRequest(BaseModel):
    level_name: Optional[str] = None
    is_default: Optional[bool] = None
    is_custom: Optional[bool] = None
    remark: Optional[str] = None


# ── 要素模板 ────────────────────────────────────────────────

class PpapElementResponse(BaseModel):
    id: int
    element_code: str
    element_name: str
    description: Optional[str] = None
    is_required: bool = True
    sort_order: int = 0
    customer_id: Optional[int] = None
    level_no: int
    has_template: bool = False
    template_file_url: Optional[str] = None

    model_config = ConfigDict(from_attributes=True)


class CreatePpapElementRequest(BaseModel):
    element_code: str
    element_name: str
    description: Optional[str] = None
    is_required: bool = True
    sort_order: int = 0
    customer_id: Optional[int] = None
    level_no: int
    has_template: bool = False
    template_file_url: Optional[str] = None


class UpdatePpapElementRequest(BaseModel):
    element_name: Optional[str] = None
    description: Optional[str] = None
    is_required: Optional[bool] = None
    sort_order: Optional[int] = None
    has_template: Optional[bool] = None
    template_file_url: Optional[str] = None


# ── 提交记录 ────────────────────────────────────────────────

class PpapSubmissionResponse(BaseModel):
    id: int
    submission_no: str
    product_id: int
    customer_id: int
    level_no: int
    version: int = 1
    status: str = "draft"
    submitted_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    change_note: Optional[str] = None
    due_reminder: bool = False
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BuildSubmissionRequest(BaseModel):
    product_id: int
    customer_id: int
    level_no: int
    change_note: Optional[str] = None


class UpdateSubmissionItemRequest(BaseModel):
    status: Optional[str] = None
    file_path: Optional[str] = None
    file_name: Optional[str] = None
    assignee_id: Optional[int] = None
    remark: Optional[str] = None


class ApproveSubmissionRequest(BaseModel):
    status: str  # approved / rejected / conditional
    comment: Optional[str] = None


class CompletenessResponse(BaseModel):
    is_complete: bool = False
    missing_elements: List[dict] = []
    total: int = 0
    completed: int = 0
    not_applicable: int = 0
