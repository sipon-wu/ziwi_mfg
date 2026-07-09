# M15 实验室管理 — Pydantic Schemas
from pydantic import BaseModel, ConfigDict
from typing import Optional, Any, List
from datetime import datetime


# ── 实验委托 ────────────────────────────────────────────────

class LabRequestResponse(BaseModel):
    id: int
    tenant_id: str
    request_no: str
    title: str
    request_type: str
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    priority: str = "medium"
    sample_info: Optional[Any] = None
    description: Optional[str] = None
    status: str = "pending"
    assignee_id: Optional[int] = None
    expected_date: Optional[datetime] = None
    conclusion: Optional[str] = None
    attachments: Optional[Any] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    test_results: List["LabTestResultResponse"] = []

    model_config = ConfigDict(from_attributes=True)


class CreateLabRequest(BaseModel):
    title: str
    request_type: str
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    priority: str = "medium"
    sample_info: Optional[Any] = None
    description: Optional[str] = None
    expected_date: Optional[datetime] = None
    attachments: Optional[Any] = None


class UpdateLabRequest(BaseModel):
    title: Optional[str] = None
    request_type: Optional[str] = None
    source_type: Optional[str] = None
    source_id: Optional[int] = None
    priority: Optional[str] = None
    sample_info: Optional[Any] = None
    description: Optional[str] = None
    expected_date: Optional[datetime] = None
    conclusion: Optional[str] = None
    attachments: Optional[Any] = None


# ── 检测结果 ────────────────────────────────────────────────

class LabTestResultResponse(BaseModel):
    id: int
    tenant_id: str
    request_id: int
    item_name: str
    spec_value: Optional[str] = None
    actual_value: Optional[str] = None
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None
    is_pass: Optional[bool] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateTestResult(BaseModel):
    item_name: str
    spec_value: Optional[str] = None
    actual_value: Optional[str] = None
    unit: Optional[str] = None
    lower_limit: Optional[float] = None
    upper_limit: Optional[float] = None
    is_pass: Optional[bool] = None
    remark: Optional[str] = None


class SubmitResultsRequest(BaseModel):
    results: List[CreateTestResult]


class AssignRequest(BaseModel):
    assignee_id: int


# ── 检验标准库 ──────────────────────────────────────────────

class TestStandardResponse(BaseModel):
    id: int
    tenant_id: str
    name: str
    category: Optional[str] = None
    method: Optional[str] = None
    default_lower_limit: Optional[float] = None
    default_upper_limit: Optional[float] = None
    unit: Optional[str] = None
    description: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateTestStandard(BaseModel):
    name: str
    category: Optional[str] = None
    method: Optional[str] = None
    default_lower_limit: Optional[float] = None
    default_upper_limit: Optional[float] = None
    unit: Optional[str] = None
    description: Optional[str] = None


class UpdateTestStandard(BaseModel):
    name: Optional[str] = None
    category: Optional[str] = None
    method: Optional[str] = None
    default_lower_limit: Optional[float] = None
    default_upper_limit: Optional[float] = None
    unit: Optional[str] = None
    description: Optional[str] = None


# ── 实验报告 ────────────────────────────────────────────────

class LabReportResponse(BaseModel):
    id: int
    tenant_id: str
    request_id: int
    report_no: str
    conclusion: Optional[str] = None
    summary: Optional[str] = None
    attachments: Optional[Any] = None
    published_by: Optional[int] = None
    published_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ── 校准记录 ────────────────────────────────────────────────

class LabCalibrationResponse(BaseModel):
    id: int
    tenant_id: str
    equipment_name: str
    calibrate_type: Optional[str] = None
    calibrate_date: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    result: Optional[str] = None
    certificate: Optional[str] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateLabCalibration(BaseModel):
    equipment_name: str
    calibrate_type: Optional[str] = None
    calibrate_date: Optional[datetime] = None
    valid_until: Optional[datetime] = None
    result: Optional[str] = None
    certificate: Optional[str] = None
    remark: Optional[str] = None
