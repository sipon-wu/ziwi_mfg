from sqlalchemy import (
    Column, BigInteger, String, Integer, Float, Boolean, DateTime, Text, JSON, Date,
    Numeric, UniqueConstraint, text,
)
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
    # ★ 点检项模板（配置态）：一行 JSON，不建独立模板表。
    #   取舍：模板不需要被统计查询，只被 ``generate_due_tasks`` 快照进
    #   ``maintenance_task_items``。建独立模板表要再加 CRUD + 权限码 + 页面，
    #   收益仅"可 SQL 查模板"，一期不值。
    #   结构：[{"check_item": "皮带张力", "check_method": "目视",
    #           "standard_desc": "无明显松弛", "sort_order": 1}, ...]
    checklist_template = Column(JSON, comment="点检项模板（JSON 数组），生成任务时快照")
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


class MaintenanceTaskItem(Base):
    """保养/点检任务项 —— 项级执行载体。

    为什么必须单独一张表
    --------------------
    ``maintenance_tasks`` 只有一个 ``result = Column(Text)`` 自由文本。由此连带缺失：

    - 没有"项级三态"（正常 / 异常 / 不适用）→ 点检退化成"整单打个勾"；
    - 数不出"几项异常"→ 异常项无法自动挂安灯/报修；
    - 没有逐项实测值与拍照 → 报修/停机上报缺载体。

    状态口径：``verdict`` **NULL = 未点检**，非 NULL 即"已点检"。
    刻意用 ``VARCHAR`` 而不是 BOOLEAN：三态（normal/abnormal/na）不是真假二值，
    而且 PG 的 boolean 只认 true/false，历史写法里的 0/1 会直接 DataError（铁律 1）。
    """

    __tablename__ = "maintenance_task_items"

    id             = Column(PK_TYPE, primary_key=True, autoincrement=True)
    # ★ tenant_id NOT NULL 且**由应用层显式写**：基类 execute() 只为
    #   UPDATE/DELETE 注入 tenant_id，INSERT 一律不管（漏写即 500）。
    tenant_id      = Column(String(50), nullable=False, comment="租户ID")
    task_id        = Column(BigInteger, nullable=False, comment="FK to maintenance_tasks.id")
    line_no        = Column(Integer, nullable=False, comment="行号（同任务内唯一）")
    check_item     = Column(String(200), nullable=False, comment="点检项目名")
    check_method   = Column(String(200), comment="点检方法（目视/手感/卡尺）")
    standard_desc  = Column(String(200), comment="判定基准描述")
    sort_order     = Column(Integer, nullable=False, server_default=text("0"),
                            comment="排序（沿模板顺序）")
    verdict        = Column(String(16), comment="normal/abnormal/na；NULL=未点检")
    measured_value = Column(Numeric(18, 6), comment="实测值（计量项）")
    remark         = Column(String(500), comment="备注")
    photo_urls     = Column(JSON, comment="异常拍照，最多 3 张")
    checked_by     = Column(BigInteger, comment="点检人")
    checked_at     = Column(DateTime(timezone=True), comment="点检时刻")
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # 同任务同行号唯一 —— 逐项提交的**幂等性**兜底：即使应用层判断失手，
        # DB 也不会出现两行同号项（"复点检"只更新、不新增）。
        UniqueConstraint("tenant_id", "task_id", "line_no",
                         name="uq_mti_tenant_task_line"),
    )


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
