from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, Text, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class SpcControlLimit(Base):
    """控制限配置"""
    __tablename__ = "spc_control_limits"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    chart_type = Column(String(20), nullable=False, comment="xbar_r / p / np")
    dimension_key = Column(String(200), nullable=False, comment="维度标识：product_id / process_id / item_id")
    cl = Column(Float, nullable=False, comment="中心线")
    ucl = Column(Float, nullable=False, comment="上控制限")
    lcl = Column(Float, nullable=False, comment="下控制限")
    usl = Column(Float, comment="规格上限（用于能力分析）")
    lsl = Column(Float, comment="规格下限")
    mode = Column(String(20), default="auto", comment="auto / manual")
    subgroup_count = Column(Integer, default=0, comment="参与计算的子组数")
    calculated_at = Column(DateTime(timezone=True), comment="计算时间")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SpcDataPoint(Base):
    """控制图数据点"""
    __tablename__ = "spc_data_points"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    chart_type = Column(String(20), nullable=False, comment="xbar_r / p / np")
    dimension_key = Column(String(200), nullable=False, comment="与 SpcControlLimit.dimension_key 对应")
    subgroup_no = Column(Integer, nullable=False, comment="子组号")
    sample_values = Column(Text, comment="JSON 数组，如 '[12.3,12.5,12.1]'")
    xbar = Column(Float, comment="子组均值")
    r = Column(Float, comment="子组极差")
    p_value = Column(Float, comment="p/np 图用：不良率")
    np_value = Column(Integer, comment="np 图用：不良品数")
    is_anomaly = Column(Boolean, default=False, comment="是否异常点")
    anomaly_rules = Column(Text, comment="JSON 数组，触发规则的编号列表")
    excluded = Column(Boolean, default=False, comment="是否被剔除")
    exclude_reason = Column(String(500), comment="剔除原因")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class SpcAlert(Base):
    """判异告警记录"""
    __tablename__ = "spc_alerts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    chart_type = Column(String(20), nullable=False, comment="xbar_r / p / np")
    dimension_key = Column(String(200), nullable=False)
    alert_rule = Column(Integer, nullable=False, comment="Nelson 规则编号 1-7")
    alert_desc = Column(String(500), nullable=False, comment="规则描述")
    subgroup_no = Column(Integer, nullable=False, comment="触发子组号")
    data_point_id = Column(BigInteger, nullable=False, comment="FK to spc_data_points.id")
    severity = Column(String(20), default="medium", comment="low / medium / high / critical")
    is_read = Column(Boolean, default=False, comment="是否已读")
    acknowledged_at = Column(DateTime(timezone=True), comment="确认时间")
    acknowledged_by = Column(BigInteger, comment="确认人ID")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
