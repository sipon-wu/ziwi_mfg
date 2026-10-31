#!/usr/bin/env python3
"""补齐保养闭环的两条关联（幂等，台账 C-39）。

背景
----
场景 X9「保养到期 → 停机 → 排产调整」此前完全走不通，原因不是某个函数写错，
而是**整条链路上一个环节都没接上**：

- ``maintenance_plans.next_execute_at`` 从来没被写过 → 计划永远不到期；
- 没有"到期扫描 → 生成任务"的代码 → 计划不会变成任务；
- ``maintenance_tasks`` 的 INSERT 丢掉 ``task_no``，也没有 ``plan_id`` →
  任务执行过几次、下次到期日该滚到哪天，全查不出来；
- 任务开工/完成只改 ``status`` → 设备台账不变、没有停机记录、计划原地不动。

本迁移做三件事：

A. ``maintenance_tasks`` 加 ``plan_id``（任务 ← 计划）；
B. ``maintenance_tasks`` 加 ``work_order_id``（保养停机影响的工单，
   用于完工后顺延交期）。工单表没有 ``equipment_id``，无法反查"这台设备在制哪张单"，
   所以只能显式指定 —— 硬猜会把别人的单停掉；
C. 给 ``next_execute_at IS NULL`` 的在用计划补一个到期日（今天 + 一个周期），
   否则这些老计划永远扫不到。默认按 ``cycle_unit`` 算，算不出来就按 30 天。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_maintenance_loop.py
"""
import asyncio
import os
import sys
from datetime import datetime, timedelta, timezone

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def _has_column(conn, table: str, column: str) -> bool:
    from sqlalchemy import inspect

    def _check(sync_conn):
        insp = inspect(sync_conn)
        return any(c["name"] == column for c in insp.get_columns(table))

    return await conn.run_sync(_check)


async def apply() -> int:
    from sqlalchemy import text

    from app.core.database import get_engine
    from app.services.maintenance_service import add_cycle

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        for col in ("plan_id", "work_order_id"):
            if await _has_column(conn, "maintenance_tasks", col):
                print(f"[skip] maintenance_tasks.{col} 已存在")
                continue
            await conn.execute(text(
                f"ALTER TABLE maintenance_tasks ADD COLUMN {col} BIGINT"))
            print(f"[apply] ALTER TABLE maintenance_tasks ADD COLUMN {col}")
            changes += 1

        # 给没排过期的在用计划补一个到期日 —— 不补的话它们永远扫不到
        rows = (await conn.execute(text(
            "SELECT id, cycle_value, cycle_unit FROM maintenance_plans "
            "WHERE status = 'active' AND next_execute_at IS NULL"))).mappings().all()
        now = datetime.now(timezone.utc)
        for row in rows:
            try:
                nxt = add_cycle(now, row["cycle_value"], row["cycle_unit"])
            except Exception:  # noqa: BLE001 —— 周期脏数据不该阻断迁移
                nxt = now + timedelta(days=30)
            await conn.execute(text(
                "UPDATE maintenance_plans SET next_execute_at = :nxt WHERE id = :id"),
                {"nxt": nxt, "id": row["id"]})
        if rows:
            print(f"[apply] 补 next_execute_at：{len(rows)} 张计划")
            changes += len(rows)

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
