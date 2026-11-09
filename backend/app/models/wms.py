"""M20 仓储管理（WMS）模块 — ORM 模型（15 张表）"""
from sqlalchemy import (
    Column, BigInteger, String, Integer, Float, DateTime, Text, Date, Boolean,
    UniqueConstraint, Index, text,
)
from sqlalchemy.sql import func
from app.core.database import Base, PK_TYPE


# ============================================
# 仓库主数据
# ============================================

class Warehouse(Base):
    """仓库"""
    __tablename__ = "warehouses"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    code          = Column(String(64), nullable=False, comment="仓库编码")
    name          = Column(String(128), nullable=False, comment="仓库名称")
    # ★ 值域真源是 `app/core/enums.py::WAREHOUSE_TYPE_LABELS`，不要再把 4 项
    #   抄回注释里 —— 旧注释（raw_material/semi/finished/consumable）就是第二
    #   个真源，它和前端各漏了几个值、和库里 7 个值也对不上。
    type          = Column(String(32), default="raw_material", comment="仓库类型，见 core/enums.py::WAREHOUSE_TYPE_LABELS")
    address       = Column(String(256), comment="地址")
    contact_person = Column(String(64), comment="联系人")
    contact_phone = Column(String(32), comment="联系电话")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class WarehouseZone(Base):
    """库区"""
    __tablename__ = "warehouse_zones"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    zone_code     = Column(String(64), nullable=False, comment="库区编码")
    zone_name     = Column(String(128), comment="库区名称")
    zone_type     = Column(String(32), default="storage", comment="storage/待检/不良品/待发/退货")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


class WarehouseLocation(Base):
    """库位"""
    __tablename__ = "warehouse_locations"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    zone_id       = Column(BigInteger, comment="库区ID")
    location_code = Column(String(64), nullable=False, comment="库位编码")
    location_type = Column(String(32), default="shelf", comment="shelf/floor/cold/area")
    max_capacity  = Column(Float, comment="最大容量")
    current_qty   = Column(Float, default=0, comment="当前占用容量")
    is_active     = Column(Boolean, default=True, comment="启用状态")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 物料主数据
# ============================================

class Material(Base):
    """物料主数据"""
    __tablename__ = "materials"

    id                = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id         = Column(String(50), nullable=False, comment="租户ID")
    code              = Column(String(64), nullable=False, comment="物料编码")
    name              = Column(String(128), nullable=False, comment="物料名称")
    spec              = Column(String(256), comment="规格型号")
    unit              = Column(String(32), nullable=False, comment="计量单位")
    material_type     = Column(String(32), default="raw", comment="raw/semi/finished/consumable/package")
    material_category = Column(String(64), comment="物料分类")
    is_batch_managed  = Column(Boolean, default=False, comment="是否批次管理")
    is_serial_managed = Column(Boolean, default=False, comment="是否序列号管理")
    storage_condition = Column(String(128), comment="存储条件")
    min_stock_qty     = Column(Float, default=0, comment="最低库存量")
    max_stock_qty     = Column(Float, default=0, comment="最高库存量")
    safety_stock_qty  = Column(Float, default=0, comment="安全库存量")
    reorder_point     = Column(Float, default=0, comment="再订货点")
    lead_time_days    = Column(Integer, default=0, comment="采购提前期(天)")
    image_url         = Column(String(256), comment="图片URL")
    is_active         = Column(Boolean, default=True, comment="启用状态")
    pick_strategy     = Column(String(20), default="fifo", comment="拣选策略: fifo/lifo/manual")
    created_at        = Column(DateTime(timezone=True), server_default=func.now())
    updated_at        = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class MaterialSubstitute(Base):
    """物料替代料（B-S6）

    「主料缺了，能不能用别的料顶上」这件事此前**完全没有数据载体**：
    全库无替代料表、无替代逻辑，齐套检查算出缺料就是缺料，界面上只告诉
    计划员"缺 100 个 A"，至于仓库里躺着 500 个能顶替 A 的 B，系统一概不知 ——
    计划员只能靠翻物料表人肉找，找不到就走"强制下发"。

    设计取舍：
    - **只做一级替代，不做多级链**：A→B→C 这种链式替代看着强大，但会出现
      "用 C 顶了 B 导致 B 本身缺料"这类级联副作用，且替代链一长，
      用料追溯就断了（这批次到底用了什么谁也说不清）。真需要多级时
      由计划员显式配一条 A→C 即可，链路始终只有一跳、可追溯。
    - **冗余存 material_code / substitute_code**：BOM 与齐套检查全程按物料
      **编码**走（``available_qty_by_codes`` 也是按编码汇总），存编码才能
      在不 join materials 的情况下直接参与缺料计算（与 inspection_result
      冗余 item_name 同一思路）。
    - **ratio 表示"1 单位替代料可顶多少单位主料"**：替代料规格不同时
      （如 1 卷 100m 替代 1 卷 50m）必须带换算比，否则算出来的
      "够不够"是错的。
    """
    __tablename__ = "material_substitutes"

    id                    = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id             = Column(String(50), nullable=False, comment="租户ID")
    material_id           = Column(BigInteger, nullable=False, comment="主料ID")
    material_code         = Column(String(64), nullable=False, comment="主料编码（冗余，按编码参与缺料计算）")
    substitute_id         = Column(BigInteger, nullable=False, comment="替代料ID")
    substitute_code       = Column(String(64), nullable=False, comment="替代料编码（冗余）")
    substitute_name       = Column(String(128), comment="替代料名称（冗余，展示用）")
    priority              = Column(Integer, default=100, comment="优先级，数字小者优先")
    ratio                 = Column(Float, default=1.0, comment="1 单位替代料可顶多少单位主料")
    is_active             = Column(Boolean, default=True, comment="启用状态")
    remark                = Column(Text, comment="备注（替代条件/工艺约束）")
    created_at            = Column(DateTime(timezone=True), server_default=func.now())
    updated_at            = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())

    __table_args__ = (
        # 同一主料下同一替代料只能配一次；重复配会让"按优先级依次替代"算出双份
        UniqueConstraint("tenant_id", "material_id", "substitute_id",
                         name="uq_material_substitutes_tenant_pair"),
    )


