from sqlalchemy import Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, JSON, Date
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE

class EquipmentCategory(Base):
    __tablename__ = "equipment_categories"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    parent_id = Column(BigInteger, default=0)
    name = Column(String(200), nullable=False)
    code = Column(String(100), nullable=False)
    level = Column(Integer, default=0)
    sort_order = Column(Integer, default=0)
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class Equipment(Base):
    __tablename__ = "equipment"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    equipment_id = Column(BigInteger, nullable=False)
    task_no = Column(String(100))
    # ★ 来源计划：改造前任务与计划之间没有任何字段关联 —— 计划被执行过几次、
    #   下次什么时候到期，全都无从判断（计划就是一行死数据，见台账 C-39）
    plan_id = Column(BigInteger, comment="来源保养计划ID")
    # ★ 受影响工单：保养停机期间要顺延的那张单。
    #   work_orders 没有 equipment_id（只有 line_code/workshop），无法反查
    #   "这台设备上在制哪张单"，硬猜会把别人的单停掉，所以由计划/任务显式指定。
    work_order_id = Column(BigInteger, comment="受影响工单ID（选填，用于排产调整）")
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
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


class EquipmentDowntime(Base):
    """设备停机记录 —— 停机时长与 OEE 可用率的唯一来源（台账 B-12）。

    改造前设备只有 ``status`` 一个字段：能知道"现在故障"，但
    - 不知道**从什么时候开始**、**停了多久** → OEE 可用率没有分母；
    - 不知道**影响哪些工单** → 排产计划不会顺延，交期照旧；
    - 故障处理完没有任何历史 → 反复出问题的设备看不出来。

    由安灯（``call_type='equipment'``）自动开/关，也允许手工补录：
    ``ended_at`` 为空即"仍在停机"，同一台设备同时只应有一条未关闭记录。
    """

    __tablename__ = "equipment_downtimes"

    id               = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False)
    equipment_id     = Column(BigInteger, nullable=False, comment="设备ID")
    work_order_id    = Column(BigInteger, comment="受影响工单（安灯带上时）")
    andon_call_id    = Column(BigInteger, comment="来源安灯呼叫")
    started_at       = Column(DateTime(timezone=True), nullable=False, comment="停机开始")
    ended_at         = Column(DateTime(timezone=True), comment="停机结束，空=仍在停机")
    duration_minutes = Column(Float, comment="停机分钟数（关闭时计算）")
    downtime_type    = Column(String(32), default="fault",
                              comment="fault/setup/material/plan/other")
    reason           = Column(Text)
    resolved_by      = Column(BigInteger)
    created_at       = Column(DateTime(timezone=True), server_default=func.now())
