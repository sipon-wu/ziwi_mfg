from sqlalchemy import Column, BigInteger, String, Boolean, Integer, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class ApprovalTemplate(Base):
    __tablename__ = "approval_templates"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    name = Column(String(200), nullable=False, comment="模板名称")
    code = Column(String(100), nullable=False, comment="模板编码")
    biz_type = Column(String(50), comment="业务类型")
    form_schema = Column(JSON, comment="表单定义JSON")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ApprovalInstance(Base):
    __tablename__ = "approval_instances"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    template_id = Column(BigInteger, nullable=False, comment="模板ID")
    title = Column(String(200), nullable=False, comment="审批标题")
    biz_type = Column(String(50), comment="业务类型")
    biz_id = Column(String(100), comment="业务ID")
    applicant_id = Column(BigInteger, nullable=False, comment="申请人ID")
    status = Column(String(20), default="pending", comment="状态: pending/approved/rejected/canceled")
    form_data = Column(JSON, comment="表单数据")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ApprovalNode(Base):
    __tablename__ = "approval_nodes"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    approval_id = Column(BigInteger, nullable=False, comment="审批实例ID")
    node_order = Column(Integer, nullable=False, comment="节点顺序")
    approver_id = Column(BigInteger, comment="审批人ID")
    node_type = Column(String(20), default="approve", comment="节点类型: approve/cc")
    status = Column(String(20), default="pending", comment="状态: pending/approved/rejected")
    comment = Column(Text, comment="审批意见")
    operated_at = Column(DateTime(timezone=True), comment="操作时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
