"""M20 仓储管理（WMS）模块 — Pydantic v2 Schemas"""
from datetime import date, datetime
from typing import Optional, List
from pydantic import BaseModel, Field, ConfigDict, field_validator

from app.core.enums import (
    WAREHOUSE_TYPE_LABELS,
    WAREHOUSE_TYPES,
    normalize_warehouse_type,
)


def _check_warehouse_type(v: Optional[str]) -> Optional[str]:
    """归一别名并校验值域。非法值直接 422，并列出合法取值。

    为什么不在 schema 里直接写 `WarehouseType`（Literal）：
    Literal 会把历史别名 `raw`/`wip`/`finished_goods` 一并拒掉，而这些值
    昨天还在被写入（前端硬编码字典就用的 4 项世界）。先归一再校验，
    既不让脏值继续落库，也不突然打断存量调用方。
    """
    if v is None:
        return None
    norm = normalize_warehouse_type(v)
    if norm not in WAREHOUSE_TYPE_LABELS:
        raise ValueError(
            f"仓库类型「{v}」不合法；可选："
            + " / ".join(f"{k}（{lab}）" for k, lab in WAREHOUSE_TYPE_LABELS.items())
        )
    return norm


# ============================================
# 仓库主数据
# ============================================

class WarehouseCreate(BaseModel):
    code: str = Field(..., max_length=64, description="仓库编码")
    name: str = Field(..., max_length=128, description="仓库名称")
    type: str = "raw_material"
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: bool = True

    _norm_type = field_validator("type", mode="after")(_check_warehouse_type)

class WarehouseUpdate(BaseModel):
    name: Optional[str] = None
    type: Optional[str] = None
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: Optional[bool] = None

    _norm_type = field_validator("type", mode="after")(_check_warehouse_type)

class ZoneCreate(BaseModel):
    warehouse_id: int
    zone_code: str = Field(..., max_length=64)
    zone_name: Optional[str] = None
    zone_type: str = "storage"
    is_active: bool = True

class ZoneUpdate(BaseModel):
    zone_name: Optional[str] = None
    zone_type: Optional[str] = None
    is_active: Optional[bool] = None

class LocationCreate(BaseModel):
    warehouse_id: int
    zone_id: Optional[int] = None
    location_code: str = Field(..., max_length=64)
    location_type: str = "shelf"
    max_capacity: Optional[float] = None
    is_active: bool = True

class LocationUpdate(BaseModel):
    zone_id: Optional[int] = None
    location_type: Optional[str] = None
    max_capacity: Optional[float] = None
    is_active: Optional[bool] = None


# ============================================
# 物料主数据
# ============================================

class MaterialCreate(BaseModel):
    code: str = Field(..., max_length=64)
    name: str = Field(..., max_length=128)
    spec: Optional[str] = None
    unit: str = Field(..., max_length=32)
    material_type: str = "raw"
    material_category: Optional[str] = None
    is_batch_managed: bool = False
    is_serial_managed: bool = False
    storage_condition: Optional[str] = None
    min_stock_qty: float = 0
    max_stock_qty: float = 0
    safety_stock_qty: float = 0
    reorder_point: float = 0
    lead_time_days: int = 0
    image_url: Optional[str] = None
    is_active: bool = True
    pick_strategy: str = "fifo"

class MaterialUpdate(BaseModel):
    name: Optional[str] = None
    spec: Optional[str] = None
    unit: Optional[str] = None
    material_type: Optional[str] = None
    material_category: Optional[str] = None
    pick_strategy: Optional[str] = None
    is_batch_managed: Optional[bool] = None
    is_serial_managed: Optional[bool] = None
    storage_condition: Optional[str] = None
    min_stock_qty: Optional[float] = None
    max_stock_qty: Optional[float] = None
    safety_stock_qty: Optional[float] = None
    reorder_point: Optional[float] = None
    lead_time_days: Optional[int] = None
    image_url: Optional[str] = None
    is_active: Optional[bool] = None


