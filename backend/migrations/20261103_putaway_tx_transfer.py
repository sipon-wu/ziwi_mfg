#!/usr/bin/env python3
"""把「上架确认」写出的库存流水从 receipt 改判为 transfer（存量数据，幂等）。

背景
----
`ReceiptService.store_item`（`app/services/wms_service.py` 上架确认分支）把
**待检区 → 正式库位** 这条库内移库的流水写成了 `transaction_type='receipt'`。
于是同一批货在流水上出现两条「入库」：

- 收货登记：receipt  +100（from_location_id = NULL，待检区入账）
- 上架确认：receipt  +100（from_location_id = 待检区，转正式库位）

而 inventory 上只加了 100 —— 按类型汇总入库量直接翻倍
（实测：某物料 Σquantity=170，现存量=70）。

同时 `/wms/transfers` 端点只查 `transaction_type='transfer'`
（`app/api/wms.py`），上架移库在本该看到它的页面里根本不可见。
同模块的库内移库（`wms_service.py` 调拨分支）本来就写 transfer，
两处语义一致才算闭环。

代码已改为写 transfer，本迁移负责把**已写错的历史行**改判过来。

判别条件（只认移库腿，绝不误伤真入库）
----------------------------------------
`transaction_type='receipt' AND from_location_id IS NOT NULL`

真入库的 from_location_id 恒为 NULL（收货登记是「无来源 → 待检区」，
代码里显式写 `"from_location_id": None`），所以这个条件精确命中移库腿。

设计约束
--------
- 幂等：重复执行只会命中 0 行。
- 失败不阻断部署。
- 不影响库存数量（只改类型字段），回滚只需把条件反过来再 UPDATE 一次。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261103_putaway_tx_transfer.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()

    async with engine.begin() as conn:
        row = (await conn.execute(text(
            "SELECT count(*) FROM inventory_transactions "
            "WHERE transaction_type = 'receipt' "
            "AND from_location_id IS NOT NULL"))).fetchone()
        n = row[0] if row else 0
        if not n:
            print("[skip] 无需改判（上架移库已是 transfer，或库内无此类历史行）")
            return False

        print(f"[apply] 改判 {n} 条上架移库流水 receipt -> transfer")
        await conn.execute(text(
            "UPDATE inventory_transactions SET transaction_type = 'transfer' "
            "WHERE transaction_type = 'receipt' "
            "AND from_location_id IS NOT NULL"))
    return True


if __name__ == "__main__":
    asyncio.run(apply())
    sys.exit(0)
