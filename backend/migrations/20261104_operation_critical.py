#!/usr/bin/env python3
"""A+ 关键工序：给 operations 加 is_critical、给 fmea_hierarchies 加 operation_id（幂等）。

为什么必须同时加这两列
----------------------
"PFMEA 发布 → 标记关键工序 → 工艺路线看到"这条链在旧实现里靠**字符串匹配**
（``route_steps.process_name = fmea_hierarchies.label``），三个前提全不成立：

1. ``route_steps`` 根本没有 ``process_name`` / ``product_id`` / ``is_critical``
   这三列（真实列是 ``route_id`` / ``operation_id`` / ``step_seq`` / ``wc_id``）；
2. 产品↔路线绑定表 ``product_routes`` 有表无数据、全项目零读写；
3. ``label`` 是自由文本 —— 实测同一份文档里 ``压装工序`` 与 ``压装`` 并存，而
   工序主数据叫 ``粗车外圆 / 热处理``，两套词表对不上。

所以只能改**结构**，不能改匹配规则：让 FMEA 节点直接存 ``operation_id``（外键），
关键标记存到 ``operations.is_critical``，``route_steps`` 通过它自己的
``operation_id`` 天然继承。整条链不再有一个字符串比较。

列清单（与 ``app/models/`` 一一对应）
------------------------------------
| 表 | 列 | 类型 | 说明 |
|---|---|---|---|
| operations | is_critical | BOOLEAN NOT NULL DEFAULT false | 关键工序标记（PFMEA 发布时写） |
| fmea_hierarchies | operation_id | BIGINT | 关联工序；可空（DFMEA、根节点、失效模式节点都不需要） |

``is_critical`` 的 ``NOT NULL DEFAULT false`` 两个都不能省：

* ``NOT NULL`` —— 下游 ``WHERE is_critical`` 才不用每处都写 ``OR IS NULL``
  （本项目已有 ``is_system`` 可空布尔导致 ``WHERE x = false`` 静默漏行的前科）；
* ``DEFAULT false`` —— 老库 ALTER 时**已有行**必须能拿到值，否则加列当场失败。
  **写 ``0`` 不行**：PG 的 boolean 不认整数字面量。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261104_operation_critical.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# (表, 列, 列定义)。定义用方言通吃的形态：
# BOOLEAN / BIGINT 在 PG 与 SQLite 都合法，默认值写 false 不写 0。
COLUMNS = [
    ("operations", "is_critical", "BOOLEAN NOT NULL DEFAULT false"),
    ("fmea_hierarchies", "operation_id", "BIGINT"),
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
    print("迁移：A+ 关键工序（operations.is_critical / fmea_hierarchies.operation_id）")
    try:
        added = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：新增 {len(added)} 列" + (f" {added}" if added else "（全部已存在）"))
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
