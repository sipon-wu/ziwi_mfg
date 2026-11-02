from sqlalchemy import (
    Column, BigInteger, String, Integer, Boolean, Text, DateTime, Numeric,
    UniqueConstraint,
)
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE


class QcPointConfig(Base):
    __tablename__ = "qc_point_config"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
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

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    order_no = Column(String(100), nullable=False)
    order_type = Column(String(20), nullable=False, comment="first/inspection/spot_check")
    work_order_id = Column(BigInteger)
    process_id = Column(BigInteger)
    material_id = Column(BigInteger)
    # ★ 来料检验（IQC）来源：指向 receipt_order_items.id。
    # 加这一列之前，检验单只有 work_order_id/process_id/material_id，
    # 判定结果无处回写 → "判定不合格却仍可上架"（scenario-verification P0-1）。
    receipt_item_id = Column(BigInteger, comment="来料检验来源：receipt_order_items.id")
    # ★ G-E4 试产检验来源：trial_orders.id。
    # 加这一列之前，试产检验只能靠 order_type 字符串"猜"是试产的，检验单与
    # 试产单之间没有任何硬链 —— 判定不合格自动开的 NCR 挂不回试产项目，
    # 评审会上问"这是哪个试产的失败"答不出来；也没法把试产 NCR 从量产
    # 不良率里干净地摘出去。
    trial_order_id = Column(BigInteger, comment="试产检验来源：trial_orders.id")
    qc_point_id = Column(BigInteger, comment="FK to qc_point_config.id")
    # ★ 本单依据的检验标准（inspection_standard.id）。
    #   加这一列之前，``inspection_item`` 只挂 standard_id、``qc_point_config``
    #   只挂 material_id/process_id —— 三者之间**没有任何 JOIN 路径**能从一张
    #   检验单走到"本单应检项"。前端只能拉"全站前 100 个检验项"，
    #   超过 100 个检验项的租户会**静默截断**（该测的项看不到）。
    #   NULL 合法（历史单 / 口头检验），此时 checklist 端点显式返回 degraded=true。
    standard_id = Column(BigInteger, comment="本单依据的检验标准ID（NULL=未挂标准）")
    org_id = Column(BigInteger, comment="归属组织ID（数据范围过滤用）")
    inspector_id = Column(BigInteger)
    result = Column(String(10), comment="ACC/REJ/UAI")
    judge_at = Column(DateTime(timezone=True))
    remark = Column(Text)
    # ── D-S7 抽样方案（GB/T 2828.1）───────────────────────────
    # 没有这几列之前，"抽检"只能靠检验员口头决定抽几个、允收几个：
    # 同一批货两个人抽能得出相反结论，且事后无法追溯依据。
    # 落库的意义是**判定可复算**：样本量与 Ac/Re 写在单子上，
    # 谁都能拿"批量 + AQL + 检验水平"再算一遍对得上。
    lot_qty = Column(Integer, comment="送检批量（抽样方案的输入）")
    aql = Column(Numeric(6, 3), comment="接收质量限 AQL，如 2.5 表示 2.5%")
    inspection_level = Column(String(10), comment="检验水平 I/II/III/S-1~S-4")
    sample_qty = Column(Integer, comment="应抽样本数")
    ac = Column(Integer, comment="允收数 Ac：不合格数 ≤ Ac 判合格")
    re = Column(Integer, comment="拒收数 Re：不合格数 ≥ Re 判不合格")
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "order_no", name="uq_inspection_order_tenant_no"),
    )


class InspectionResult(Base):
    __tablename__ = "inspection_result"

    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    order_id = Column(BigInteger, nullable=False, comment="FK to inspection_order.id")
    # 归属组织：**继承检验单**，不取录入人组织。子表若用录入人组织，
    # 会出现"品质部录入人 + 生产部检验单"→ 生产部负责人看得到单头看不到明细。
    org_id = Column(BigInteger, comment="归属组织ID（数据范围过滤用，继承检验单 org_id）")
    item_id = Column(BigInteger, comment="FK to inspection_item.id")
    item_name = Column(String(200), comment="冗余字段")
    # spec_value 保持文本：实测为**区间描述**（如 "39.95~40.05"、"0~1.6"），非单值，不能改数值
    spec_value = Column(String(100))
    measured_value = Column(Numeric(18, 6))
    deviation = Column(Numeric(18, 6))
    unit = Column(String(20))
    result = Column(String(10), comment="PASS/FAIL")
    remark = Column(Text)
    # ★ 录入人归属（D-B2）：同一检验单可由多名检验员分工录明细，
    #   没有这一列，出了问题追溯不到是谁录的。
    created_by = Column(BigInteger, comment="录入人 user id")
    # ── 录入通道（C-79）────────────────────────────────────
    # 同一个数，人手抄进 PC 界面、手机扫码录、还是量具直连推上来的，
    # 可信度完全不同：设备直采可以追溯到 calibrate 记录，手抄不行。
    # 不记通道的话，事后争论"这个 8.02 到底是谁录的"只能靠猜。
    source = Column(String(20), default="web",
                    comment="录入通道: web PC / miniapp 小程序 / device 量具直连")
    device_code = Column(String(50), comment="设备编码（source=device 时必填）")
    # 测量时刻与写库时刻分开：设备离线缓存后会补传，两者能差几天。
    # 判定仍按 measured_at 算，否则"先测后判"时序会被写库时间洗掉。
    measured_at = Column(DateTime(timezone=True), comment="实际测量时刻（设备推送可补传）")
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class QualityReport(Base):
    __tablename__ = "quality_report"
    id = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    report_type = Column(String(20), nullable=False, comment="daily/weekly/monthly")
    period = Column(String(20), nullable=False, comment="统计周期, 如 2026-06-13")
    report_data = Column(Text, comment="报表数据 JSON 字符串")
    generated_at = Column(DateTime(timezone=True))
    created_at = Column(DateTime(timezone=True), server_default=func.now())


