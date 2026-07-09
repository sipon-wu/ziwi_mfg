"""M20 仓储管理（WMS）模块 — ORM 模型（15 张表）"""
from sqlalchemy import Column, BigInteger, String, Integer, Float, DateTime, Text, Date, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


# ============================================
# 仓库主数据
# ============================================

class Warehouse(Base):
    """仓库"""
    __tablename__ = "warehouses"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    code          = Column(String(64), nullable=False, comment="仓库编码")
    name          = Column(String(128), nullable=False, comment="仓库名称")
    type          = Column(String(32), default="raw_material", comment="raw_material/semi/finished/consumable")
    address       = Column(String(256), comment="地址")
    contact_person = Column(String(64), comment="联系人")
    contact_phone = Column(String(32), comment="联系电话")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WarehouseZone(Base):
    """库区"""
    __tablename__ = "warehouse_zones"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    zone_code     = Column(String(64), nullable=False, comment="库区编码")
    zone_name     = Column(String(128), comment="库区名称")
    zone_type     = Column(String(32), default="storage", comment="storage/待检/不良品/待发/退货")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class WarehouseLocation(Base):
    """库位"""
    __tablename__ = "warehouse_locations"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    zone_id       = Column(BigInteger, comment="库区ID")
    location_code = Column(String(64), nullable=False, comment="库位编码")
    location_type = Column(String(32), default="shelf", comment="shelf/floor/cold/area")
    max_capacity  = Column(Float, comment="最大容量")
    current_qty   = Column(Float, default=0, comment="当前占用容量")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 物料主数据
# ============================================

class Material(Base):
    """物料主数据"""
    __tablename__ = "materials"

    id                = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id         = Column(String(50), nullable=False, comment="租户ID")
    code              = Column(String(64), nullable=False, comment="物料编码")
    name              = Column(String(128), nullable=False, comment="物料名称")
    spec              = Column(String(256), comment="规格型号")
    unit              = Column(String(32), nullable=False, comment="计量单位")
    material_type     = Column(String(32), default="raw", comment="raw/semi/finished/consumable/package")
    material_category = Column(String(64), comment="物料分类")
    is_batch_managed  = Column(Boolean, default=False, comment="是否批次管理")
    is_serial_managed = Column(Boolean, default=False, comment="是否序列号管理")
    storage_condition = Column(String(128), comment="存储条件")
    min_stock_qty     = Column(Float, default=0, comment="最低库存量")
    max_stock_qty     = Column(Float, default=0, comment="最高库存量")
    safety_stock_qty  = Column(Float, default=0, comment="安全库存量")
    reorder_point     = Column(Float, default=0, comment="再订货点")
    lead_time_days    = Column(Integer, default=0, comment="采购提前期(天)")
    image_url         = Column(String(256), comment="图片URL")
    is_active         = Column(Boolean, default=True, comment="启用状态")
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ============================================
# 批次主数据
# ============================================

