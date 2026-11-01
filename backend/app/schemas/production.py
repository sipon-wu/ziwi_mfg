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
    assignee_id: Optional[int] = None
    assigned_org_id: Optional[int] = None
    # C-E7：工单挂的设备/工作中心（传了才校验启用状态，不传不逼人填）
    equipment_id: Optional[int] = None
    work_center_id: Optional[int] = None
    # B-S3/B-E6：工单冻结的工艺路线（传了校验存在性，不传给 warning）
    route_id: Optional[int] = None
    remark: Optional[str] = None


class AssignWorkOrderRequest(BaseModel):
    """派工（场景 C-S2）。个人与班组至少要给一个。"""
    assignee_id: Optional[int] = None
    assigned_org_id: Optional[int] = None
    remark: Optional[str] = None


class UpdateWorkOrderRequest(BaseModel):
    wo_status: Optional[str] = None
    planned_qty: Optional[int] = None
    priority: Optional[int] = None
    assignee_id: Optional[int] = None
    assigned_org_id: Optional[int] = None
    equipment_id: Optional[int] = None
    work_center_id: Optional[int] = None
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
    # 报工时刻（C-B2）。不传则落库 now()，且不参与"早于开工"的 400 校验 ——
    # 补录昨天的产量是正常业务，不能因为没传时刻就被拒。
    reported_at: Optional[datetime] = None


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


# ==================== 工单状态流转请求 ====================

class PauseWorkOrderRequest(BaseModel):
    """暂停工单。原因进状态流水，用于追溯停机损失。"""
    reason: Optional[str] = None


class CompleteWorkOrderRequest(BaseModel):
    """完工。无产出时需 force=true 并说明原因。"""
    force: bool = False
    force_reason: Optional[str] = None


class CancelWorkOrderRequest(BaseModel):
    """作废工单。原因必填 —— 作废会让工单一动不动地消失，必须留痕。"""
    reason: str
    # 已有产出时必须 force + 说明产出去向（C-E5），否则作废会让报工数据成孤儿
    force: bool = False
    force_reason: Optional[str] = None


# ── C-S6 工单拆分 ────────────────────────────────────────────
class SplitWorkOrderRequest(BaseModel):
    """拆分工单：按给定数量拆出若干子单，母单留下余量。

    只传数量不传其他字段 —— 子单的产品、工艺路线、设备、工作中心、
    班组、交期一律从母单继承：拆出来的单和母单做的是**同一件事**，
    让调用方再填一遍只会填错。
    """
    qtys: List[int]


# ── C-S7 工单合并 ────────────────────────────────────────────
class MergeWorkOrdersRequest(BaseModel):
    """合并工单：多张同产品同工艺的草稿单合成一张。"""
    order_ids: List[int]
    wo_no: Optional[str] = None
    """合并单号。不传则自动生成 ``{首单号}-M1``（冲突时递增）。"""


class WorkOrderActionItem(BaseModel):
    action: str
    label: str
