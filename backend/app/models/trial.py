from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class TrialOrder(Base):
    """试产工单"""
    __tablename__ = "trial_orders"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    order_no = Column(String(64), nullable=False, comment="工单编号 NP-YYYYMM-NNNN")
    trial_type = Column(String(32), nullable=False, comment="new_product/new_process/new_material/eco_verification/tooling_trial")
    status = Column(String(20), default="planning", comment="planning/lab_trial/pilot_run/batch_verify/review/production/terminated")
    product_id = Column(BigInteger, comment="关联产品ID")
    product_name = Column(String(200), nullable=False, comment="产品名称")
    product_spec = Column(String(256), comment="产品规格")
    planned_qty = Column(Integer, comment="计划数量")
    completed_qty = Column(Integer, default=0, comment="已完成数量")
    priority = Column(Integer, default=500, comment="优先级(越小越高)")
    lab_required = Column(Boolean, default=False, comment="是否需要实验室检测")
    scheme_json = Column(Text, comment="试产方案 JSON")
    target_json = Column(Text, comment="预期目标 JSON")
    key_params = Column(Text, comment="关键参数 JSON")
    source_route_id = Column(BigInteger, comment="引用的正式路线ID")
    bom_verified = Column(Boolean, default=False, comment="BOM是否已验证")
    inspection_plan = Column(Text, comment="检验方案 JSON")
    started_at = Column(DateTime(timezone=True), comment="开始时间")
    completed_at = Column(DateTime(timezone=True), comment="完成时间")
    terminated_reason = Column(Text, comment="终止原因")
    created_by = Column(BigInteger, comment="创建人")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class TrialRoute(Base):
    """试产工艺路线"""
    __tablename__ = "trial_routes"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    trial_order_id = Column(BigInteger, nullable=False, comment="FK to trial_orders.id")
    route_json = Column(Text, nullable=False, comment="完整路线数据 JSON")
    source_type = Column(String(20), default="manual", comment="template/manual")
    source_route_id = Column(BigInteger, comment="源正式路线ID")
    name = Column(String(200), comment="路线名称")
    description = Column(Text, comment="路线描述")
    change_notes = Column(Text, comment="变更说明")
    is_active = Column(Boolean, default=True)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TrialBom(Base):
    """试产BOM"""
    __tablename__ = "trial_bom"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    trial_order_id = Column(BigInteger, nullable=False, comment="FK to trial_orders.id")
    bom_json = Column(Text, nullable=False, comment="完整物料清单 JSON")
    source_type = Column(String(20), default="manual", comment="formal_bom/manual")
    source_bom_id = Column(BigInteger, comment="源正式BOM ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class TrialReview(Base):
    """试产评审记录"""
    __tablename__ = "trial_reviews"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    trial_order_id = Column(BigInteger, nullable=False, comment="FK to trial_orders.id")
    review_stage = Column(String(20), comment="评审阶段")
    conclusion = Column(String(20), default="pending", comment="pending/approved/conditional_approve/terminated/adjust")
    summary_attachments = Column(Text, comment="评审附件 JSON")
    review_items = Column(Text, comment="评审项列表 JSON")
    summary_data = Column(Text, comment="汇总的试产数据 JSON")
    reviewer = Column(BigInteger, comment="评审人")
    reviewed_at = Column(DateTime(timezone=True), comment="评审时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