class Batch(Base):
    """批次"""
    __tablename__ = "batches"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False, comment="租户ID")
    batch_no         = Column(String(64), nullable=False, comment="批次号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    supplier_batch_no = Column(String(64), comment="供应商批次号")
    manufacture_date = Column(Date, comment="生产日期")
    expiry_date      = Column(Date, comment="有效期/到期日")
    status           = Column(String(32), default="active", comment="active/locked/expired/blocked")
    is_locked        = Column(Boolean, default=False, comment="是否锁定")
    lock_reason      = Column(String(256), comment="锁定原因")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 库存台账
# ============================================

class Inventory(Base):
    """库存台账"""
    __tablename__ = "inventory"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    material_id   = Column(BigInteger, nullable=False, comment="物料ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    location_id   = Column(BigInteger, comment="库位ID")
    batch_id      = Column(BigInteger, comment="批次ID")
    batch_no      = Column(String(64), comment="批号")
    quantity      = Column(Float, default=0, comment="现存量")
    locked_qty    = Column(Float, default=0, comment="锁定数量")
    unit          = Column(String(32), nullable=False, comment="单位")
    last_transaction_at = Column(DateTime(timezone=True), comment="最后交易时间")
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InventoryTransaction(Base):
    """库存交易流水"""
    __tablename__ = "inventory_transactions"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False, comment="租户ID")
    transaction_type = Column(String(32), nullable=False, comment="receipt/issue/transfer/adjust/scrap")
    voucher_no       = Column(String(64), nullable=False, comment="物料凭证号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    warehouse_id     = Column(BigInteger, nullable=False, comment="仓库ID")
    from_location_id = Column(BigInteger, comment="源库位ID")
    to_location_id   = Column(BigInteger, comment="目标库位ID")
    batch_id         = Column(BigInteger, comment="批次ID")
    batch_no         = Column(String(64), comment="批号")
    quantity         = Column(Float, nullable=False, comment="数量")
    unit             = Column(String(32), nullable=False, comment="单位")
    unit_price       = Column(Float, comment="单价")
    source_type      = Column(String(32), comment="purchase/production/sale/adjust/scrap/transfer")
    source_doc_no    = Column(String(64), comment="来源单据号")
    reference_type   = Column(String(32), comment="po/wo/so/adjust/stock_move")
    reference_id     = Column(BigInteger, comment="来源单据ID")
    remark           = Column(String(256), comment="备注")
    created_by       = Column(BigInteger, comment="创建人ID")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 入库单
# ============================================

class ReceiptOrder(Base):
    """入库单"""
    __tablename__ = "receipt_orders"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    receipt_no    = Column(String(64), nullable=False, comment="入库单号")
    receipt_type  = Column(String(32), nullable=False, comment="purchase/生产入库/退货入库/transfer")
    status        = Column(String(32), default="pending", comment="pending/inspecting/partially_stored/stored/cancelled")
    source_type   = Column(String(32), comment="po/wo/return/transfer")
    source_doc_no = Column(String(64), comment="来源单据号")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    supplier_id   = Column(BigInteger, comment="供应商ID")
    total_qty     = Column(Float, default=0, comment="总数量")
    received_qty  = Column(Float, default=0, comment="已收数量")
    stored_qty    = Column(Float, default=0, comment="已上架数量")
    created_by    = Column(BigInteger, comment="创建人ID")
    checked_by    = Column(BigInteger, comment="质检确认人")
    stored_by     = Column(BigInteger, comment="上架确认人")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), comment="完成时间")


class ReceiptOrderItem(Base):
    """入库单明细"""
    __tablename__ = "receipt_order_items"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    receipt_id       = Column(BigInteger, nullable=False, comment="入库单ID")
    line_no          = Column(Integer, nullable=False, comment="行号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    expected_qty     = Column(Float, default=0, comment="应收数量")
    received_qty     = Column(Float, default=0, comment="实收数量")
    stored_qty       = Column(Float, default=0, comment="已上架数量")
    unit             = Column(String(32), nullable=False, comment="单位")
    batch_no         = Column(String(64), comment="批号")
    location_id      = Column(BigInteger, comment="目标库位ID")
    inspection_status = Column(String(32), default="pending", comment="pending/待检/qualified/disqualified")
    inspection_id    = Column(BigInteger, comment="关联IQC检验单ID")
    remark           = Column(String(256), comment="备注")


# ============================================
# 出库单
# ============================================

class IssueOrder(Base):
    """出库单"""
    __tablename__ = "issue_orders"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    issue_no      = Column(String(64), nullable=False, comment="出库单号")
    issue_type    = Column(String(32), nullable=False, comment="production/销售出库/scrap/transfer")
    status        = Column(String(32), default="pending", comment="pending/picking/partially_issued/issued/cancelled")
    source_type   = Column(String(32), comment="wo/so/scrap/transfer")
    source_doc_no = Column(String(64), comment="来源单据号")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    department_id = Column(BigInteger, comment="领用部门ID")
    recipient     = Column(String(64), comment="领料人")
    total_qty     = Column(Float, default=0, comment="总数量")
    issued_qty    = Column(Float, default=0, comment="已发数量")
    created_by    = Column(BigInteger, comment="创建人ID")
    issued_by     = Column(BigInteger, comment="出库确认人")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), comment="完成时间")


class IssueOrderItem(Base):
    """出库单明细"""
    __tablename__ = "issue_order_items"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    issue_id        = Column(BigInteger, nullable=False, comment="出库单ID")
    line_no         = Column(Integer, nullable=False, comment="行号")
    material_id     = Column(BigInteger, nullable=False, comment="物料ID")
    required_qty    = Column(Float, default=0, comment="需求数量")
    issued_qty      = Column(Float, default=0, comment="实发数量")
    unit            = Column(String(32), nullable=False, comment="单位")
    batch_no        = Column(String(64), comment="批号")
    from_location_id = Column(BigInteger, comment="源库位ID")
    pick_status     = Column(String(32), default="pending", comment="pending/picked")
    remark          = Column(String(256), comment="备注")


