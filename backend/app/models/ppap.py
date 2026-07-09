from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class PpapLevel(Base):
    """PPAP 提交等级"""
    __tablename__ = "ppap_levels"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    level_no = Column(Integer, nullable=False, comment="1-5")
    level_name = Column(String(200), nullable=False, comment="等级名称")
    is_default = Column(Boolean, default=False, comment="是否默认等级")
    is_custom = Column(Boolean, default=False, comment="是否自定义")
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PpapElementTemplate(Base):
    """PPAP 文件包要素模板"""
    __tablename__ = "ppap_element_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    element_code = Column(String(50), nullable=False, comment="要素编码（如 E01=设计记录）")
    element_name = Column(String(200), nullable=False, comment="要素名称")
    description = Column(Text, comment="填写指南")
    is_required = Column(Boolean, default=True, comment="是否必填")
    sort_order = Column(Integer, default=0, comment="排序号")
    customer_id = Column(BigInteger, comment="客户自定义时，关联客户ID")
    level_no = Column(Integer, nullable=False, comment="关联等级")
    has_template = Column(Boolean, default=False, comment="是否有模板文件")
    template_file_url = Column(String(500), comment="模板文件URL")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class PpapSubmission(Base):
    """PPAP 提交记录"""
    __tablename__ = "ppap_submissions"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    submission_no = Column(String(100), nullable=False, comment="提交编号（自动生成）")
    product_id = Column(BigInteger, nullable=False, comment="关联产品")
    customer_id = Column(BigInteger, nullable=False, comment="关联客户")
    level_no = Column(Integer, nullable=False, comment="提交等级")
    version = Column(Integer, default=1, comment="版本号（初始1，重新提交+1）")
    status = Column(String(20), default="draft", comment="draft / pending / approved / rejected / conditional")
    submitted_at = Column(DateTime(timezone=True), comment="提交时间")
    approved_at = Column(DateTime(timezone=True), comment="批准时间")
    change_note = Column(Text, comment="版本变更说明")
    due_reminder = Column(Boolean, default=False, comment="到期提醒标记")
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class PpapSubmissionItem(Base):
    """PPAP 提交明细（要素→文件映射）"""
    __tablename__ = "ppap_submission_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    submission_id = Column(BigInteger, nullable=False, comment="FK to ppap_submissions.id")
    element_id = Column(BigInteger, nullable=False, comment="FK to ppap_element_templates.id")
    status = Column(String(20), default="not_started", comment="not_started / in_progress / completed / not_applicable")
    file_path = Column(String(500), comment="上传文件路径/URL")
    file_name = Column(String(200), comment="原始文件名")
    assignee_id = Column(BigInteger, comment="责任人")
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
