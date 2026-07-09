from pydantic import BaseModel, ConfigDict
from typing import Optional
from datetime import datetime


# ============================================================
# 质控点配置
# ============================================================
class QcPointConfigResponse(BaseModel):
    id: int
    point_type: str
    point_name: str
    is_enabled: bool = True
    sampling_plan: Optional[str] = None
    patrol_frequency: Optional[int] = None
    material_id: Optional[int] = None
    process_id: Optional[int] = None
    priority: int = 0
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateQcPointConfigRequest(BaseModel):
    point_type: str
    point_name: str
    is_enabled: bool = True
    sampling_plan: Optional[str] = None
    patrol_frequency: Optional[int] = None
    material_id: Optional[int] = None
    process_id: Optional[int] = None
    priority: int = 0
    remark: Optional[str] = None


class UpdateQcPointConfigRequest(BaseModel):
    point_type: Optional[str] = None
    point_name: Optional[str] = None
    is_enabled: Optional[bool] = None
    sampling_plan: Optional[str] = None
    patrol_frequency: Optional[int] = None
    material_id: Optional[int] = None
    process_id: Optional[int] = None
    priority: Optional[int] = None
    remark: Optional[str] = None


# ============================================================
# 检验标准
# ============================================================
class InspectionStandardResponse(BaseModel):
    id: int
    name: str
    standard_type: str = "enterprise"
    version: Optional[str] = "1.0"
    is_enabled: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionStandardRequest(BaseModel):
    name: str
    standard_type: str = "enterprise"
    version: Optional[str] = "1.0"
    is_enabled: bool = True
    remark: Optional[str] = None


class UpdateInspectionStandardRequest(BaseModel):
    name: Optional[str] = None
    standard_type: Optional[str] = None
    version: Optional[str] = None
    is_enabled: Optional[bool] = None
    remark: Optional[str] = None


# ============================================================
# 检验项目
# ============================================================
class InspectionItemResponse(BaseModel):
    id: int
    standard_id: int
    item_name: str
    spec_upper_limit: Optional[str] = None
    spec_lower_limit: Optional[str] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    sort_order: int = 0
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionItemRequest(BaseModel):
    standard_id: int
    item_name: str
    spec_upper_limit: Optional[str] = None
    spec_lower_limit: Optional[str] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    sort_order: int = 0


class UpdateInspectionItemRequest(BaseModel):
    item_name: Optional[str] = None
    spec_upper_limit: Optional[str] = None
    spec_lower_limit: Optional[str] = None
    unit: Optional[str] = None
    method: Optional[str] = None
    sort_order: Optional[int] = None


# ============================================================
# 检验单
# ============================================================
class InspectionOrderResponse(BaseModel):
    id: int
    order_no: str
    order_type: str
    work_order_id: Optional[int] = None
    process_id: Optional[int] = None
    material_id: Optional[int] = None
    qc_point_id: Optional[int] = None
    inspector_id: Optional[int] = None
    result: Optional[str] = None
    judge_at: Optional[datetime] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionOrderRequest(BaseModel):
    order_type: str
    work_order_id: Optional[int] = None
    process_id: Optional[int] = None
    material_id: Optional[int] = None
    qc_point_id: Optional[int] = None
    inspector_id: Optional[int] = None
    remark: Optional[str] = None


class UpdateInspectionOrderRequest(BaseModel):
    order_type: Optional[str] = None
    work_order_id: Optional[int] = None
    process_id: Optional[int] = None
    material_id: Optional[int] = None
    qc_point_id: Optional[int] = None
    inspector_id: Optional[int] = None
    remark: Optional[str] = None


class JudgeOrderRequest(BaseModel):
    result: str  # ACC/REJ/UAI
    remark: Optional[str] = None


# ============================================================
# 检验结果明细
# ============================================================
class InspectionResultResponse(BaseModel):
    id: int
    order_id: int
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    spec_value: Optional[str] = None
    measured_value: Optional[str] = None
    deviation: Optional[str] = None
    unit: Optional[str] = None
    result: str
    remark: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class CreateInspectionResultRequest(BaseModel):
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    spec_value: Optional[str] = None
    measured_value: Optional[str] = None
    deviation: Optional[str] = None
    unit: Optional[str] = None
    result: str  # PASS/FAIL
    remark: Optional[str] = None


class UpdateInspectionResultRequest(BaseModel):
    item_id: Optional[int] = None
    item_name: Optional[str] = None
    spec_value: Optional[str] = None
    measured_value: Optional[str] = None
    deviation: Optional[str] = None
    unit: Optional[str] = None
    result: Optional[str] = None
    remark: Optional[str] = None


# ============================================================
# 品质报表
# ============================================================
class QualityReportResponse(BaseModel):
    id: int
    report_type: str
    period: str
    report_data: Optional[str] = None
    generated_at: Optional[datetime] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class GenerateReportRequest(BaseModel):
    report_type: str
    period: str