# ============================================
# 批次主数据
# ============================================

class Batch(Base):
    """批次"""
    __tablename__ = "batches"

    id               = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False, comment="租户ID")
    batch_no         = Column(String(64), nullable=False, comment="批次号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    supplier_batch_no = Column(String(64), comment="供应商批次号")
    manufacture_date = Column(Date, comment="生产日期")
    expiry_date      = Column(Date, comment="有效期/到期日")
    status           = Column(String(32), default="active", comment="active/locked/expired/blocked")
    is_locked        = Column(Boolean, default=False, comment="是否锁定")
    lock_reason      = Column(String(256), comment="锁定原因")
    # ── 2026-11-09 B-20：三级码与组套（定子 + 转子 → 合成成品码）────────────
    # `batch_type` 只表达「这个码是哪一级」，不表达命名规则 —— 客户叫 TD/TZ/TC
    # 还是别的，由 `core/trace_code.py` 的前缀模板决定，代码里不许出现字面量。
    # ★ nullable=False 必须同时给 server_default：`default=` 只作用于 ORM 层，
    #   手写迁移 ALTER 出来的列对存量行是 NULL，PG 会直接拒绝 NOT NULL。
    batch_type       = Column(String(16), nullable=False, server_default="raw",
                              comment="码级别：raw 原料码 / wip 部件码 / final 成品码")
    # 组套的父子关系：成品码的 `parent_batch_id` 指向定子码 / 转子码。
    # 定子码与转子码各自只有一行成品码引用它（业务上是一对一），但**不加唯一约束**
    # —— 返修拆解后重新组套是正常场景，硬约束会把返修卡死。
    parent_batch_id  = Column(BigInteger, comment="组套父批次ID（成品码 → 定子码/转子码）")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())

    # 收货入账时按 (物料, 批次号) find_or_create，必须靠唯一约束兜住并发重复。
    # 没有它，同一批货可能建出两条批次记录 → inventory.batch_id 指向不同行，
    # 冻结只锁住其中一条，另一条照样能被拣走（台账 B-9）。
    __table_args__ = (
        UniqueConstraint("tenant_id", "material_id", "batch_no",
                         name="uq_batches_tenant_material_no"),
        # 双向追溯的两个方向都要走索引：成品码展开部件（按 parent 查）、
        # 部件码反查成品（按 id 回看谁挂了我）。SQLAlchemy 2.0 的 CreateTable
        # **不带索引**，所以这条在迁移里必须逐条 CREATE INDEX 补上。
        Index("ix_batches_tenant_parent", "tenant_id", "parent_batch_id"),
    )


