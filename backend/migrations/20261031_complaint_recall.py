#!/usr/bin/env python3
"""创建客诉与召回三张表（幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #C-37（X6：客诉 → NCR → 批次追溯 → 召回）。
改造前系统里没有"客诉"也没有"召回"：

- 客户投诉只能记在 Excel/微信里，与 NCR、批次、召回全无线；
- 追溯查出"同批还有 200 件在库"，没有任何单据承载这个结论，
  更不会去锁批次 —— 证物照旧可以被正常拣走。

新库由 ``create_all`` 建（模型已注册到 ``models/__init__``），本迁移负责
给**已部署的库**补上，且不依赖部署顺序。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_complaint_recall.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TABLES = ("customer_complaints", "recall_orders", "recall_order_items")


async def apply() -> int:
    from sqlalchemy import inspect

    from app.core.database import get_engine
    from app.models.complaint import (
        CustomerComplaint, RecallOrder, RecallOrderItem)

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        for model in (CustomerComplaint, RecallOrder, RecallOrderItem):
            table = model.__table__
            # 异步连接下不能用 table.exists()，也不能碰 conn.sync_connection
            exists = await conn.run_sync(lambda c, t=table.name: inspect(c).has_table(t))
            if exists:
                print(f"[skip] 表 {table.name} 已存在")
                continue
            await conn.run_sync(lambda c, t=table: t.create(c, checkfirst=True))
            print(f"[apply] CREATE TABLE {table.name}")
            changes += 1
    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:  # noqa: BLE001
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
