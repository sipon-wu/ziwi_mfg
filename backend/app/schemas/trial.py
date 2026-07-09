from pydantic import BaseModel, ConfigDict
from typing import Optional, Any, List
from datetime import datetime


# ── 试产工单 ────────────────────────────────────────────────

class TrialOrderResponse(BaseModel):
    id: int
    tenant_id: str
    order_no: str
    trial_type: str
    status: str
    product_id: Optional[int] = None
    product_name: str
    product_spec: Optional[str] = None
    planned_qty: Optional[int] = None
    completed_qty: int = 0
    priority: int = 500
    lab_required: bool = False
    scheme_json: Optional[Any] = None
    target_json: Optional[Any] = None
    key_params: Optional[Any] = None
    source_route_id: Optional[int] = None
    bom_verified: bool = False
    inspection_plan: Optional[Any] = None
    started_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    terminated_reason: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateTrialOrderRequest(BaseModel):
    trial_type: str
    product_id: Optional[int] = None
    product_name: str
    product_spec: Optional[str] = None
    planned_qty: Optional[int] = None
    priority: int = 500
    lab_required: bool = False
    scheme_json: Optional[Any] = None
    target_json: Optional[Any] = None
    key_params: Optional[Any] = None
    inspection_plan: Optional[Any] = None


class UpdateTrialOrderRequest(BaseModel):
    product_id: Optional[int] = None
    product_name: Optional[str] = None
    product_spec: Optional[str] = None
    planned_qty: Optional[int] = None
    completed_qty: Optional[int] = None
    priority: Optional[int] = None
    lab_required: Optional[bool] = None
    scheme_json: Optional[Any] = None
    target_json: Optional[Any] = None
    key_params: Optional[Any] = None
    inspection_plan: Optional[Any] = None
    terminated_reason: Optional[str] = None


# ── 试产路线 ────────────────────────────────────────────────

class TrialRouteResponse(BaseModel):
    id: int
    tenant_id: str
    trial_order_id: int
    route_json: Any
    source_type: str = "manual"
    source_route_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    change_notes: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SaveTrialRouteRequest(BaseModel):
    route_json: Any
    source_type: str = "manual"
    source_route_id: Optional[int] = None
    name: Optional[str] = None
    description: Optional[str] = None
    change_notes: Optional[str] = None


# ── 试产BOM ─────────────────────────────────────────────────

class TrialBomResponse(BaseModel):
    id: int
    tenant_id: str
    trial_order_id: int
    bom_json: Any
    source_type: str = "manual"
    source_bom_id: Optional[int] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SaveTrialBomRequest(BaseModel):
    bom_json: Any
    source_type: str = "manual"
    source_bom_id: Optional[int] = None


# ── 试产评审 ────────────────────────────────────────────────

class TrialReviewResponse(BaseModel):
    id: int
    tenant_id: str
    trial_order_id: int
    review_stage: Optional[str] = None
    conclusion: str = "pending"
    summary_attachments: Optional[Any] = None
    review_items: Optional[Any] = None
    summary_data: Optional[Any] = None
    reviewer: Optional[int] = None
    reviewed_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class SubmitReviewRequest(BaseModel):
    review_stage: Optional[str] = None
    review_items: Optional[Any] = None
    summary_data: Optional[Any] = None
    summary_attachments: Optional[Any] = None


class MakeReviewDecisionRequest(BaseModel):
    conclusion: str  # approved/conditional_approve/terminated/adjust
    summary_attachments: Optional[Any] = None
    terminated_reason: Optional[str] = None


# ── 通用 ────────────────────────────────────────────────────

class ImportFromSourceRequest(BaseModel):
    source_id: int


class AdvanceStageRequest(BaseModel):
    target_stage: Optional[str] = None