# ============================================
# 库存台账
# ============================================

class Inventory(Base):
    """库存台账"""
    __tablename__ = "inventory"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    material_id   = Column(BigInteger, nullable=False, comment="物料ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    location_id   = Column(BigInteger, comment="库位ID")
    batch_id      = Column(BigInteger, comment="批次ID")
    batch_no      = Column(String(64), comment="批号")
    quantity      = Column(Float, default=0, comment="现存量")
    locked_qty    = Column(Float, default=0, comment="锁定数量")
    unit          = Column(String(32), nullable=False, comment="单位")
    last_transaction_at = Column(DateTime(timezone=True), comment="最后交易时间")
    updated_at    = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())


class InventoryTransaction(Base):
    """库存交易流水"""
    __tablename__ = "inventory_transactions"

    id               = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False, comment="租户ID")
    org_id           = Column(BigInteger, comment="归属组织ID（数据范围过滤用，取操作人主组织）")
    transaction_type = Column(String(32), nullable=False, comment="receipt/issue/transfer/adjust/scrap")
    voucher_no       = Column(String(64), nullable=False, comment="物料凭证号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    warehouse_id     = Column(BigInteger, nullable=False, comment="仓库ID")
    from_location_id = Column(BigInteger, comment="源库位ID")
    to_location_id   = Column(BigInteger, comment="目标库位ID")
    batch_id         = Column(BigInteger, comment="批次ID")
    batch_no         = Column(String(64), comment="批号")
    quantity         = Column(Float, nullable=False, comment="数量")
    unit             = Column(String(32), nullable=False, comment="单位")
    unit_price       = Column(Float, comment="单价")
    source_type      = Column(String(32), comment="purchase/production/sale/adjust/scrap/transfer")
    source_doc_no    = Column(String(64), comment="来源单据号")
    reference_type   = Column(String(32), comment="po/wo/so/adjust/stock_move")
    reference_id     = Column(BigInteger, comment="来源单据ID")
    remark           = Column(String(256), comment="备注")
    created_by       = Column(BigInteger, comment="创建人ID")
    created_at       = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 入库单
# ============================================

class ReceiptOrder(Base):
    """入库单"""
    __tablename__ = "receipt_orders"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    receipt_no    = Column(String(64), nullable=False, comment="入库单号")
    receipt_type  = Column(String(32), nullable=False, comment="purchase/生产入库/退货入库/transfer")
    status        = Column(String(32), default="pending", comment="pending/inspecting/partially_stored/stored/cancelled")
    source_type   = Column(String(32), comment="po/wo/return/transfer")
    source_doc_no = Column(String(64), comment="来源单据号")
    # ★ 生产入库来源工单：加这一列之前，"生产入库"只能靠 source_doc_no 字符串
    # 弱关联工单，SQL 层无法 JOIN 校验"入库量 ≤ 完工量"（scenario-verification P0-2）
    work_order_id = Column(BigInteger, comment="生产入库来源工单ID")
    org_id        = Column(BigInteger, comment="归属组织ID（数据范围过滤用）")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    supplier_id   = Column(BigInteger, comment="供应商ID")
    total_qty     = Column(Float, default=0, comment="总数量")
    received_qty  = Column(Float, default=0, comment="已收数量")
    stored_qty    = Column(Float, default=0, comment="已上架数量")
    created_by    = Column(BigInteger, comment="创建人ID")
    checked_by    = Column(BigInteger, comment="质检确认人")
    stored_by     = Column(BigInteger, comment="上架确认人")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), comment="完成时间")

    __table_args__ = (
        # 单号在同租户内唯一。改造前 receipt_no 无任何约束，重复提交/并发
        # 会产出两张同号入库单，库存流水与对账都失去唯一锚点。
        UniqueConstraint("tenant_id", "receipt_no", name="uq_receipt_order_tenant_no"),
    )