# ============================================
# 批次主数据
# ============================================

class BatchCreate(BaseModel):
    batch_no: str = Field(..., max_length=64)
    material_id: int
    supplier_batch_no: Optional[str] = None
    manufacture_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: str = "active"
    is_locked: bool = False
    lock_reason: Optional[str] = None
    # 三级码（B-20）：不填按来料码处理 —— 收货入账建的都是原料批次
    batch_type: str = Field("raw", description="raw 原料码 / wip 部件码 / final 成品码")
    parent_batch_id: Optional[int] = Field(None, description="组套父批次ID（一般由扫码组套写入，不手填）")

    @field_validator("batch_type")
    @classmethod
    def _valid_batch_type(cls, v: str) -> str:
        allowed = {"raw", "wip", "final"}
        if v not in allowed:
            raise ValueError(f"batch_type 只能是 {sorted(allowed)}，收到 {v!r}")
        return v


class BatchComposeRequest(BaseModel):
    """扫码组套：定子码 + 转子码 → 合成一个成品码。

    ★ 没有「缺码也提交」这种请求 —— 现场是扫到才生效，两个码都在才会发起。
      这里三个字段都必填，缺一个连请求都构造不出来（前端按钮也是两码齐才可点）。
    """
    work_order_id: int = Field(..., description="合装所在工单（成品物料由它反查）")
    stator_no: str = Field(..., min_length=1, max_length=64, description="定子码（扫码）")
    rotor_no: str = Field(..., min_length=1, max_length=64, description="转子码（扫码）")

class BatchUpdate(BaseModel):
    supplier_batch_no: Optional[str] = None
    expiry_date: Optional[date] = None
    status: Optional[str] = None
    is_locked: Optional[bool] = None
    lock_reason: Optional[str] = None


# ============================================
# 库存台账
# ============================================

class InventoryCreate(BaseModel):
    material_id: int
    warehouse_id: int
    location_id: Optional[int] = None
    batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    quantity: float = 0
    locked_qty: float = 0
    unit: str = Field(..., max_length=32)

class InventoryUpdate(BaseModel):
    quantity: Optional[float] = None
    locked_qty: Optional[float] = None


# ============================================
# 库存交易
# ============================================

class InventoryTransactionCreate(BaseModel):
    transaction_type: str
    voucher_no: str = Field(..., max_length=64)
    material_id: int
    warehouse_id: int
    from_location_id: Optional[int] = None
    to_location_id: Optional[int] = None
    batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    quantity: float
    unit: str
    unit_price: Optional[float] = None
    source_type: Optional[str] = None
    source_doc_no: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    remark: Optional[str] = None


# ============================================
# 入库单
# ============================================

class ReceiptOrderCreate(BaseModel):
    receipt_no: str
    receipt_type: str
    source_type: Optional[str] = None
    source_doc_no: Optional[str] = None
    warehouse_id: int
    supplier_id: Optional[int] = None
    items: List["ReceiptOrderItemCreate"] = []

class ReceiptOrderUpdate(BaseModel):
    status: Optional[str] = None
    checked_by: Optional[int] = None
    stored_by: Optional[int] = None

class ReceiptOrderItemCreate(BaseModel):
    line_no: int
    material_id: int
    expected_qty: float = 0
    received_qty: float = 0
    unit: str
    batch_no: Optional[str] = None
    location_id: Optional[int] = None
    remark: Optional[str] = None

class ReceiptOrderItemUpdate(BaseModel):
    received_qty: Optional[float] = None
    stored_qty: Optional[float] = None
    batch_no: Optional[str] = None
    location_id: Optional[int] = None
    inspection_status: Optional[str] = None


# ============================================
# 出库单
# ============================================

