from pydantic import BaseModel, ConfigDict
from typing import Optional, List
from datetime import date, datetime


class WorkOrderResponse(BaseModel):
    id: int
    tenant_id: str
    wo_no: str
    wo_type: str = "production"
    wo_status: str = "draft"
    product_code: str
    product_name: str
    planned_qty: int = 0
    completed_qty: int = 0
    scrap_qty: int = 0
    priority: int = 0
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    actual_start_at: Optional[datetime] = None
    actual_end_at: Optional[datetime] = None
    workshop: Optional[str] = None
    line_code: Optional[str] = None
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class CreateWorkOrderRequest(BaseModel):
    wo_no: str
    product_code: str
    product_name: str
    planned_qty: int
    wo_type: str = "production"
    priority: int = 0
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    workshop: Optional[str] = None
    line_code: Optional[str] = None
    remark: Optional[str] = None


class UpdateWorkOrderRequest(BaseModel):
    wo_status: Optional[str] = None
    planned_qty: Optional[int] = None
    priority: Optional[int] = None
    scheduled_start_at: Optional[datetime] = None
    scheduled_end_at: Optional[datetime] = None
    remark: Optional[str] = None


class WorkReportResponse(BaseModel):
    id: int
    tenant_id: str
    work_order_id: int
    report_date: date
    reporter_id: int
    operation_code: Optional[str] = None
    operation_name: Optional[str] = None
    output_qty: int = 0
    input_qty: int = 0
    scrap_qty: int = 0
    defect_reason: Optional[str] = None
    labor_hours: float = 0
    machine_hours: float = 0
    status: str = "draft"
    created_at: Optional[datetime] = None
    
    model_config = ConfigDict(from_attributes=True)


class CreateWorkReportRequest(BaseModel):
    work_order_id: int
    report_date: date
    operation_code: Optional[str] = None
    operation_name: Optional[str] = None
    input_qty: int = 0
    output_qty: int = 0
    scrap_qty: int = 0
    defect_reason: Optional[str] = None
    labor_hours: float = 0
    machine_hours: float = 0


class DailyReportRow(BaseModel):
    report_date: date
    wo_no: str
    product_name: str
    output_qty: int
    scrap_qty: int
    labor_hours: float
    machine_hours: float = 0
    operator_name: str = ""


class DailyReportResponse(BaseModel):
    date: date
    total_output: int
    total_scrap: float
    total_hours: float
    total_machine_hours: float = 0
    rows: List[DailyReportRow] = []


# ==================== M02 BOM 相关 Schema ====================

class ProductBomCreate(BaseModel):
    product_id: int
    material_code: str
    material_name: str
    qty_per_unit: float
    unit: str
    material_type: str = "raw"
    scrap_rate: float = 0
    issue_operation_seq: Optional[str] = None
    is_key_material: bool = False
    version: int = 1
    effective_from: Optional[date] = None
    is_active: bool = True
    remark: Optional[str] = None


class ProductBomUpdate(BaseModel):
    material_code: Optional[str] = None
    material_name: Optional[str] = None
    qty_per_unit: Optional[float] = None
    unit: Optional[str] = None
    material_type: Optional[str] = None
    scrap_rate: Optional[float] = None
    issue_operation_seq: Optional[str] = None
    is_key_material: Optional[bool] = None
    version: Optional[int] = None
    effective_from: Optional[date] = None
    is_active: Optional[bool] = None
    remark: Optional[str] = None


class ProductBomResponse(BaseModel):
    id: int
    tenant_id: str
    product_id: int
    material_code: str
    material_name: str
    qty_per_unit: float
    unit: str
    material_type: str = "raw"
    scrap_rate: float = 0
    issue_operation_seq: Optional[str] = None
    is_key_material: bool = False
    version: int = 1
    effective_from: Optional[date] = None
    is_active: bool = True
    remark: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


class BomSnapshotResponse(BaseModel):
    id: int
    tenant_id: str
    work_order_id: int
    bom_version: int = 1
    snapshot_data: Optional[str] = None
    created_at: Optional[datetime] = None

    model_config = ConfigDict(from_attributes=True)


# ==================== M07 齐套性检查 Schema ====================

class MaterialCheckItem(BaseModel):
    material_code: str
    material_name: str
    required_qty: float
    available_qty: float
    short_qty: float
    unit: str
    is_ok: bool


class MaterialCheckResult(BaseModel):
    work_order_id: int
    check_status: str = "pending"
    total_materials: int = 0
    ok_materials: int = 0
    short_materials: int = 0
    kitting_rate: float = 0
    details: List[MaterialCheckItem] = []
    force_release: bool = False
    force_reason: Optional[str] = None


class ReleaseWorkOrderRequest(BaseModel):
    force_release: bool = False
    force_reason: Optional[str] = None
