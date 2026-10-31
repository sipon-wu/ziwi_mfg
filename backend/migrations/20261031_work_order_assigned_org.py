#!/usr/bin/env python3
"""给 `work_orders` 补 `assigned_org_id` 列（派工班组/部门，场景 C-S2，幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #C-50：工单派工这条链断在两处——
①``work_orders.assignee_id`` 列一直在，但建单/改单接口都没暴露它，也没有
派工端点，派工只能直接改库；②**班组维度连列都没有**，组织树里有
``org_type='team'`` 却无处可挂。

本迁移只补列，不改数据：老工单没有派工记录，`assigned_org_id` 保持 NULL 即是
"未派工"的正确表达，回填任何默认值都是在编造派工事实。

设计约束
--------
- 幂等：先用 ``inspect`` 看列在不在，在就直接返回 0（异步连接下不能用
  ``Table.exists()``，会 greenlet_spawn 报错）。
- 方言无关：SQLite 与 PG 都用 ``ALTER TABLE ... ADD COLUMN BIGINT``。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_work_order_assigned_org.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402


async def _column_exists(conn, table: str, column: str) -> bool:
    def _check(sync_conn):
        cols = [c["name"] for c in sa_inspect(sync_conn).get_columns(table)]
        return column in cols

    return await conn.run_sync(_check)


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        if await _column_exists(conn, "work_orders", "assigned_org_id"):
            print("[skip] work_orders.assigned_org_id 已存在")
        else:
            await conn.execute(
                text("ALTER TABLE work_orders ADD COLUMN assigned_org_id BIGINT")
            )
            print("[apply] 新增 work_orders.assigned_org_id")
            changes += 1
    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
