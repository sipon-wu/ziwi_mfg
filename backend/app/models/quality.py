from sqlalchemy import Column, BigInteger, String, Integer, Boolean, Text, DateTime, Numeric
from sqlalchemy.sql import func
from app.core.database import Base


class QcPointConfig(Base):
    __tablename__ = "qc_point_config"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    point_type = Column(String(20), nullable=False, comment="IQC/IPQC/FQC/OQC")
    point_name = Column(String(200), nullable=False)
    is_enabled = Column(Boolean, default=True)
    sampling_plan = Column(String(200))
    patrol_frequency = Column(Integer)
    material_id = Column(BigInteger)
    process_id = Column(BigInteger)
    priority = Column(Integer, default=0)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InspectionStandard(Base):
    __tablename__ = "inspection_standard"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    name = Column(String(200), nullable=False)
    standard_type = Column(String(20), nullable=False, default="enterprise", comment="national/enterprise")
    version = Column(String(50), default="1.0")
    is_enabled = Column(Boolean, default=True)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InspectionItem(Base):
    __tablename__ = "inspection_item"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    standard_id = Column(BigInteger, nullable=False, comment="FK to inspection_standard.id")
    item_name = Column(String(200), nullable=False)
    # 规格限改为数值型：SQL 层可直接 BETWEEN/比较（此前为 VARCHAR，"9">"10" 会逻辑错）
    spec_upper_limit = Column(Numeric(18, 6))
    spec_lower_limit = Column(Numeric(18, 6))
    unit = Column(String(20))
    method = Column(String(200))
    sort_order = Column(Integer, default=0)
    is_auto_generated = Column(Boolean, default=False, comment="FMEA 自动生成的检验项建议")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class InspectionOrder(Base):
    __tablename__ = "inspection_order"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    order_no = Column(String(100), nullable=False)
    order_type = Column(String(20), nullable=False, comment="first/inspection/spot_check")
    work_order_id = Column(BigInteger)
    process_id = Column(BigInteger)
    material_id = Column(BigInteger)
    qc_point_id = Column(BigInteger, comment="FK to qc_point_config.id")
    inspector_id = Column(BigInteger)
    result = Column(String(10), comment="ACC/REJ/UAI")
    judge_at = Column(DateTime(timezone=True))
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InspectionResult(Base):
    __tablename__ = "inspection_result"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    order_id = Column(BigInteger, nullable=False, comment="FK to inspection_order.id")
    item_id = Column(BigInteger, comment="FK to inspection_item.id")
    item_name = Column(String(200), comment="冗余字段")
    # spec_value 保持文本：实测为**区间描述**（如 "39.95~40.05"、"0~1.6"），非单值，不能改数值
    spec_value = Column(String(100))
    measured_value = Column(Numeric(18, 6))
    deviation = Column(Numeric(18, 6))
    unit = Column(String(20))
    result = Column(String(10), comment="PASS/FAIL")
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class QualityReport(Base):
    __tablename__ = "quality_report"
    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    report_type = Column(String(20), nullable=False, comment="daily/weekly/monthly")
    period = Column(String(20), nullable=False, comment="统计周期, 如 2026-06-13")
    report_data = Column(Text, comment="报表数据 JSON 字符串")
    generated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
