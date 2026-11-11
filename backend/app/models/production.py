from sqlalchemy import (
    Column, BigInteger, String, Integer, Float, DateTime, Text, Date, Boolean,
    UniqueConstraint, Index,
)
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE


class WorkOrder(Base):
    __tablename__ = "work_orders"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    wo_no = Column(String(100), nullable=False, comment="工单编号")
    wo_type = Column(String(50), default="production", comment="工单类型: production/maintenance/quality")
    wo_status = Column(String(50), default="draft", comment="状态: draft/released/in_progress/paused/completed/closed/cancelled")
    product_code = Column(String(100), nullable=False, comment="产品编码")
    product_name = Column(String(200), nullable=False, comment="产品名称")
    planned_qty = Column(Integer, default=0, comment="计划数量")
    completed_qty = Column(Integer, default=0, comment="已完成数量")
    scrap_qty = Column(Integer, default=0, comment="报废数量")
    priority = Column(Integer, default=0, comment="优先级 0-5")
    scheduled_start_at = Column(DateTime(timezone=True), comment="计划开始时间")
    scheduled_end_at = Column(DateTime(timezone=True), comment="计划结束时间")
    actual_start_at = Column(DateTime(timezone=True), comment="实际开始时间")
    actual_end_at = Column(DateTime(timezone=True), comment="实际结束时间")
    assignee_id = Column(BigInteger, comment="负责人ID（派工到人）")
    assigned_org_id = Column(BigInteger, comment="派工班组/部门（organizations.id，场景 C-S2）")
    workshop = Column(String(100), comment="车间")
    # C-E7：工单挂在哪台设备 / 哪个工作中心做。改造前工单上没有这两个字段，
    # "设备已报废却还在给它排产"既拦不住（没有可拦的对象）也查不出（没有线索）。
    equipment_id = Column(BigInteger, comment="设备ID（equipment.id，C-E7 停用拦截用）")
    work_center_id = Column(BigInteger, comment="工作中心ID（work_centers.id，C-E7）")
    # ★ B-S3/B-E6：工单冻结的工艺路线（process_routes.id）。
    # 工艺升级是**新建一行版本**（不是改老行），工单拿着老行的 id 就自然
    # 沿用旧版 —— "在制工单用什么工艺"从口头约定变成可查证的外键。
    route_id = Column(BigInteger, comment="工艺路线ID（process_routes.id，B-S3/B-E6）")
    org_id = Column(BigInteger, comment="归属组织ID（数据范围过滤用，创建时取创建人主组织）")
    line_code = Column(String(100), comment="产线编码")
    remark = Column(Text, comment="备注")
    # M07 齐套性检查字段
    # no_bom = 该产品没有生效 BOM。改造前这种情况返回 "passed / 100%"，
    # 等于把「什么都没确认」说成「齐套通过」（台账 C-44）。
    material_check_status = Column(String(20), default="pending",
                                   comment="齐套状态: pending/passed/failed/force_passed/no_bom")
    material_check_result = Column(Text, comment="缺料明细（JSON）")

    __table_args__ = (
        # 单号在同租户内唯一。改造前 wo_no 无任何约束：并发或前端重试会
        # 静默产生两张同号工单，之后报工、入库、对账全部对不上。
        UniqueConstraint("tenant_id", "wo_no", name="uq_work_order_tenant_no"),
    )
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WorkOrderStatusLog(Base):
    __tablename__ = "work_order_status_logs"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    work_order_id = Column(BigInteger, nullable=False, comment="工单ID")
    from_status = Column(String(50), comment="原状态")
    to_status = Column(String(50), nullable=False, comment="目标状态")
    operator_id = Column(BigInteger, comment="操作人ID")
    remark = Column(Text, comment="备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class WorkReport(Base):
    __tablename__ = "work_reports"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    work_order_id = Column(BigInteger, nullable=False, comment="关联工单ID")
    org_id = Column(BigInteger, comment="归属组织ID（数据范围过滤用，取报工人主组织）")
    report_date = Column(Date, nullable=False, comment="报工日期")
    reporter_id = Column(BigInteger, nullable=False, comment="报工人ID")
    operation_code = Column(String(100), comment="工序编码")
    operation_name = Column(String(200), comment="工序名称")
    input_qty = Column(Integer, default=0, comment="投入数量")
    output_qty = Column(Integer, default=0, comment="产出数量")
    scrap_qty = Column(Integer, default=0, comment="不良/报废数量")
    defect_reason = Column(String(500), comment="不良原因")
    labor_hours = Column(Float, default=0, comment="工时(小时)")
    machine_hours = Column(Float, default=0, comment="设备工时(小时)")
    # 报工**时刻**（C-B2）。``report_date`` 只有日期，而"报工早于开工"这类
    # 时序错乱必须靠时刻才能判；只有日期的话，同一天内的先后无从区分。
    # 可空：历史数据没有这一列的值，不为难存量；新数据由 Service 兜 now()。
    reported_at = Column(DateTime(timezone=True), comment="报工时刻（C-B2 时序校验用）")
    status = Column(String(20), default="draft", comment="状态: draft/submitted/approved/rejected")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


# ── 工单工序实例（2026-11-10 · 报工管理改成工序任务台的地基）──────────


class WorkOrderStep(Base):
    """工单工序实例：下达那一刻按工艺路线**快照**展开的一条工序任务。

    ## 为什么是快照，不是实时 join ``route_steps``

    路线会被改版（加一道工序、换工作中心、调顺序）。实时 join 的话，一张三个月前
    的工单今天打开会显示"它从没走过的那道工序"，而它的报工记录里一行都对不上 ——
    **历史被后来的改版改写了，脏数据却是当时的人背锅**。``bom_snapshots`` 用的是
    同一个道理：下达那一刻的工艺是事实，日后的改动是另一件事。

    ## 为什么必须有这张表（而不是每次从 ``work_reports`` 反推）

    「这道工序报了多少 / 是不是在制 / 完没完工」—— 报工记录只能回答第一问，
    而且要靠 ``operation_code`` 字符串去猜。**工序级状态在库里一直没有任何载体**，
    于是两件事都做不成：

    - 报工管理只能做成"报工流水台账"（已发生的事），做不成"我今天该干什么"；
    - 扫码过站没法判断"这个码现在该过哪道" —— 组套页能定位到合装工序，
      是因为那个页面**硬编码了"这里就是合装"**，换一个工位就复用不了。

    一行 = 某张工单的第 N 道工序。``status`` 就是这条工序链路的当前位置。

    ## 状态取值

    ``pending`` 未开工 → ``in_progress`` 在制 → ``completed`` 已完工。
    **没有 blocked / paused**：阻塞与缺料都不是工序自身的状态 ——
    阻塞是安灯（``andon_call``）在报，缺料是工单级齐套检查在报。
    把它们塞进工序状态里，等于同一件事有两个真相源，早晚对不上。

    ## 累计量为什么落在这一行上

    ``output_qty`` 等是**该工序**的累计（不是工单的）。工单的 ``completed_qty``
    只记末道工序的合格产出（三桶口径见 ``production_repo._rollup_by_wo``），
    两者维度不同，不能互相覆盖。这里的累计量是"工序流转量"的来源。
    """

    __tablename__ = "work_order_steps"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(64), nullable=False, comment="租户ID")
    work_order_id = Column(BigInteger, nullable=False, comment="工单ID（work_orders.id）")
    # ★ 唯一性锚点是 (工单, 工序序号) 而不是工序编码：同一张工单的路线里
    #   同一道工序可以出现两次（返修复检），按编码唯一会把第二次直接吃掉。
    step_seq = Column(Integer, nullable=False, comment="工序序号（快照自 route_steps.step_seq）")
    operation_id = Column(BigInteger, comment="工序ID（operations.id）")
    operation_code = Column(String(100), comment="工序编码（快照，报工按它对账）")
    operation_name = Column(String(200), comment="工序名称（快照）")
    # ★ 工作中心也快照：路线改版换了工位时，历史工单该显示当时的工位。
    #   实时 join route_steps 会把昨天干的活显示到今天的工位上。
    wc_id = Column(BigInteger, comment="执行工作中心ID（快照自 route_steps.wc_id）")
    step_type = Column(String(20), default="production", comment="步骤类型：production/inspect/outsource")

    planned_qty = Column(Integer, default=0, comment="计划数量（快照自工单 planned_qty）")
    input_qty = Column(Integer, default=0, comment="累计投入数量")
    output_qty = Column(Integer, default=0, comment="累计合格产出（该工序）")
    scrap_qty = Column(Integer, default=0, comment="累计报废数量（该工序）")
    report_count = Column(Integer, default=0, comment="报工次数（分批报工的痕迹）")
    status = Column(String(20), default="pending",
                    comment="工序状态: pending/in_progress/completed")

    first_reported_at = Column(DateTime(timezone=True), comment="首次报工时刻")
    last_reported_at = Column(DateTime(timezone=True), comment="最近一次报工时刻")
    # ★ IE 标准必须**快照**，不能分析时实时 join route_steps：
    #   路线改版调了节拍，三个月前的工单不该被新标准重判一次（与 operation_code /
    #   wc_id 快照同一个道理）。NULL = 下达时该工序未配置标准 → 分析判「未判」。
    takt_target_min = Column(Float, comment="下达时快照的 IE 目标节拍(分钟/件)")
    transit_limit_min = Column(Float, comment="下达时快照的 IE 过站时效上限(分钟)")
    # 归属组织（数据范围过滤用）：取工单的 org_id，不是操作人的 ——
    # 这一行的"归属"由它属于哪张工单决定，跟谁报的无关（与 work_reports
    # 取报工人组织是**相反**的口径，两处不要统一）。
    org_id = Column(BigInteger, comment="归属组织ID（数据范围过滤用，取工单归属）")

    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "work_order_id", "step_seq",
                         name="uq_wo_step_tenant_wo_seq"),
        # 工序任务台的主查询是"某个工位还有哪些活没干" —— 靠这条索引命中。
        Index("ix_wo_step_tenant_wc_status", "tenant_id", "wc_id", "status"),
        # 工单详情页展开工序 / 下达时幂等判重走这条。
        Index("ix_wo_step_tenant_wo", "tenant_id", "work_order_id"),
    )


