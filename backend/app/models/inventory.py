"""M07 齐套性检查 — 临时库存表（Phase 1 过渡方案，待 M20 替换）"""
from sqlalchemy import Column, BigInteger, String, Float, DateTime
from sqlalchemy.sql import func
from app.core.database import Base


class InventoryItem(Base):
    """简化库存表 — 仅包含齐套性检查所需字段。

    Phase 1 过渡方案，M20 仓储模块上线后替换。
    每个物料编码一条记录，记录可用库存和已锁定数量。
    """
    __tablename__ = "inventory_items"

    id = Column(BigInteger, primary_key=True, autoincrement=True)
    tenant_id = Column(String(50), nullable=False, comment="租户ID")
    material_code = Column(String(100), nullable=False, comment="物料编码")
    material_name = Column(String(200), comment="物料名称")
    available_qty = Column(Float, default=0, comment="可用库存数量")
    locked_qty = Column(Float, default=0, comment="已锁定数量")
    unit = Column(String(20), comment="单位")
    updated_at = Column(DateTime(timezone=True), server_default=func.now(), onupdate=func.now())
