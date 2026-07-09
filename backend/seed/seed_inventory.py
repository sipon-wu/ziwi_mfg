#!/usr/bin/env python3
"""库存种子数据脚本（M07 齐套性检查测试用）。

运行方式：
    python -m seed.seed_inventory

在测试环境中为指定租户预置库存数据。
"""
import asyncio
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import init_db, get_session_factory
from app.repositories.inventory_repo import InventoryRepository


# 默认库存种子数据
DEFAULT_INVENTORY = [
    {"material_code": "RM-001", "material_name": "钢材 Q235", "available_qty": 500, "locked_qty": 50, "unit": "kg"},
    {"material_code": "RM-002", "material_name": "铜线 2.5mm²", "available_qty": 200, "locked_qty": 20, "unit": "m"},
    {"material_code": "RM-003", "material_name": "铝合金型材", "available_qty": 300, "locked_qty": 30, "unit": "kg"},
    {"material_code": "RM-004", "material_name": "塑料粒子 ABS", "available_qty": 1000, "locked_qty": 100, "unit": "kg"},
    {"material_code": "RM-005", "material_name": "电子芯片 STM32", "available_qty": 50, "locked_qty": 5, "unit": "pcs"},
    {"material_code": "SF-001", "material_name": "半成品轴承座", "available_qty": 80, "locked_qty": 10, "unit": "pcs"},
    {"material_code": "SF-002", "material_name": "半成品齿轮", "available_qty": 120, "locked_qty": 15, "unit": "pcs"},
    {"material_code": "PK-001", "material_name": "包装纸箱", "available_qty": 500, "locked_qty": 50, "unit": "pcs"},
    {"material_code": "PK-002", "material_name": "泡沫垫片", "available_qty": 1000, "locked_qty": 100, "unit": "pcs"},
    {"material_code": "CF-001", "material_name": "紧固件 M8螺栓", "available_qty": 2000, "locked_qty": 200, "unit": "pcs"},
]


async def seed_inventory(tenant_id: str = "default", inventory_items: list = None):
    """初始化库存种子数据。

    Args:
        tenant_id: 租户 ID
        inventory_items: 库存数据列表，默认为 DEFAULT_INVENTORY
    """
    await init_db()
    factory = get_session_factory()

    items = inventory_items or DEFAULT_INVENTORY

    async with factory() as session:
        repo = InventoryRepository(session)
        repo.set_tenant_id(tenant_id)

        for item in items:
            data = {**item, "tenant_id": tenant_id}
            await repo.upsert(data)
            print(f"  [seed] {data['material_code']}: {data['material_name']} — {data['available_qty']} {data.get('unit', '')}")

        await session.commit()

    print(f"[seed] 库存种子数据初始化完成，共 {len(items)} 条记录")


if __name__ == "__main__":
    tenant_id = sys.argv[1] if len(sys.argv) > 1 else "default"
    asyncio.run(seed_inventory(tenant_id))
