# ── 基础数据模块 ORM 模型 ─────────────────────────────────────────
# M01 产品管理 | M04 工序定义 | M05 工作中心 | M03 工艺路线 | M06 工厂日历

from sqlalchemy import Column, BigInteger, String, Integer, Float, DateTime, Text, Date, Boolean
from sqlalchemy.sql import func
from app.core.database import Base


# ── M04 工序定义 ────────────────────────────────────────────────

class Operation(Base):
    """工序定义表"""
    __tablename__ = "operations"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    code          = Column(String(100), nullable=False, comment="工序编码")
    name          = Column(String(200), nullable=False, comment="工序名称")
    op_type       = Column(String(50), nullable=False, comment="工序类型: machining/assembly/heat_treat/surface_treat/inspect/pack/reaction/blend/separation/filling/transport")
    setup_time    = Column(Float, default=0, comment="准备时间(分钟)")
    unit_time     = Column(Float, default=0, comment="单件加工时间(分钟/件)")
    labor_cert    = Column(Text, comment="人员资质要求(JSON): [{cert_type, cert_level, min_count}]")
    equip_req     = Column(Text, comment="设备能力要求(JSON): [{equip_type, capability, count}]")
    material_reqs = Column(Text, comment="物料要求(JSON): [{material_type, spec}]")
    sop_refs      = Column(Text, comment="作业标准/法(JSON): [{sop_code, sop_name, doc_url}]")
    env_req       = Column(Text, comment="环境要求(JSON): {temp_min, temp_max, humidity_min, humidity_max, clean_level}")
    remark        = Column(Text, comment="备注")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── M05 工作中心 ────────────────────────────────────────────────

class WorkCenter(Base):
    """工作中心表"""
    __tablename__ = "work_centers"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id       = Column(String(50), nullable=False, comment="租户ID")
    code            = Column(String(100), nullable=False, comment="工作中心编码")
    name            = Column(String(200), nullable=False, comment="工作中心名称")
    wc_type         = Column(String(50), nullable=False, comment="类型: production_line/work_cell/workstation")
    org_id          = Column(BigInteger, comment="所属组织ID")
    efficiency      = Column(Float, default=0.85, comment="效率因子(0~1)")
    equipment_count = Column(Integer, default=0, comment="设备数")
    labor_count     = Column(Integer, default=0, comment="人员数")
    capacity_per_shift = Column(Float, comment="每班产能(件)")
    is_esd          = Column(Boolean, default=False, comment="ESD静电防护标识")
    shift_config    = Column(Text, comment="班次配置(JSON): [{shift_name, start_time, end_time, hours}]")
    calendar_override = Column(Text, comment="工作日历覆盖(JSON): {weekend_days, work_days_override}")
    description     = Column(Text, comment="描述")
    is_active       = Column(Boolean, default=True, comment="启用状态")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WcEquipment(Base):
    """工作中心关联设备表"""
    __tablename__ = "wc_equipments"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    wc_id         = Column(BigInteger, nullable=False, comment="工作中心ID")
    equip_id      = Column(BigInteger, nullable=False, comment="设备ID")
    is_primary    = Column(Boolean, default=False, comment="是否主设备")
    capability_params = Column(Text, comment="能力参数(JSON)")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class WcTeam(Base):
    """工作中心关联班组表"""
    __tablename__ = "wc_teams"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id  = Column(String(50), nullable=False, comment="租户ID")
    wc_id      = Column(BigInteger, nullable=False, comment="工作中心ID")
    team_name  = Column(String(200), nullable=False, comment="班组名称")
    leader_id  = Column(BigInteger, comment="班组长用户ID")
    member_ids = Column(Text, comment="成员用户ID列表(JSON)")
    team_type  = Column(String(50), default="regular", comment="班组类型: regular/rotating/shift")
    is_active  = Column(Boolean, default=True, comment="启用状态")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── M03 工艺路线 ────────────────────────────────────────────────

class ProcessRoute(Base):
    """工艺路线主表"""
    __tablename__ = "process_routes"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id       = Column(String(50), nullable=False, comment="租户ID")
    code            = Column(String(100), nullable=False, comment="路线编码")
    name            = Column(String(200), nullable=False, comment="路线名称")
    version         = Column(Integer, default=1, comment="版本号")
    status          = Column(String(20), default="draft", comment="状态: draft/published/archived")
    source_route_id = Column(BigInteger, comment="源路线ID(复制创建时)")
    route_type      = Column(String(20), default="discrete", comment="路线类型: discrete(离散)/process(流程)")
    effective_from  = Column(Date, comment="生效日期")
    effective_to    = Column(Date, comment="失效日期")
    description     = Column(Text, comment="描述")
    created_by      = Column(BigInteger, comment="创建人ID")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    updated_at      = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
    published_at    = Column(DateTime(timezone=True), comment="发布时间")
    archived_at     = Column(DateTime(timezone=True), comment="归档时间")


