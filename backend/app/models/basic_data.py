# ── 基础数据模块 ORM 模型 ─────────────────────────────────────────
# M01 产品管理 | M04 工序定义 | M05 工作中心 | M03 工艺路线 | M06 工厂日历

from sqlalchemy import (Column, BigInteger, String, Integer, Float, DateTime, Text, Date,
                       Boolean, UniqueConstraint, Index, text)
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
    setup_time    = Column(Float, default=0, comment="准备时间(分钟/**批**)——每批一次，不含单件加工")
    unit_time     = Column(Float, default=0, comment="加工时间(分钟/**批**)——一次加工同时处理 batch_size 件")
    # ★ 同装量（2026-11-07 新增）：一次加工同时处理几件。默认 1 = 单件流。
    #
    # 为什么需要它：这类"炉/烘箱/罐"工序的工艺时间是**一炉**的时长，不是一件的。
    # 推进器定子线的「固化烘烤」工艺 120 分/炉、一炉 4 个 —— 没有这一列时只能
    # 把 120÷4=30 手填进 `unit_time`，于是**「4」这个事实在库里不存在**：
    # 换个人看到 30 根本看不出它是 120÷4，产能复核时也无法用原始工艺时间对账。
    # 代价是那条线被低估 4 倍（单班闭环下线 1 台 vs 2 台）。
    #
    # 口径（产能核算唯一用法）：
    #     每件占机 = (unit_time + setup_time) / batch_size
    # batch_size=1 时退化为原来的 unit_time + setup_time，**存量数据语义不变**。
    # 消费方：`scripts/check_capacity_consistency.py`（口径 A/B/C 都走这个式子）。
    # ⚠️ NOT NULL + server_default 是必须的：只给 `default=` 那只是 ORM 层默认，
    #    老库加列时会失败（PG 方言铁律第 1 条）。
    batch_size    = Column(Integer, nullable=False, server_default="1", default=1,
                           comment="同装量(件/批)：一次加工同时处理几件。每件占机=(unit_time+setup_time)/batch_size")
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


# ── M04b 报工小组（工序分组）──────────────────────────────────────

class OperationGroup(Base):
    """报工小组：把邻近 / 同质的工序并成一组，一组统一报工、统一看活。

    ## 为什么是 tenant 级，不挂在工艺路线版本上

    同一道「装配」工序在 A 线属于"前段组"、在 B 线可能属于"后段组"——
    那确实是路线的事。但路线级分组要求分组数据跟着 ``process_routes`` 一起
    版本化（每次路线升版都得复制一遍分组关系），复杂度高一个量级，
    而这个产品线的现场反馈是"我们车间就这么几个组，人不换组就不改"。
    所以先做 tenant 级；将来真需要路线级，再加一层 ``route_id`` 可空列收敛。

    ## 为什么一道工序可以属于多个组

    唯一键是 ``(group_id, operation_id)`` 而不是 ``operation_id`` 单列。
    现场真实形态就是这样：装配工序既在"前段组"的看板上，也在"总装组"的
    看板上——两个组的人都得能看见这批活。做成单属会把第二个组的人静默挡在门外，
    而**没有任何界面会报错**，只是活不见了。

    ## 与 ``work_order_steps.wc_id`` 的口径差异（刻意不同，别统一）

    ``wc_id`` 是**下达那一刻的工艺事实**，必须快照（路线改版不能改写历史）。
    分组的归属则是**今天这批人怎么分队**——把它快照进工序行会立刻产生
    "一道工序属两个组、快照列只能存一个"的信息丢失，而分组本来就是
    会被人反复重切的东西（换班、换线、赶工）。所以工序行上**没有** ``group_id`` 列，
    一律按 ``operation_id`` 实时关联。
    """

    __tablename__ = "operation_groups"

    id         = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id  = Column(String(50), nullable=False, comment="租户ID")
    code       = Column(String(100), nullable=False, comment="小组编码")
    name       = Column(String(200), nullable=False, comment="小组名称（车间看板上显示的就是它）")
    remark     = Column(Text, comment="备注")
    is_active  = Column(Boolean, default=True, comment="启用状态")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "code", name="uq_op_group_tenant_code"),
    )