class IssueOrderCreate(BaseModel):
    issue_no: str
    issue_type: str
    source_type: Optional[str] = None
    source_doc_no: Optional[str] = None
    # 领料来源工单：不传时服务层会用 source_doc_no 反查工单号自动补齐，
    # 保证批次追溯有一条可靠的 JOIN 边而不是字符串弱关联。
    work_order_id: Optional[int] = None
    warehouse_id: int
    department_id: Optional[int] = None
    recipient: Optional[str] = None
    items: List["IssueOrderItemCreate"] = []

class IssueOrderUpdate(BaseModel):
    status: Optional[str] = None
    issued_by: Optional[int] = None

class IssueOrderItemCreate(BaseModel):
    line_no: int
    material_id: int
    required_qty: float = 0
    issued_qty: float = 0
    unit: str
    batch_no: Optional[str] = None
    from_location_id: Optional[int] = None
    remark: Optional[str] = None

class IssueOrderItemUpdate(BaseModel):
    issued_qty: Optional[float] = None
    batch_no: Optional[str] = None
    from_location_id: Optional[int] = None
    pick_status: Optional[str] = None
    request_id: Optional[str] = Field(
        default=None, max_length=64,
        description=(
            "幂等键。同一次逻辑发料重试时必须沿用同一个值，服务端按 "
            "(tenant_id, request_id) 去重 15 分钟，重复请求不再扣库存而是"
            "原样返回上次结果。不传则退化为无幂等的原行为（兼容老客户端）。"
        ),
    )


class IssueOrderCompleteRequest(BaseModel):
    """结案出库单（``partially_issued`` 的唯一出口）。

    ``allow_shortage`` 是**显式的责任选择**，不是默认放行：
    - ``False``（默认）→ 有欠发就 400，message 带行号与欠发数；
    - ``True`` → 结案，并在单据上打 ``short_closed=true`` + 记 ``shortage_reason``，
      同时写一条 ``wms.short_close`` 审计 —— "就发这么多"必须留痕，
      否则事后分不清"发齐了"和"欠发结了案"。
    """

    allow_shortage: bool = False
    reason: Optional[str] = Field(
        default=None, description="差额结案原因（缺料/客户改单/…），落 issue_orders.shortage_reason")
    remark: Optional[str] = None


# ============================================
# 盘点单
# ============================================

class InventoryCountCreate(BaseModel):
    count_no: str
    count_type: str
    warehouse_id: int
    zone_id: Optional[int] = None
    count_date: date
    items: List["InventoryCountItemCreate"] = []

class InventoryCountUpdate(BaseModel):
    status: Optional[str] = None
    counted_by: Optional[int] = None
    adjusted_by: Optional[int] = None

class InventoryCountItemCreate(BaseModel):
    material_id: int
    location_id: Optional[int] = None
    batch_no: Optional[str] = None
    system_qty: float = 0
    count_qty: Optional[float] = None
    diff_qty: Optional[float] = None
    diff_reason: Optional[str] = None
    remark: Optional[str] = None

class InventoryCountItemUpdate(BaseModel):
    count_qty: Optional[float] = None
    diff_qty: Optional[float] = None
    diff_reason: Optional[str] = None
    status: Optional[str] = None
    remark: Optional[str] = None


class InventoryCountAdjustRequest(BaseModel):
    """盘点调整（E-E5）。存在超阈值差异行时必须 force + 说明。"""
    force: bool = False
    force_reason: Optional[str] = None


# ============================================
# 库存预警
# ============================================

class InventoryAlertCreate(BaseModel):
    alert_type: str
    material_id: int
    warehouse_id: Optional[int] = None
    current_qty: float = 0
    threshold_qty: float = 0
    alert_message: Optional[str] = None

class InventoryAlertUpdate(BaseModel):
    status: Optional[str] = None
    resolved_by: Optional[int] = None


# ============================================
# 领料申请
# ============================================

class MaterialRequestCreate(BaseModel):
    request_no: str
    work_order_id: int
    warehouse_id: int
    department_id: Optional[int] = None
    requester: Optional[int] = None
    items: List["MaterialRequestItemCreate"] = []

