from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import datetime, date


# ── FMEA 文档 ───────────────────────────────────────────────

class FmeaDocumentResponse(BaseModel):
    id: int
    doc_no: str
    fmea_type: str
    title: str
    product_id: Optional[int] = None
    process_id: Optional[int] = None
    project_id: Optional[int] = None
    version: str = "V1.0"
    status: str = "draft"
    is_latest: bool = True
    source_doc_id: Optional[int] = None
    rpn_threshold: int = 100
    remark: Optional[str] = None
    created_by: int
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateFmeaDocumentRequest(BaseModel):
    fmea_type: str
    title: str
    product_id: Optional[int] = None
    process_id: Optional[int] = None
    project_id: Optional[int] = None
    source_doc_id: Optional[int] = None
    rpn_threshold: int = 100
    remark: Optional[str] = None


class UpdateFmeaDocumentRequest(BaseModel):
    title: Optional[str] = None
    product_id: Optional[int] = None
    process_id: Optional[int] = None
    project_id: Optional[int] = None
    rpn_threshold: Optional[int] = None
    remark: Optional[str] = None


# ── 结构树 ──────────────────────────────────────────────────

class FmeaHierarchyNode(BaseModel):
    id: Optional[int] = None
    parent_id: Optional[int] = None
    level_type: Optional[str] = None
    sort_order: int = 0
    label: str


class FmeaHierarchyResponse(BaseModel):
    id: int
    doc_id: int
    parent_id: Optional[int] = None
    level_type: Optional[str] = None
    sort_order: int = 0
    label: str
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BatchSaveTreeRequest(BaseModel):
    nodes: List[FmeaHierarchyNode]


# ── FMEA 项 ─────────────────────────────────────────────────

class FmeaItemResponse(BaseModel):
    id: int
    doc_id: int
    hierarchy_id: int
    function_desc: str
    failure_mode: str
    failure_effect: str
    failure_cause: str
    current_control_prevent: Optional[str] = None
    current_control_detect: Optional[str] = None
    severity: int
    occurrence: int
    detection: int
    rpn: int
    is_high_risk: bool = False
    is_critical_process: bool = False
    recommended_action: Optional[str] = None
    status: str = "open"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateFmeaItemRequest(BaseModel):
    doc_id: int
    hierarchy_id: int
    function_desc: str
    failure_mode: str
    failure_effect: str
    failure_cause: str
    current_control_prevent: Optional[str] = None
    current_control_detect: Optional[str] = None
    severity: int = 1
    occurrence: int = 1
    detection: int = 1
    is_critical_process: bool = False
    recommended_action: Optional[str] = None


class UpdateFmeaItemRequest(BaseModel):
    function_desc: Optional[str] = None
    failure_mode: Optional[str] = None
    failure_effect: Optional[str] = None
    failure_cause: Optional[str] = None
    current_control_prevent: Optional[str] = None
    current_control_detect: Optional[str] = None
    severity: Optional[int] = None
    occurrence: Optional[int] = None
    detection: Optional[int] = None
    is_critical_process: Optional[bool] = None
    recommended_action: Optional[str] = None
    status: Optional[str] = None


# ── 整改措施 ────────────────────────────────────────────────

class FmeaActionResponse(BaseModel):
    id: int
    item_id: int
    action_desc: str
    responsible_id: int
    target_date: Optional[date] = None
    status: str = "open"
    completed_at: Optional[datetime] = None
    re_severity: Optional[int] = None
    re_occurrence: Optional[int] = None
    re_detection: Optional[int] = None
    re_rpn: Optional[int] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateActionRequest(BaseModel):
    action_desc: str
    responsible_id: int
    target_date: Optional[date] = None
    remark: Optional[str] = None


class CompleteActionRequest(BaseModel):
    re_severity: int
    re_occurrence: int
    re_detection: int


# ── 控制计划 ────────────────────────────────────────────────

class ControlPlanResponse(BaseModel):
    id: int
    fmea_doc_id: int
    fmea_item_id: int
    process_id: Optional[int] = None
    control_item: str
    control_method: str
    frequency: Optional[str] = None
    responsible: Optional[str] = None
    specification: Optional[str] = None
    source: str = "auto"
    status: str = "draft"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class UpdateControlPlanRequest(BaseModel):
    process_id: Optional[int] = None
    control_item: Optional[str] = None
    control_method: Optional[str] = None
    frequency: Optional[str] = None
    responsible: Optional[str] = None
    specification: Optional[str] = None
    status: Optional[str] = None


class GenerateControlPlanRequest(BaseModel):
    fmea_doc_id: int


class RpnResult(BaseModel):
    id: int
    rpn: int
    severity: int
    occurrence: int
    detection: int
    is_high_risk: bool
