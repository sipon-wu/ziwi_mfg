from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, JSON, Date
from sqlalchemy.sql import func
from app.core.database import Base

class EquipmentCategory(Base):
    __tablename__ = "equipment_categories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    parent_id = Column(BigInteger, default=0)
    name = Column(String(200), nullable=False)
    code = Column(String(100), nullable=False)
    level = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    equipment_code = Column(String(100), nullable=False)
    equipment_name = Column(String(200), nullable=False)
    category_id = Column(BigInteger, comment="分类ID")
    model = Column(String(200))
    manufacturer = Column(String(200))
    install_date = Column(Date)
    location = Column(String(200))
    status = Column(String(20), default="idle", comment="running/idle/maintenance/fault/scrapped")
    power_kw = Column(Float)
    parameters = Column(JSON)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MaintenancePlan(Base):
    __tablename__ = "maintenance_plans"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    equipment_id = Column(BigInteger, nullable=False)
    plan_name = Column(String(200), nullable=False)
    plan_type = Column(String(50), comment="daily/weekly/monthly/yearly")
    cycle_value = Column(Integer, default=1)
    cycle_unit = Column(String(20), default="month")
    last_execute_at = Column(DateTime(timezone=True))
    next_execute_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="active")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MaintenanceTask(Base):
    __tablename__ = "maintenance_tasks"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    equipment_id = Column(BigInteger, nullable=False)
    task_no = Column(String(100))
    task_type = Column(String(50), comment="repair/maintenance/inspection")
    priority = Column(Integer, default=0)
    description = Column(Text)
    assignee_id = Column(BigInteger)
    scheduled_start_at = Column(DateTime(timezone=True))
    scheduled_end_at = Column(DateTime(timezone=True))
    actual_start_at = Column(DateTime(timezone=True))
    actual_end_at = Column(DateTime(timezone=True))
    status = Column(String(20), default="pending", comment="pending/in_progress/completed/canceled")
    result = Column(Text)
    cost = Column(Float)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SparePart(Base):
    __tablename__ = "spare_parts"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    part_code = Column(String(100), nullable=False)
    part_name = Column(String(200), nullable=False)
    spec = Column(String(200))
    unit = Column(String(20))
    min_stock = Column(Integer, default=0)
    max_stock = Column(Integer, default=0)
    current_stock = Column(Integer, default=0)
    location = Column(String(200))
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class SparePartInventory(Base):
    __tablename__ = "spare_part_inventories"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    part_id = Column(BigInteger, nullable=False)
    change_type = Column(String(20), comment="in/out/adjust")
    qty = Column(Integer, nullable=False)
    before_qty = Column(Integer)
    after_qty = Column(Integer)
    reference_type = Column(String(50))
    reference_id = Column(String(100))
    operator_id = Column(BigInteger)
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