class OperationGroupMember(Base):
    """小组 ↔ 工序 的成员关系（多对多）。

    ★ ``tenant_id`` 是**冗余**的（group_id 已经决定了租户），保留它是为了让
      仓储层按该表作主表查询时租户注入能生效——注入层是拿 FROM 表名去
      找 ``tenant_id`` 列的，靠 join 过滤一旦有人写漏 WHERE 就是跨租户读。
      代价是 INSERT 必须**显式**写 tenant_id（本仓铁律：INSERT 的 tenant_id
      由应用层写，不靠 default）。
    """

    __tablename__ = "operation_group_members"

    id           = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id    = Column(String(50), nullable=False, comment="租户ID（冗余，供租户注入）")
    group_id     = Column(BigInteger, nullable=False, comment="小组ID（operation_groups.id）")
    operation_id = Column(BigInteger, nullable=False, comment="工序ID（operations.id）")
    created_at   = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        # 一组成员关系只能有一条。没有这条约束时重复保存会把同一道工序
        # 在同一组里插两遍，列表上看起来一样、`COUNT(*)` 却是两倍。
        UniqueConstraint("group_id", "operation_id", name="uq_op_group_member"),
        # 报工任务台按工序反查它属于哪些组 —— 每页 20 行各查一次，
        # 没索引就是 20 次全表扫。
        Index("ix_op_group_member_op", "tenant_id", "operation_id"),
    )


# ── M05 工作中心 ────────────────────────────────────────────────

class WorkCenter(Base):
    """工作中心表"""
    __tablename__ = "work_centers"

    id              = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id       = Column(String(50), nullable=False, comment="租户ID")
    code            = Column(String(100), nullable=False, comment="工作中心编码")
    name            = Column(String(200), nullable=False, comment="工作中心名称")
    # ★ 这一列混了两种正交语义（粒度 / 工艺性质），历史遗留：
    #   库里的实际取值是 `assembly` / `quality` / `machining`（工艺性质），
    #   而探针建工位填的是 `workstation`（粒度）；全库 `production_line` /
    #   `work_cell` **零使用**。原先这句注释只写了后三个粒度值，前端照它建了
    #   下拉，导致列表「类型」列 33/33 行裸渲染英文。
    #   真源见 `core.enums.WC_TYPE_LABELS`，前端对应 `config/enums.ts`。
    wc_type         = Column(String(50), nullable=False, comment="工作中心类别（粒度或工艺性质），取值见 core.enums.WC_TYPE_LABELS")
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
    # ── IE 精益配置（2026-11-11）──────────────────────────────────
    # ★ 两列刻意**可空且没有 Python 默认值**：NULL 的语义是「IE 还没给这道工序
    #   设标准」，分析端点据此判「未判」。给 default=0 会把「没配」变成「标准 0
    #   分钟」，于是所有实测都被判超节拍；给一个产品默认值（例如推进器 30 分）
    #   更糟 —— 换租户时拿别家的合同判本家的活，正是 C-111 抓到的那种残留。
    # ★ 配置挂在 route_steps 而不是 operations：同一道工序挂到不同产品/路线时，
    #   站位节拍可以不同（与已有的 setup_time_override 同一层 override 语义）。
    # ★ 工单下达时快照进 work_order_steps 同名列（见 20261111b 迁移）：
    #   IE 后来改了标准，不该把历史工单按新标准重判一遍。
    takt_target_min   = Column(Float, comment="IE 目标节拍(分钟/件)：该站位处理一件的目标时间；空=未配置")
    transit_limit_min = Column(Float, comment="IE 过站时效上限(分钟)：本道完工到下一道开工允许的最大等待；空=未配置")
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