# ============================================
# 盘点单
# ============================================

class InventoryCount(Base):
    """盘点单"""
    __tablename__ = "inventory_counts"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    count_no      = Column(String(64), nullable=False, comment="盘点单号")
    count_type    = Column(String(32), nullable=False, comment="full/cycle/spot")
    status        = Column(String(32), default="draft", comment="draft/in_progress/completed/adjusted/closed")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    zone_id       = Column(BigInteger, comment="库区ID")
    count_date    = Column(Date, nullable=False, comment="盘点日期")
    total_items   = Column(Integer, default=0, comment="总物料数")
    counted_items = Column(Integer, default=0, comment="已盘物料数")
    diff_items    = Column(Integer, default=0, comment="差异物料数")
    created_by    = Column(BigInteger, comment="创建人ID")
    counted_by    = Column(BigInteger, comment="盘点人ID")
    adjusted_by   = Column(BigInteger, comment="调整人ID")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), comment="完成时间")
    adjusted_at   = Column(DateTime(timezone=True), comment="调整时间")


class InventoryCountItem(Base):
    """盘点明细"""
    __tablename__ = "inventory_count_items"

    id          = Column(BigInteger, primary_key=True, autoincrement=True)
    count_id    = Column(BigInteger, nullable=False, comment="盘点单ID")
    material_id = Column(BigInteger, nullable=False, comment="物料ID")
    location_id = Column(BigInteger, comment="库位ID")
    batch_no    = Column(String(64), comment="批号")
    system_qty  = Column(Float, default=0, comment="系统账面数量")
    count_qty   = Column(Float, comment="实盘数量")
    diff_qty    = Column(Float, comment="差异数量")
    diff_reason = Column(String(128), comment="差异原因")
    status      = Column(String(32), default="pending", comment="pending/counted/confirmed")
    remark      = Column(String(256), comment="备注")


# ============================================
# 库存预警
# ============================================

class InventoryAlert(Base):
    """库存预警记录"""
    __tablename__ = "inventory_alerts"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    alert_type    = Column(String(32), nullable=False, comment="min_stock/max_stock/safety_stock/slow_moving/expiry")
    material_id   = Column(BigInteger, nullable=False, comment="物料ID")
    warehouse_id  = Column(BigInteger, comment="仓库ID")
    current_qty   = Column(Float, default=0, comment="当前库存")
    threshold_qty = Column(Float, default=0, comment="阈值")
    status        = Column(String(32), default="open", comment="open/acknowledged/resolved")
    alert_message = Column(String(256), comment="预警消息")
    resolved_by   = Column(BigInteger, comment="解决人ID")
    resolved_at   = Column(DateTime(timezone=True), comment="解决时间")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 领料申请单
# ============================================

class MaterialRequest(Base):
    """领料申请单"""
    __tablename__ = "material_requests"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    request_no    = Column(String(64), nullable=False, comment="领料申请单号")
    work_order_id = Column(BigInteger, nullable=False, comment="关联工单ID")
    status        = Column(String(32), default="pending", comment="pending/approved/partially_issued/issued/cancelled")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    department_id = Column(BigInteger, comment="部门ID")
    requester     = Column(BigInteger, comment="申请人ID")
    approved_by   = Column(BigInteger, comment="审批人ID")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    approved_at   = Column(DateTime(timezone=True), comment="审批时间")


class MaterialRequestItem(Base):
    """领料申请明细"""
    __tablename__ = "material_request_items"

    id               = Column(BigInteger, primary_key=True, autoincrement=True)
    request_id       = Column(BigInteger, nullable=False, comment="申请单ID")
    line_no          = Column(Integer, nullable=False, comment="行号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    required_qty     = Column(Float, default=0, comment="需求数量")
    approved_qty     = Column(Float, comment="核准数量")
    issued_qty       = Column(Float, default=0, comment="已发数量")
    unit             = Column(String(32), nullable=False, comment="单位")
    operation_seq    = Column(Integer, comment="投料工序")
    requirement_date = Column(Date, comment="需求日期")
    remark           = Column(String(256), comment="备注")
