#!/usr/bin/env python3
"""把越界的停机类型 `maintenance` 回填到模型声明域内（幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #C-54：``equipment_downtimes.downtime_type`` 模型声明的
取值域是 ``fault/setup/material/plan/other``，而 ``MaintenanceService.start_task``
**写死 ``"maintenance"``** —— 一个不在域里的值。

后果是分类型聚合时凭空多出一个"幽灵分类"，而真正的**计划停机**（plan）反倒
统计不到。等 OEE 可用率、停机 Pareto 这类报表落地时才会暴露，且那时已经攒了
一堆分错类的数据。维修（``task_type='repair'``）的停机同样被记成 maintenance，
把**故障停机**混进计划停机 —— 可用率只会虚高得更难发现。

代码侧已按 ``task_type`` 映射：``repair → fault``，其余（maintenance /
inspection / 周期型）→ ``plan``。本迁移只回填存量：

- 停机原因形如「维修任务 …」→ ``fault``
- 其余 ``maintenance`` → ``plan``

设计约束
--------
- 幂等：只动 ``downtime_type = 'maintenance'`` 的行，二次运行 0 变更。
- 方言无关：纯 UPDATE + LIKE，无函数。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_downtime_type_domain.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        res = await conn.execute(text(
            "UPDATE equipment_downtimes SET downtime_type = 'fault' "
            "WHERE downtime_type = 'maintenance' AND reason LIKE '%维修任务%'"))
        n = res.rowcount or 0
        if n:
            print(f"[apply] 维修停机 maintenance → fault {n} 行")
            changes += n

        res = await conn.execute(text(
            "UPDATE equipment_downtimes SET downtime_type = 'plan' "
            "WHERE downtime_type = 'maintenance'"))
        n = res.rowcount or 0
        if n:
            print(f"[apply] 计划保养停机 maintenance → plan {n} 行")
            changes += n
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
