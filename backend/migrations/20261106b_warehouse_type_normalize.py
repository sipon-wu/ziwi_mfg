#!/usr/bin/env python3
"""把 `warehouses.type` 的历史别名归一成规范值（幂等）。

## 为什么必须归一

`warehouses.type` 的声明域写在模型列注释里（`raw_material/semi/finished/
consumable`），但**从来没有一处校验**，前端另有一份 4 项硬编码字典。
实测两边都漏，库里有 7 个值：

    raw_material 24 · line_side 3 · finished 2 · wip 1 · spare_parts 1
    raw 1 · finished_goods 1        （2026-11-06 本地实测）

其中 `raw` / `wip` / `finished_goods` 是别名，和
`raw_material` / `semi` / `finished` 指的是同一件事。

危害不是不好看，而是**按类型找仓的代码会静默找不到**：
`production_service` 完工入库要取 `type='finished'` 的仓，若某租户建的仓是
`finished_goods`，那就是"没有成品仓" —— 半成品与成品混仓，全程不报错。
仓储报表按 type 分组统计也会把同一类仓拆成两行。

`line_side`（线边仓）与 `spare_parts`（备件仓）**不归一**：它们是不同的
物理区域，语义不能合并 —— 已经作为合法值纳入 `WAREHOUSE_TYPE_LABELS`。

## 不擅自改未知值

映射表只认 `WAREHOUSE_TYPE_ALIASES` 里登记过的别名。域外且非别名的值
（比如哪天有人手工塞了个 `abc`）**只打印、不改** —— 改成什么得由业务定，
脚本无权替人猜。这类值同时也是接口层校验要挡住的。

## 方言

`UPDATE ... WHERE` 在 PG/SQLite 都合法，不分支。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261106b_warehouse_type_normalize.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TABLE = "warehouses"


async def apply() -> str:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine
    from app.core.enums import (
        WAREHOUSE_TYPE_ALIASES,
        WAREHOUSE_TYPE_LABELS,
    )

    engine = get_engine()
    lines: list[str] = []

    async with engine.begin() as conn:
        def _tables(sync_conn):
            return set(sa_inspect(sync_conn).get_table_names())

        if TABLE not in await conn.run_sync(_tables):
            return "表不存在，跳过"

        before = dict((await conn.execute(text(
            f"SELECT type, COUNT(*) FROM {TABLE} GROUP BY type"
        ))).fetchall())

        # 1) 别名归一
        for old, new in WAREHOUSE_TYPE_ALIASES.items():
            n = before.get(old) or 0
            if not n:
                continue
            await conn.execute(
                text(f"UPDATE {TABLE} SET type = :new WHERE type = :old"),
                {"new": new, "old": old},
            )
            lines.append(f"  {old} → {new}：{n} 行")

        # 2) 域外未知值：只报告
        after = dict((await conn.execute(text(
            f"SELECT type, COUNT(*) FROM {TABLE} GROUP BY type"
        ))).fetchall())
        unknown = {k: v for k, v in after.items()
                   if k not in WAREHOUSE_TYPE_LABELS}
        if unknown:
            print("[STOP] 仍有值域外的仓库类型（未改动，需业务确认后再定）：")
            for k, v in unknown.items():
                print(f"       type={k!r} 共 {v} 行")
            lines.append(f"  域外值 {len(unknown)} 种，已保留待人工确认")

        if not lines:
            return f"无需归一（当前 {len(after)} 种类型均已在值域内或为合法值）"
        return "\n".join(lines)


async def main():
    print("迁移：warehouses.type 别名归一")
    try:
        result = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：\n{result}" if "\n" in result else f"完成：{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