class ReceiptOrderItem(Base):
    """入库单明细"""
    __tablename__ = "receipt_order_items"

    id               = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False, comment="租户ID")
    receipt_id       = Column(BigInteger, nullable=False, comment="入库单ID")
    line_no          = Column(Integer, nullable=False, comment="行号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    expected_qty     = Column(Float, default=0, comment="应收数量")
    received_qty     = Column(Float, default=0, comment="实收数量")
    stored_qty       = Column(Float, default=0, comment="已上架数量")
    unit             = Column(String(32), nullable=False, comment="单位")
    batch_no         = Column(String(64), comment="批号")
    location_id      = Column(BigInteger, comment="目标库位ID")
    inspection_status = Column(String(32), default="pending", comment="pending/待检/qualified/disqualified")
    inspection_id    = Column(BigInteger, comment="关联IQC检验单ID")
    remark           = Column(String(256), comment="备注")


# ============================================
# 出库单
# ============================================

class IssueOrder(Base):
    """出库单"""
    __tablename__ = "issue_orders"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    issue_no      = Column(String(64), nullable=False, comment="出库单号")
    issue_type    = Column(String(32), nullable=False, comment="production/销售出库/scrap/transfer")
    status        = Column(String(32), default="pending", comment="pending/picking/partially_issued/issued/cancelled")
    source_type   = Column(String(32), comment="wo/so/scrap/transfer")
    source_doc_no = Column(String(64), comment="来源单据号")
    # ★ 领料来源工单：与 receipt_orders.work_order_id 对称。改造前领料单只有
    #   一个 source_doc_no 字符串挂工单号，批次追溯只能靠字符串 JOIN ——
    #   工单号改了、或前端没传，追溯链就断，召回查不出"这批原料用在哪台机上"。
    work_order_id = Column(BigInteger, comment="领料来源工单ID")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    department_id = Column(BigInteger, comment="领用部门ID")
    recipient     = Column(String(64), comment="领料人")
    total_qty     = Column(Float, default=0, comment="总数量")
    issued_qty    = Column(Float, default=0, comment="已发数量")
    created_by    = Column(BigInteger, comment="创建人ID")
    issued_by     = Column(BigInteger, comment="出库确认人")
    # ★ 差额结案（状态机的出口）：``partially_issued`` 此前是一个**无出口状态** ——
    #   行欠发 8 个之后，唯一的出口是"把 8 个补齐"，而现场缺料就是缺料，
    #   于是单据永远停在 partially_issued，列表上永久堆在最前面。
    #   ``short_closed=true`` 表示"就发这么多、差额结案"，与"发齐了"在数据上可区分，
    #   事后能算出"这个月有多少张单是欠发结案的"。
    #   ★PG 严格类型：代码里写 ``False`` 不写 0；默认值走 **DB 侧**
    #   ``server_default=text("false")`` 而不是 Python 侧 ``default=False`` ——
    #   后者对裸 SQL INSERT 不生效（不写列就落 NULL，而本列 NOT NULL），
    #   而且会被 ``scripts/check_insert_defaults.py`` 判成"固定列清单漏写"。
    #   写 0 会让新库 create_all 在 PG 上直接失败。
    short_closed  = Column(Boolean, nullable=False,
                           server_default=text("false"),
                           comment="是否差额结案（true=欠发结案，非发齐）")
    shortage_reason = Column(Text, comment="差额结案原因（缺料/客户改单/…）")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), comment="完成时间")

    __table_args__ = (
        UniqueConstraint("tenant_id", "issue_no", name="uq_issue_order_tenant_no"),
    )


class IssueOrderItem(Base):
    """出库单明细"""
    __tablename__ = "issue_order_items"

    id              = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id       = Column(String(50), nullable=False, comment="租户ID")
    issue_id        = Column(BigInteger, nullable=False, comment="出库单ID")
    line_no         = Column(Integer, nullable=False, comment="行号")
    material_id     = Column(BigInteger, nullable=False, comment="物料ID")
    required_qty    = Column(Float, default=0, comment="需求数量")
    issued_qty      = Column(Float, default=0, comment="实发数量")
    unit            = Column(String(32), nullable=False, comment="单位")
    batch_no        = Column(String(64), comment="批号")
    from_location_id = Column(BigInteger, comment="源库位ID")
    pick_status     = Column(String(32), default="pending", comment="pending/picked")
    remark          = Column(String(256), comment="备注")


