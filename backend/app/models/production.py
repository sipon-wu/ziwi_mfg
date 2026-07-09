from sqlalchemy import Column, BigInteger, String, Integer, Float, DateTime, Text, Date, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    wo_no = Column(String(100), nullable=False, comment="工单编号")
    wo_type = Column(String(50), default="production", comment="工单类型: production/maintenance/quality")
    wo_status = Column(String(50), default="draft", comment="状态: draft/released/in_progress/completed/closed/canceled")
    product_code = Column(String(100), nullable=False, comment="产品编码")
    product_name = Column(String(200), nullable=False, comment="产品名称")
    planned_qty = Column(Integer, default=0, comment="计划数量")
    completed_qty = Column(Integer, default=0, comment="已完成数量")
    scrap_qty = Column(Integer, default=0, comment="报废数量")
    priority = Column(Integer, default=0, comment="优先级 0-5")
    scheduled_start_at = Column(DateTime(timezone=True), comment="计划开始时间")
    scheduled_end_at = Column(DateTime(timezone=True), comment="计划结束时间")
    actual_start_at = Column(DateTime(timezone=True), comment="实际开始时间")
    actual_end_at = Column(DateTime(timezone=True), comment="实际结束时间")
    assignee_id = Column(BigInteger, comment="负责人ID")
    workshop = Column(String(100), comment="车间")
    line_code = Column(String(100), comment="产线编码")
    remark = Column(Text, comment="备注")
    # M07 齐套性检查字段
    material_check_status = Column(String(20), default="pending", comment="齐套状态: pending/passed/failed/force_passed")
    material_check_result = Column(Text, comment="缺料明细（JSON）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkOrderStatusLog(Base):
    __tablename__ = "work_order_status_logs"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    work_order_id = Column(BigInteger, nullable=False, comment="工单ID")
    from_status = Column(String(50), comment="原状态")
    to_status = Column(String(50), nullable=False, comment="目标状态")
    operator_id = Column(BigInteger, comment="操作人ID")
    remark = Column(Text, comment="备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkReport(Base):
    __tablename__ = "work_reports"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    work_order_id = Column(BigInteger, nullable=False, comment="关联工单ID")
    report_date = Column(Date, nullable=False, comment="报工日期")
    reporter_id = Column(BigInteger, nullable=False, comment="报工人ID")
    operation_code = Column(String(100), comment="工序编码")
    operation_name = Column(String(200), comment="工序名称")
    input_qty = Column(Integer, default=0, comment="投入数量")
    output_qty = Column(Integer, default=0, comment="产出数量")
    scrap_qty = Column(Integer, default=0, comment="不良/报废数量")
    defect_reason = Column(String(500), comment="不良原因")
    labor_hours = Column(Float, default=0, comment="工时(小时)")
    machine_hours = Column(Float, default=0, comment="设备工时(小时)")
    status = Column(String(20), default="draft", comment="状态: draft/submitted/approved/rejected")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── M02 BOM 版本锁定 ────────────────────────────────────────────────


class ProductBom(Base):
    """产品 BOM 物料清单表"""
    __tablename__ = "product_bom"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    product_id = Column(BigInteger, nullable=False, comment="关联产品ID")
    material_code = Column(String(100), nullable=False, comment="物料编码")
    material_name = Column(String(200), nullable=False, comment="物料名称")
    qty_per_unit = Column(Float, default=1, comment="单件用量")
    unit = Column(String(20), nullable=False, comment="单位")
    material_type = Column(String(50), default="raw", comment="类型: raw/semi/finished")
    scrap_rate = Column(Float, default=0, comment="损耗率(%)")
    issue_operation_seq = Column(String(50), comment="投料工序序号")
    is_key_material = Column(Boolean, default=False, comment="关键物料标记")
    version = Column(Integer, default=1, comment="BOM 版本号")
    effective_from = Column(Date, comment="生效日期")
    is_active = Column(Boolean, default=True, comment="是否激活")
    remark = Column(Text, comment="备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BomSnapshot(Base):
    """BOM 快照表（工单下达时生成）"""
    __tablename__ = "bom_snapshots"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    work_order_id = Column(BigInteger, nullable=False, comment="工单ID")
    bom_version = Column(Integer, default=1, comment="快照时的 BOM 版本")
    snapshot_data = Column(Text, comment="BOM快照内容（物料清单 JSON）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
