# ── 基础数据模块 ORM 模型 ─────────────────────────────────────────
# M01 产品管理 | M04 工序定义 | M05 工作中心 | M03 工艺路线 | M06 工厂日历

from sqlalchemy import (Column, BigInteger, String, Integer, Float, DateTime, Text, Date,
                       Boolean, UniqueConstraint, text)
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE


# ── M04 工序定义 ────────────────────────────────────────────────

class Operation(Base):
    """工序定义表"""
    __tablename__ = "operations"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    code          = Column(String(100), nullable=False, comment="工序编码")
    name          = Column(String(200), nullable=False, comment="工序名称")
    # 值域唯一真源：app/core/enums.py::OP_TYPE_LABELS（14 个值，含 incoming_qc/
    # process_qc/final_qc）。这里不再重复列一遍 —— 上一版列在注释里的 11 个值
    # 被前端抄成两份常量，结果库里出现的 *_qc 一个都不在，页面直接印英文原文。
    op_type       = Column(String(50), nullable=False, comment="工序类型（值域见 core/enums.py）")
    setup_time    = Column(Float, default=0, comment="准备时间(分钟)")
    unit_time     = Column(Float, default=0, comment="单件加工时间(分钟/件)")
    labor_cert    = Column(Text, comment="人员资质要求(JSON): [{cert_type, cert_level, min_count}]")
    equip_req     = Column(Text, comment="设备能力要求(JSON): [{equip_type, capability, count}]")
    material_reqs = Column(Text, comment="物料要求(JSON): [{material_type, spec}]")
    sop_refs      = Column(Text, comment="作业标准/法(JSON): [{sop_code, sop_name, doc_url}]")
    env_req       = Column(Text, comment="环境要求(JSON): {temp_min, temp_max, humidity_min, humidity_max, clean_level}")
    remark        = Column(Text, comment="备注")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    # 关键工序（CTQ 落点）：PFMEA 发布时把高风险工序标到这里，工艺路线的
    # route_steps 通过 operation_id 天然带出，不需要在每条路线里各刷一遍。
    #
    # 为什么 NOT NULL + server_default 而不是 nullable：NOT NULL 才能让下游
    # `WHERE is_critical` 不必每处都写 `OR IS NULL`（本项目已有 `is_system`
    # 这类可空布尔导致 `WHERE x = false` 静默漏行的前科）。server_default 是
    # 给**老库 ALTER** 用的 —— 已有行必须能拿到 false，否则加列当场失败。
    is_critical   = Column(Boolean, nullable=False, server_default=text("false"),
                           default=False, comment="关键工序(PFMEA 高风险自动标记)")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    # 工序编码在租户内唯一。
    #
    # 没有这条约束时，同一租户可以有两条 code 完全相同的工序，而**没有任何一处
    # 会报错**：`route_steps` 按 operation_id 引用（不重），但凡是按 code 查找的
    # 地方（导入模板、报表聚合、print 模板）都会随机命中其中一条 —— 表现为
    # "同一个工序有时显示 A 名、有时显示 B 名"，且换了顺序结果就变。
    # 库级约束是唯一能挡住它的地方：应用层查重总有并发窗口。
    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_operations_tenant_code"),
    )


# ── M05 工作中心 ────────────────────────────────────────────────

class WorkCenter(Base):
    """工作中心表"""
    __tablename__ = "work_centers"

    id              = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    wc_id         = Column(BigInteger, nullable=False, comment="工作中心ID")
    equip_id      = Column(BigInteger, nullable=False, comment="设备ID")
    is_primary    = Column(Boolean, default=False, comment="是否主设备")
    capability_params = Column(Text, comment="能力参数(JSON)")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class WcTeam(Base):
    """工作中心关联班组表"""
    __tablename__ = "wc_teams"

    id         = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id              = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id                = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    # ★ 同一产品同一路线只能挂一次。挂两次不会报错，只会让"默认哪条"
    #   更难判 —— 而默认路线解析错是静默的（建单悄悄不带路线或带错路线）。
    # ★ 默认路线唯一走**部分唯一索引**（`WHERE is_default`），在
    #   migrations/20261106c_product_route_perm.py 里逐条 CreateIndex：
    #   SQLAlchemy 2.0 的 CreateTable 不带索引，写在 __table_args__ 里
    #   对既有库不生效，容易造成"模型里有、库里没有"的假安全感。
    __table_args__ = (
        UniqueConstraint("tenant_id", "product_id", "route_id",
                         name="uq_product_routes_tenant_product_route"),
    )

    id              = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id              = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id         = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id  = Column(String(50), nullable=False, comment="租户ID")
    year       = Column(Integer, nullable=False, comment="年份")
    cal_date   = Column(Date, nullable=False, comment="日期")
    day_type   = Column(String(20), nullable=False, comment="类型: workday/rest/holiday/adjust_work/adjust_rest")
    name       = Column(String(200), comment="名称(如'国庆节')")
    is_system  = Column(Boolean, default=False, comment="是否系统预设(周末规则)")
    weekday    = Column(Integer, comment="星期几(1~7, 1=周一)")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── M00 供应商主数据（B-11 / C-78）───────────────────────────────

class Supplier(Base):
    """供应商主数据 —— MES 侧**只读快照 + 种子演示数据**。

    ★ 权威源在 ERP。本表存在的唯一理由是 MES 需要它做两件事：
    ① 来料检验 / NCR 能归到供应商（"按供应商分摊不良"此前永远算不出来，
       因为 `ncr_records.supplier_id` 有列、没有可指向的表）；
    ② 来料收货要记"这批货是谁送的"。

    **不承担供应商生命周期管理** —— 准入、评级、SRM 协同属 M09/ERP 边界
    （产品决策：供应商主数据 → M01 ERP 优先；M09 SRM 只管生命周期不管理主数据）。
    因此本模块只提供读接口，写入口留给后续 ERP 同步（`source='erp'`），
    演示环境由 `seeds/suppliers_seed.py` 造种子（`source='seed'`）。
    """

    __tablename__ = "suppliers"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    code          = Column(String(50), nullable=False, comment="供应商编码")
    name          = Column(String(200), nullable=False, comment="供应商名称")
    short_name    = Column(String(50), comment="简称（列表与选择器显示）")
    category      = Column(String(30), default="raw",
                           comment="类别: raw 原材料/pack 包材/outsource 外协/service 服务")
    contact_name  = Column(String(100), comment="联系人")
    contact_phone = Column(String(50), comment="联系电话")
    email         = Column(String(100), comment="邮箱")
    address       = Column(String(300), comment="地址")
    tax_no        = Column(String(50), comment="税号（对账用）")
    status        = Column(String(20), default="active", comment="状态: active/disabled")
    source        = Column(String(20), default="seed",
                           comment="来源: seed 种子/erp ERP同步/manual 手工")
    erp_code      = Column(String(50), comment="ERP 侧供应商编码（同步对账用）")
    remark        = Column(Text)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_supplier_tenant_code"),
    )