# ============================================
# 盘点单
# ============================================

class InventoryCount(Base):
    """盘点单"""
    __tablename__ = "inventory_counts"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    count_no      = Column(String(64), nullable=False, comment="盘点单号")
    count_type    = Column(String(32), nullable=False, comment="full/cycle/spot")
    status        = Column(String(32), default="draft", comment="draft/in_progress/completed/adjusted/closed")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    zone_id       = Column(BigInteger, comment="库区ID")
    count_date    = Column(Date, nullable=False, comment="盘点日期")
    total_items   = Column(Integer, default=0, comment="总物料数")
    counted_items = Column(Integer, default=0, comment="已盘物料数")
    diff_items    = Column(Integer, default=0, comment="差异物料数")
    created_by    = Column(BigInteger, comment="创建人ID")
    counted_by    = Column(BigInteger, comment="盘点人ID")
    adjusted_by   = Column(BigInteger, comment="调整人ID")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True), comment="完成时间")
    adjusted_at   = Column(DateTime(timezone=True), comment="调整时间")


class InventoryCountItem(Base):
    """盘点明细"""
    __tablename__ = "inventory_count_items"

    id          = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id   = Column(String(50), nullable=False, comment="租户ID")
    count_id    = Column(BigInteger, nullable=False, comment="盘点单ID")
    material_id = Column(BigInteger, nullable=False, comment="物料ID")
    location_id = Column(BigInteger, comment="库位ID")
    batch_no    = Column(String(64), comment="批号")
    system_qty  = Column(Float, default=0, comment="系统账面数量")
    count_qty   = Column(Float, comment="实盘数量")
    diff_qty    = Column(Float, comment="差异数量")
    diff_reason = Column(String(128), comment="差异原因")
    status      = Column(String(32), default="pending", comment="pending/counted/confirmed")
    remark      = Column(String(256), comment="备注")


# ============================================
# 库存预警
# ============================================

class InventoryAlert(Base):
    """库存预警记录"""
    __tablename__ = "inventory_alerts"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    alert_type    = Column(String(32), nullable=False, comment="min_stock/max_stock/safety_stock/slow_moving/expiry")
    material_id   = Column(BigInteger, nullable=False, comment="物料ID")
    warehouse_id  = Column(BigInteger, comment="仓库ID")
    current_qty   = Column(Float, default=0, comment="当前库存")
    threshold_qty = Column(Float, default=0, comment="阈值")
    status        = Column(String(32), default="open", comment="open/acknowledged/resolved")
    alert_message = Column(String(256), comment="预警消息")
    resolved_by   = Column(BigInteger, comment="解决人ID")
    resolved_at   = Column(DateTime(timezone=True), comment="解决时间")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())


# ============================================
# 领料申请单
# ============================================

class MaterialRequest(Base):
    """领料申请单"""
    __tablename__ = "material_requests"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    request_no    = Column(String(64), nullable=False, comment="领料申请单号")
    work_order_id = Column(BigInteger, nullable=False, comment="关联工单ID")
    status        = Column(String(32), default="pending", comment="pending/approved/partially_issued/issued/cancelled")
    warehouse_id  = Column(BigInteger, nullable=False, comment="仓库ID")
    department_id = Column(BigInteger, comment="部门ID")
    requester     = Column(BigInteger, comment="申请人ID")
    approved_by   = Column(BigInteger, comment="审批人ID")
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    approved_at   = Column(DateTime(timezone=True), comment="审批时间")


class MaterialRequestItem(Base):
    """领料申请明细"""
    __tablename__ = "material_request_items"

    id               = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id        = Column(String(50), nullable=False, comment="租户ID")
    request_id       = Column(BigInteger, nullable=False, comment="申请单ID")
    line_no          = Column(Integer, nullable=False, comment="行号")
    material_id      = Column(BigInteger, nullable=False, comment="物料ID")
    required_qty     = Column(Float, default=0, comment="需求数量")
    approved_qty     = Column(Float, comment="核准数量")
    issued_qty       = Column(Float, default=0, comment="已发数量")
    unit             = Column(String(32), nullable=False, comment="单位")
    operation_seq    = Column(Integer, comment="投料工序")
    requirement_date = Column(Date, comment="需求日期")
    remark           = Column(String(256), comment="备注")