class NcrRecord(Base):
    """不合格品评审记录（NCR, Non-Conformance Report）——M30 质量域。

    补齐此前的一个结构性缺口：现有 `inspection_order.result`(ACC/REJ/UAI) 与
    `inspection_result.result`(PASS/FAIL) **只有判定、没有处置**，
    REJ 之后的「退货 / 挑选 / 让步接收 / 返工 / 报废 / 索赔」无处记录。

    与 SRM 第四层（SI&D）的关系：本表是 SCAR 的**源头事件与闭环证据**。
    按松耦合纪律②，M40 只订阅本表的领域事件并保存 `source_id` + 快照，
    不跨域 JOIN、不 import 本模块；`need_supplier_action` 仅为标志位，
    由 M40 订阅 `quality.ncr_disposed` 后自行决定是否生成 SCAR。

    设计出处：docs/架构v2-松耦合目标态与迁移路径-2026-10-28.md §3.13
    """
    __tablename__ = "ncr_records"

    # 同 status_log.py：sqlite 方言下 BigInteger 主键不会自增，降级为 Integer
    id = Column(BigInteger().with_variant(Integer, "sqlite"), primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False)
    ncr_no = Column(String(100), nullable=False, comment="不合格单号, 如 NC-202610-0001")

    # 来源（ID + 快照，守松耦合纪律②）
    source_type = Column(String(20), nullable=False, comment="iqc/ipqc/fqc/oqc/lab/manual")
    org_id = Column(BigInteger, comment="归属组织ID（数据范围过滤用）")
    source_id = Column(BigInteger, comment="源头单据ID, 如 inspection_order.id")
    source_no = Column(String(100), comment="源头单号快照")

    # 对象（均为快照字段，避免跨域 JOIN）
    material_id = Column(BigInteger)
    material_name = Column(String(200), comment="物料名称快照")
    supplier_id = Column(BigInteger, comment="供应商ID（来料场景）")
    supplier_name = Column(String(200), comment="供应商名称快照")
    work_order_id = Column(BigInteger, comment="工单ID（制程场景）")
    batch_no = Column(String(100))

    total_qty = Column(Numeric(18, 6), comment="检验/涉及总数, 用于计算不良率")
    defect_qty = Column(Numeric(18, 6), comment="不合格数量")
    defect_type = Column(String(100), comment="缺陷类型（字典）")
    severity = Column(String(20), comment="minor/major/critical")
    defect_desc = Column(Text)

    # 处置结论
    disposition = Column(String(20), comment="return退货/sorting挑选/concession让步接收/rework返工/scrap报废/claim索赔")
    disposition_by = Column(BigInteger)
    disposition_at = Column(DateTime(timezone=True))
    disposition_remark = Column(Text)

    # 状态机：open待评审 → reviewing评审中 → disposed已处置 → closed已关闭；cancelled作废
    status = Column(String(20), nullable=False, server_default="open",
                    comment="open/reviewing/disposed/closed/cancelled")
    need_supplier_action = Column(Boolean, default=False, comment="是否需供方整改；M40 据此生成 SCAR")

    raised_by = Column(BigInteger, comment="提出人")
    raised_at = Column(DateTime(timezone=True), server_default=func.now())
    closed_by = Column(BigInteger)
    closed_at = Column(DateTime(timezone=True))
    remark = Column(Text)
    created_at = Column(DateTime(timezone=True), server_default=func.now())
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # 单号在同租户内唯一：NCR 的 ncr_no 由调用方传入，
        # 重复提交会产生两张同号不合格单，SCAR 追溯直接串号。
        UniqueConstraint("tenant_id", "ncr_no", name="uq_ncr_record_tenant_no"),
    )