class MaterialRequestUpdate(BaseModel):
    status: Optional[str] = None
    approved_by: Optional[int] = None

class MaterialRequestItemCreate(BaseModel):
    line_no: int
    material_id: int
    required_qty: float
    approved_qty: Optional[float] = None
    unit: str
    operation_seq: Optional[int] = None
    requirement_date: Optional[date] = None
    remark: Optional[str] = None

class MaterialRequestItemUpdate(BaseModel):
    approved_qty: Optional[float] = None
    issued_qty: Optional[float] = None
    remark: Optional[str] = None


# ============================================
# 库存移动
# ============================================

class StockMoveRequest(BaseModel):
    source_location_id: int
    target_location_id: int
    material_id: int
    batch_no: Optional[str] = None
    quantity: float
    unit: str
    remark: Optional[str] = None
    # 可选校验项：目标仓库**由目标库位解析**（库位归属是权威事实），
    # 显式传只用于让调用方多一道自检——传错会被拒，不会静默按错的走。
    target_warehouse_id: Optional[int] = None


# ============================================
# Response Schemas（ORM 模式）
# ============================================

class WarehouseResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    type: str
    address: Optional[str] = None
    contact_person: Optional[str] = None
    contact_phone: Optional[str] = None
    is_active: bool = True
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ZoneResponse(BaseModel):
    id: int
    tenant_id: str
    warehouse_id: int
    zone_code: str
    zone_name: Optional[str] = None
    zone_type: str = "storage"
    is_active: bool = True
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class LocationResponse(BaseModel):
    id: int
    tenant_id: str
    warehouse_id: int
    zone_id: Optional[int] = None
    location_code: str
    location_type: str = "shelf"
    max_capacity: Optional[float] = None
    current_qty: float = 0
    is_active: bool = True
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class MaterialResponse(BaseModel):
    id: int
    tenant_id: str
    code: str
    name: str
    spec: Optional[str] = None
    unit: str
    material_type: str = "raw"
    material_category: Optional[str] = None
    is_batch_managed: bool = False
    is_serial_managed: bool = False
    storage_condition: Optional[str] = None
    min_stock_qty: float = 0
    max_stock_qty: float = 0
    safety_stock_qty: float = 0
    reorder_point: float = 0
    lead_time_days: int = 0
    image_url: Optional[str] = None
    is_active: bool = True
    pick_strategy: str = "fifo"
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class BatchResponse(BaseModel):
    id: int
    tenant_id: str
    batch_no: str
    material_id: int
    supplier_batch_no: Optional[str] = None
    manufacture_date: Optional[date] = None
    expiry_date: Optional[date] = None
    status: str = "active"
    is_locked: bool = False
    lock_reason: Optional[str] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class InventoryResponse(BaseModel):
    id: int
    tenant_id: str
    material_id: int
    warehouse_id: int
    location_id: Optional[int] = None
    batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    quantity: float = 0
    locked_qty: float = 0
    unit: str
    last_transaction_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class InventoryTransactionResponse(BaseModel):
    id: int
    tenant_id: str
    transaction_type: str
    voucher_no: str
    material_id: int
    warehouse_id: int
    from_location_id: Optional[int] = None
    to_location_id: Optional[int] = None
    batch_id: Optional[int] = None
    batch_no: Optional[str] = None
    quantity: float
    unit: str
    unit_price: Optional[float] = None
    source_type: Optional[str] = None
    source_doc_no: Optional[str] = None
    reference_type: Optional[str] = None
    reference_id: Optional[int] = None
    remark: Optional[str] = None
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ReceiptOrderResponse(BaseModel):
    id: int
    tenant_id: str
    receipt_no: str
    receipt_type: str
    status: str = "pending"
    source_type: Optional[str] = None
    source_doc_no: Optional[str] = None
    warehouse_id: int
    supplier_id: Optional[int] = None
    total_qty: float = 0
    received_qty: float = 0
    stored_qty: float = 0
    created_by: Optional[int] = None
    checked_by: Optional[int] = None
    stored_by: Optional[int] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class ReceiptOrderItemResponse(BaseModel):
    id: int
    receipt_id: int
    line_no: int
    material_id: int
    expected_qty: float = 0
    received_qty: float = 0
    stored_qty: float = 0
    unit: str
    batch_no: Optional[str] = None
    location_id: Optional[int] = None
    inspection_status: str = "pending"
    inspection_id: Optional[int] = None
    remark: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class IssueOrderResponse(BaseModel):
    id: int
    tenant_id: str
    issue_no: str
    issue_type: str
    status: str = "pending"
    source_type: Optional[str] = None
    source_doc_no: Optional[str] = None
    work_order_id: Optional[int] = None
    warehouse_id: int
    department_id: Optional[int] = None
    recipient: Optional[str] = None
    total_qty: float = 0
    issued_qty: float = 0
    created_by: Optional[int] = None
    issued_by: Optional[int] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class IssueOrderItemResponse(BaseModel):
    id: int
    issue_id: int
    line_no: int
    material_id: int
    required_qty: float = 0
    issued_qty: float = 0
    unit: str
    batch_no: Optional[str] = None
    from_location_id: Optional[int] = None
    pick_status: str = "pending"
    remark: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class InventoryCountResponse(BaseModel):
    id: int
    tenant_id: str
    count_no: str
    count_type: str
    status: str = "draft"
    warehouse_id: int
    zone_id: Optional[int] = None
    count_date: date
    total_items: int = 0
    counted_items: int = 0
    diff_items: int = 0
    created_by: Optional[int] = None
    counted_by: Optional[int] = None
    adjusted_by: Optional[int] = None
    created_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None
    adjusted_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class InventoryCountItemResponse(BaseModel):
    id: int
    count_id: int
    material_id: int
    location_id: Optional[int] = None
    batch_no: Optional[str] = None
    system_qty: float = 0
    count_qty: Optional[float] = None
    diff_qty: Optional[float] = None
    diff_reason: Optional[str] = None
    status: str = "pending"
    remark: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class InventoryAlertResponse(BaseModel):
    id: int
    tenant_id: str
    alert_type: str
    material_id: int
    warehouse_id: Optional[int] = None
    current_qty: float = 0
    threshold_qty: float = 0
    status: str = "open"
    alert_message: Optional[str] = None
    resolved_by: Optional[int] = None
    resolved_at: Optional[datetime] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class MaterialRequestResponse(BaseModel):
    id: int
    tenant_id: str
    request_no: str
    work_order_id: int
    status: str = "pending"
    warehouse_id: int
    department_id: Optional[int] = None
    requester: Optional[int] = None
    approved_by: Optional[int] = None
    created_at: Optional[datetime] = None
    approved_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class MaterialRequestItemResponse(BaseModel):
    id: int
    request_id: int
    line_no: int
    material_id: int
    required_qty: float
    approved_qty: Optional[float] = None
    issued_qty: float = 0
    unit: str
    operation_seq: Optional[int] = None
    requirement_date: Optional[date] = None
    remark: Optional[str] = None
    model_config = ConfigDict(from_attributes=True)

class StockMoveResponse(BaseModel):
    id: int = 0
    tenant_id: str = ""
    transaction_type: str = "transfer"
    voucher_no: str = ""
    material_id: int
    warehouse_id: int
    from_location_id: int
    to_location_id: int
    batch_no: Optional[str] = None
    quantity: float
    unit: str
    source_type: str = "transfer"
    reference_type: str = "stock_move"
    created_by: Optional[int] = None
    created_at: Optional[datetime] = None
    model_config = ConfigDict(from_attributes=True)

class LocationBatchGenerateRequest(BaseModel):
    warehouse_id: int
    zone_id: int
    prefix: str = ""
    start: int = 1
    end: int = 10
    step: int = 1
    location_type: str = "shelf"
    max_capacity: Optional[float] = None
