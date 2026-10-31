"""客诉与召回（M03 质量域）—— 台账 C-37。

X6 的完整链路是「客诉 → NCR → 批次追溯 → 召回」，追溯部分已由
``app/services/trace_service.py`` 打通；本文件补上两个**单据载体**：

- ``customer_complaints``：客诉单。改造前系统里根本没有"客诉"这个概念，
  客户打电话来只能记在 Excel 或微信里，与 NCR、批次、召回全无线；
- ``recall_orders`` / ``recall_order_items``：召回单。光有追溯结果没用 ——
  "同批还有多少在库里"必须落成一张可执行、可跟踪的单据，并且**锁住批次**，
  否则证物还在正常拣选。

设计取舍
--------
- 客户主数据不存在（台账 B-11），客诉只存 ``customer_name`` 快照，不做外键。
  这也是召回"只能锁批次、不能生成客户通知清单"的原因，属已知边界。
- 客诉状态机刻意扁平：``open → investigating → ncr_raised → closed``。
  客诉处理的实质动作是"开 NCR 去查"，不是在自己的状态机里绕圈。
"""
from sqlalchemy import (
    BigInteger, Boolean, Column, DateTime, Float, Integer, String, Text,
    UniqueConstraint,
)
from sqlalchemy.sql import func

from app.core.database import Base, PK_TYPE


class CustomerComplaint(Base):
    """客诉单"""
    __tablename__ = "customer_complaints"

    id             = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id      = Column(String(50), nullable=False, comment="租户ID")
    org_id         = Column(BigInteger, comment="归属组织ID（数据范围过滤用）")
    complaint_no   = Column(String(64), nullable=False, comment="客诉单号 CC-YYYYMMDD-NNNN")

    # 客户（无客户主数据，只存快照）
    customer_name  = Column(String(200), nullable=False, comment="客户名称快照")
    customer_contact = Column(String(100), comment="联系人/电话")

    # 投诉对象（快照，避免跨域 JOIN）
    product_code   = Column(String(64), comment="产品编码")
    product_name   = Column(String(200), comment="产品名称")
    batch_no       = Column(String(64), comment="客诉批号 —— 追溯的锚点")
    complaint_qty  = Column(Float, comment="涉及数量")

    complaint_type = Column(String(32), comment="外观/功能/包装/交付/其他")
    severity       = Column(String(20), default="major", comment="minor/major/critical")
    source_channel = Column(String(32), comment="phone/email/wechat/visit")
    description    = Column(Text, comment="问题描述")

    # open → investigating → ncr_raised → closed
    status         = Column(String(20), nullable=False, default="open")
    ncr_id         = Column(BigInteger, comment="关联 NCR（客诉的实质处理入口）")
    recall_id      = Column(BigInteger, comment="关联召回单")
    # 受理时算好的追溯快照（JSON 文本）：那一刻的影响面，后续批次变动不改写它
    trace_snapshot = Column(Text, comment="受理时的追溯快照 JSON")
    trace_summary  = Column(String(256), comment="追溯摘要一句话（列表页直接展示）")

    received_at    = Column(DateTime(timezone=True), server_default=func.now())
    due_at         = Column(DateTime(timezone=True), comment="承诺答复时间")
    closed_at      = Column(DateTime(timezone=True))
    handled_by     = Column(BigInteger, comment="处理人")
    remark         = Column(Text)
    created_at     = Column(DateTime(timezone=True), server_default=func.now())

    __table_args__ = (
        UniqueConstraint("tenant_id", "complaint_no", name="uq_complaint_tenant_no"),
    )


class RecallOrder(Base):
    """召回单（按批次锁定的证物清单）"""
    __tablename__ = "recall_orders"

    id            = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id     = Column(String(50), nullable=False, comment="租户ID")
    org_id        = Column(BigInteger, comment="归属组织ID")
    recall_no     = Column(String(64), nullable=False, comment="召回单号 RC-YYYYMMDD-NNNN")
    complaint_id  = Column(BigInteger, comment="来源客诉ID")
    ncr_id        = Column(BigInteger, comment="来源 NCR ID")
    source_batch_no = Column(String(64), comment="起点批号（追溯的出发点）")

    reason        = Column(Text, comment="召回原因")
    scope         = Column(String(32), default="batch", comment="batch=按批次/product=按产品")
    status        = Column(String(20), nullable=False, default="executing",
                           comment="executing/completed/cancelled")
    batch_count   = Column(Integer, default=0, comment="涉及批次数")
    locked_count  = Column(Integer, default=0, comment="成功冻结的批次数")
    qty_on_hand   = Column(Float, default=0, comment="冻结时在库总量")

    created_by    = Column(BigInteger)
    created_at    = Column(DateTime(timezone=True), server_default=func.now())
    completed_at  = Column(DateTime(timezone=True))
    remark        = Column(Text)

    __table_args__ = (
        UniqueConstraint("tenant_id", "recall_no", name="uq_recall_tenant_no"),
    )


class RecallOrderItem(Base):
    """召回明细：一行一个被锁定的批次"""
    __tablename__ = "recall_order_items"

    id          = Column(PK_TYPE, primary_key=True, autoincrement=True)
    tenant_id   = Column(String(50), nullable=False, comment="租户ID")
    recall_id   = Column(BigInteger, nullable=False, comment="召回单ID")
    batch_no    = Column(String(64), nullable=False, comment="批次号")
    material_id = Column(BigInteger, comment="物料ID")
    qty_on_hand = Column(Float, default=0, comment="冻结时在库数量")
    is_locked   = Column(Boolean, default=False, comment="是否已成功冻结")
    lock_note   = Column(String(256), comment="冻结失败原因 / 已锁定说明")
    remark      = Column(String(256))