class RouteStep(Base):
    """工艺路线工序步骤表"""
    __tablename__ = "route_steps"

    id                = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id         = Column(String(50), nullable=False, comment="租户ID")
    route_id          = Column(BigInteger, nullable=False, comment="工艺路线ID")
    operation_id      = Column(BigInteger, nullable=False, comment="工序ID(引用operations.id)")
    step_name         = Column(String(200), comment="步骤名称(可覆盖工序名称)")
    step_seq          = Column(Integer, nullable=False, comment="步骤序号")
    step_type         = Column(String(20), default="production", comment="步骤类型: production/inspect/outsource")
    wc_id             = Column(BigInteger, comment="执行工作中心ID(引用work_centers.id)")
    setup_time_override   = Column(Float, comment="准备时间覆盖(分钟)")
    unit_time_override    = Column(Float, comment="单件加工时间覆盖(分钟)")
    is_parallel_eligible  = Column(Boolean, default=False, comment="是否允许并行")
    is_outsource          = Column(Boolean, default=False, comment="是否为外协工序")
    next_step_seq         = Column(Integer, comment="下一工序序号(串行) / 空表示末工序")
    parallel_group        = Column(String(50), comment="并行组标识(同组工序可并行执行)")
    remark                = Column(Text, comment="备注")
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProductRoute(Base):
    """产品-工艺路线关联表"""
    __tablename__ = "product_routes"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id       = Column(String(50), nullable=False, comment="租户ID")
    product_id      = Column(BigInteger, nullable=False, comment="产品ID")
    route_id        = Column(BigInteger, nullable=False, comment="工艺路线ID")
    is_default      = Column(Boolean, default=False, comment="是否为默认路线")
    effective_from  = Column(Date, comment="关联生效日期")
    effective_to    = Column(Date, comment="关联失效日期")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())


# ── M01 产品管理 ────────────────────────────────────────────────

class Product(Base):
    """产品主数据表"""
    __tablename__ = "products"

    id            = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    code          = Column(String(100), nullable=False, comment="产品编码")
    name          = Column(String(200), nullable=False, comment="产品名称")
    spec          = Column(String(200), comment="规格型号")
    unit          = Column(String(20), nullable=False, comment="单位: 个/件/套/Kg/m")
    product_type  = Column(String(50), nullable=False, comment="产品类型: final(成品)/semi(半成品)/raw(原材料)")
    category      = Column(String(100), comment="产品分类")
    weight        = Column(Float, comment="重量(kg)")
    drawing_url   = Column(Text, comment="图纸附件URL(JSON数组)")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    remark        = Column(Text, comment="备注")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class ProductVersion(Base):
    """产品版本表"""
    __tablename__ = "product_versions"

    id              = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id       = Column(String(50), nullable=False, comment="租户ID")
    product_id      = Column(BigInteger, nullable=False, comment="产品ID")
    version_label   = Column(String(50), nullable=False, comment="版本标签 e.g. V1.0")
    status          = Column(String(20), default="draft", comment="状态: draft/published/archived")
    effective_from  = Column(Date, comment="生效日期")
    effective_to    = Column(Date, comment="失效日期")
    description     = Column(Text, comment="版本描述")
    created_by      = Column(BigInteger, comment="创建人ID")
    created_at      = Column(DateTime(timezone=True), server_default=func.now())
    published_at    = Column(DateTime(timezone=True), comment="发布时间")


# ── M06 工厂日历 ────────────────────────────────────────────────

class FactoryCalendar(Base):
    """工厂日历表"""
    __tablename__ = "factory_calendars"

    id         = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id  = Column(String(50), nullable=False, comment="租户ID")
    year       = Column(Integer, nullable=False, comment="年份")
    cal_date   = Column(Date, nullable=False, comment="日期")
    day_type   = Column(String(20), nullable=False, comment="类型: workday/rest/holiday/adjust_work/adjust_rest")
    name       = Column(String(200), comment="名称(如'国庆节')")
    is_system  = Column(Boolean, default=False, comment="是否系统预设(周末规则)")
    weekday    = Column(Integer, comment="星期几(1~7, 1=周一)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
