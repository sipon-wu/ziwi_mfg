# M15 实验室管理 — 数据库模型
from datetime import datetime
from sqlalchemy import Column, Integer, String, Text, DateTime, Float, Boolean, ForeignKey
from app.core.database import Base


class LabRequest(Base):
    """实验委托主表"""
    __tablename__ = "lab_requests"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    request_no = Column(String(64), nullable=False)
    title = Column(String(256), nullable=False)
    request_type = Column(String(32), nullable=False)  # mechanical/metallographic/chemical/...
    source_type = Column(String(32))  # trial_order/quality/complaint/manual
    source_id = Column(Integer, nullable=True)
    priority = Column(String(16), default="medium")  # high/medium/low
    sample_info = Column(Text)  # JSON
    description = Column(Text)
    status = Column(String(32), default="pending")  # pending/received/assigned/in_progress/reviewing/done
    assignee_id = Column(Integer, nullable=True)
    expected_date = Column(DateTime, nullable=True)
    conclusion = Column(String(32), nullable=True)  # pass/fail/inconclusive
    attachments = Column(Text)  # JSON
    created_by = Column(Integer, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class LabTestResult(Base):
    """检测结果明细表"""
    __tablename__ = "lab_test_results"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    request_id = Column(Integer, ForeignKey("lab_requests.id", ondelete="CASCADE"), nullable=False)
    item_name = Column(String(128), nullable=False)
    spec_value = Column(String(256))
    actual_value = Column(String(256))
    unit = Column(String(32))
    lower_limit = Column(Float, nullable=True)
    upper_limit = Column(Float, nullable=True)
    is_pass = Column(Boolean, nullable=True)
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class TestStandard(Base):
    """检验标准库"""
    __tablename__ = "test_standards"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    name = Column(String(128), nullable=False)
    category = Column(String(64))
    method = Column(String(256))
    default_lower_limit = Column(Float, nullable=True)
    default_upper_limit = Column(Float, nullable=True)
    unit = Column(String(32))
    description = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


class LabReport(Base):
    """实验报告"""
    __tablename__ = "lab_reports"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    request_id = Column(Integer, ForeignKey("lab_requests.id", ondelete="CASCADE"), nullable=False)
    report_no = Column(String(64), nullable=False)
    conclusion = Column(String(32))  # pass/fail/conditional
    summary = Column(Text)
    attachments = Column(Text)  # JSON
    published_by = Column(Integer, nullable=True)
    published_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)


class LabCalibration(Base):
    """校准记录"""
    __tablename__ = "lab_calibrations"

    id = Column(Integer, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, index=True)
    equipment_name = Column(String(128), nullable=False)
    calibrate_type = Column(String(32))  # internal/external
    calibrate_date = Column(DateTime, nullable=True)
    valid_until = Column(DateTime, nullable=True)
    result = Column(String(64))
    certificate = Column(String(256))
    remark = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