# ── M02 BOM 版本锁定 ────────────────────────────────────────────────


class ProductBom(Base):
    """产品 BOM 物料清单表"""
    __tablename__ = "product_bom"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    product_id = Column(BigInteger, nullable=False, comment="关联产品ID")
    material_code = Column(String(100), nullable=False, comment="物料编码")
    material_name = Column(String(200), nullable=False, comment="物料名称")
    qty_per_unit = Column(Float, default=1, comment="单件用量")
    unit = Column(String(20), nullable=False, comment="单位")
    material_type = Column(String(50), default="raw", comment="类型: raw/semi/finished")
    scrap_rate = Column(Float, default=0, comment="损耗率(%)")
    issue_operation_seq = Column(String(50), comment="投料工序序号")
    is_key_material = Column(Boolean, default=False, comment="关键物料标记")
    version = Column(Integer, default=1, comment="BOM 版本号")
    effective_from = Column(Date, comment="生效日期")
    is_active = Column(Boolean, default=True, comment="是否激活")
    remark = Column(Text, comment="备注")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class BomSnapshot(Base):
    """BOM 快照表（工单下达时生成）"""
    __tablename__ = "bom_snapshots"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    work_order_id = Column(BigInteger, nullable=False, comment="工单ID")
    bom_version = Column(Integer, default=1, comment="快照时的 BOM 版本")
    snapshot_data = Column(Text, comment="BOM快照内容（物料清单 JSON）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
