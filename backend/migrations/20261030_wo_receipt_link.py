#!/usr/bin/env python3
"""完工 → 成品入库：补 `receipt_orders.work_order_id`（幂等）。

背景
----
``docs/scenario-verification-2026-10-29.md`` §二 P0-2。

改造前 ``POST /work-orders/{id}/close`` 只调 ``change_status``，不写任何库存；
``receipt_orders`` 也没有指向工单的列，只能靠 ``source_doc_no`` 字符串弱关联，
SQL 层无法 JOIN 校验"入库量 ≤ 完工量"。

本迁移只加一列，让"生产入库单 → 工单"这条边存在。自动建单逻辑在
``services/production_service.py::_raise_production_receipt``。

设计约束
--------
- 幂等：先探测再 ADD COLUMN。
- 存量数据留 NULL，语义是"非生产入库单"。
- 不加外键约束：SQLite 的 ALTER 不支持，且历史数据无法回填。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261030_wo_receipt_link.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

ADD_COLUMNS = [
    ("receipt_orders", "work_order_id", "BIGINT"),
]


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return {r[1]: (r[2] or "").upper() for r in res}
        res = await conn.execute(text(
            "SELECT column_name, data_type FROM information_schema.columns "
            "WHERE table_name = :t"
        ), {"t": table})
        return {r[0]: (r[1] or "").upper() for r in res}
    except Exception:
        return {}


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        for table, column, ddl in ADD_COLUMNS:
            existing = await _fetch_columns(conn, dialect, table)
            if not existing:
                print(f"[skip] 表 {table} 不存在")
                continue
            if column in existing:
                print(f"[skip] {table}.{column} 已存在 ({existing[column]})")
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl}"))
            print(f"[apply] ALTER TABLE {table} ADD COLUMN {column} {ddl}")
            changes += 1

    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:
        print(f"[error] 迁移失败（请检查日志，不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
