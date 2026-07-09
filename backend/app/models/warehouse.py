"""M20 仓储管理（WMS）模块 — ORM 模型（15 张表）
从 wms 模块重新导出，保持向后兼容。
"""
from app.models.wms import (
    Warehouse,
    WarehouseZone,
    WarehouseLocation,
    Material,
    Batch,
    Inventory,
    InventoryTransaction,
    ReceiptOrder,
    ReceiptOrderItem,
    IssueOrder,
    IssueOrderItem,
    InventoryCount,
    InventoryCountItem,
    InventoryAlert,
    MaterialRequest,
)

__all__ = [
    "Warehouse", "WarehouseZone", "WarehouseLocation",
    "Material", "Batch",
    "Inventory", "InventoryTransaction",
    "ReceiptOrder", "ReceiptOrderItem",
    "IssueOrder", "IssueOrderItem",
    "InventoryCount", "InventoryCountItem",
    "InventoryAlert",
    "MaterialRequest",
]
