from sqlalchemy import Column, BigInteger, String, Integer, DateTime, Text, JSON
from sqlalchemy.sql import func
from app.core.database import Base

class ExcelImportTask(Base):
    __tablename__ = "excel_import_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    task_name = Column(String(200), nullable=False, comment="任务名称")
    file_name = Column(String(500), nullable=False, comment="原始文件名")
    file_path = Column(String(1000), comment="服务端文件路径")
    file_size = Column(Integer, comment="文件大小(bytes)")
    import_type = Column(String(50), nullable=False, comment="导入类型: production/tpm/quality/andon/energy/equipment/employee/inventory")
    total_rows = Column(Integer, default=0, comment="总行数")
    success_rows = Column(Integer, default=0, comment="成功行数")
    failed_rows = Column(Integer, default=0, comment="失败行数")
    status = Column(String(20), default="pending", comment="状态: pending/processing/completed/failed")
    error_detail = Column(Text, comment="错误详情(JSON)")
    operator_id = Column(BigInteger, comment="操作人ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

class ImportTemplate(Base):
    __tablename__ = "import_templates"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    import_type = Column(String(50), unique=True, nullable=False, comment="导入类型编码")
    template_name = Column(String(200), nullable=False, comment="模板名称")
    description = Column(Text, comment="模板说明")
    columns_config = Column(JSON, nullable=False, comment="列配置: [{field, label, required, type, validate}]")
    file_path = Column(String(500), comment="模板文件路径")
    version = Column(String(20), default="1.0", comment="版本号")
    is_active = Column(Integer, default=1, comment="是否启用")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
