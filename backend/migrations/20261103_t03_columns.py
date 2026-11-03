#!/usr/bin/env python3
"""补 T03 引入的 4 个列（幂等）：差额结案 / 检验标准挂接 / 点检模板。

为什么必须有这个脚本
--------------------
这三个能力（差额结案、检验单挂标准、保养点检模板）在**本地 SQLite 上一切正常**，
一到 staging 就 500 —— 因为本地库是 `create_all` 按最新模型新建的，而 staging 是
**先有表、后有列**：`create_all` 只建表**不补列**，模型里加的列在老库上不存在。

线上实测（本轮部署后立刻炸）：
    18 × column "short_closed" of relation "issue_orders" does not exist
    17 × column "standard_id" of relation "inspection_order" does not exist
出库/发料、检验判定、NCR 处置全部 500。而模型、单测、本地 E2E 全绿 ——
**「测试没红」和「线上能用」之间差的就是这一步。**

列清单（与 `app/models/` 一一对应）
----------------------------------
| 表 | 列 | 类型 | 说明 |
|---|---|---|---|
| issue_orders | short_closed | BOOLEAN NOT NULL DEFAULT false | 差额结案标记 |
| issue_orders | shortage_reason | TEXT | 差额结案原因 |
| inspection_order | standard_id | BIGINT | 本单依据的检验标准 |
| maintenance_plans | checklist_template | JSON | 点检项模板 |

`short_closed` 是 `NOT NULL`，所以必须带 `DEFAULT false` —— 否则老库里的历史行
直接违反非空约束、ALTER 本身失败。**写 `0` 不行**：PG 的 boolean 不认整数字面量。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261103_t03_columns.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# (表, 列, 列定义)。定义直接写方言通吃的形态：
# BIGINT / TEXT / JSON 在 PG 与 SQLite 都合法；BOOLEAN 同理，但默认值要写 false。
COLUMNS = [
    ("issue_orders", "short_closed",
     "BOOLEAN NOT NULL DEFAULT false"),
    ("issue_orders", "shortage_reason", "TEXT"),
    ("inspection_order", "standard_id", "BIGINT"),
    ("maintenance_plans", "checklist_template", "JSON"),
]


async def apply() -> list:
    from sqlalchemy import inspect as sa_inspect
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    added = []

    async with engine.begin() as conn:
        def _tables(sync_conn):
            return set(sa_inspect(sync_conn).get_table_names())

        tables = await conn.run_sync(_tables)

        for table, column, ddl in COLUMNS:
            if table not in tables:
                print(f"[SKIP] 表不存在：{table}")
                continue

            def _cols(sync_conn, t=table):
                return {c["name"] for c in sa_inspect(sync_conn).get_columns(t)}

            cols = await conn.run_sync(_cols)
            if column in cols:
                print(f"[skip] {table}.{column} 已存在")
                continue

            def _add(sync_conn, t=table, c=column, d=ddl):
                sync_conn.execute(text(f"ALTER TABLE {t} ADD COLUMN {c} {d}"))

            await conn.run_sync(_add)
            added.append(f"{table}.{column}")
            print(f"[apply] {table}.{column} {ddl}")

    return added


async def main():
    print("迁移：补 T03 的 4 个列（差额结案 / 检验标准 / 点检模板）")
    try:
        added = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：新增 {len(added)} 列" + (f" {added}" if added else "（全部已存在）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
