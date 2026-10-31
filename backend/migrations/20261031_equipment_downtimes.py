#!/usr/bin/env python3
"""创建 `equipment_downtimes` 表（幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #B-12：设备只有 ``status`` 一个字段 —— 能知道
"此刻故障"，但

- 不知道**从什么时候开始、停了多久** → OEE 可用率的停机时间没有来源；
- 不知道**影响哪张工单** → 计划完工时间不会顺延，排产表是张假表；
- 故障处理完不留历史 → 反复出问题的设备看不出来。

本迁移把表的创建落成脚本。新库本来由 ``create_all`` 建（模型已注册），
这里是为了**已部署的库**能单独补上，且不依赖部署顺序。

设计约束
--------
- 幂等：``Table.create(checkfirst=True)``，已有表就跳过。
- 方言自适应：走 SQLAlchemy 的 DDL，不写死 SQLite/PG 的类型差异。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_equipment_downtimes.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> int:
    from sqlalchemy import inspect

    from app.core.database import get_engine
    from app.models.tpm import EquipmentDowntime

    engine = get_engine()
    table = EquipmentDowntime.__table__
    async with engine.begin() as conn:
        # 异步连接下不能用 table.exists()（Table 没这个方法），
        # 也不能访问 conn.sync_connection —— 用 run_sync 交给同步 inspector
        exists = await conn.run_sync(lambda c: inspect(c).has_table(table.name))
        if exists:
            print(f"[skip] 表 {table.name} 已存在")
        else:
            await conn.run_sync(lambda c: table.create(c, checkfirst=True))
            print(f"[apply] CREATE TABLE {table.name}")
    await engine.dispose()
    return 0 if exists else 1


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
