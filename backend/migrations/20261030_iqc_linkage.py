#!/usr/bin/env python3
"""IQC 来料检验闭环：补 `inspection_order.receipt_item_id`（幂等）。

背景
----
``docs/scenario-verification-2026-10-29.md`` §二 P0-1（最低投入最高收益项）。

改造前的事实链：

- ``receipt_order_items.inspection_id`` 字段**存在但全库为 NULL**，
  没有任何代码写入它；
- ``inspection_order`` 只有 ``work_order_id/process_id/material_id``，
  **没有任何字段能指回入库明细**；
- 于是质检员判完 REJ，``judge_order`` 写下一张 NCR 就结束，
  ``receipt_order_items.inspection_status`` 仍靠人工维护，
  ``store_item`` 的闸门只拦 ``disqualified`` 这个手动值 —— 等于不拦。

本迁移只做一件事：给 ``inspection_order`` 加一列 ``receipt_item_id``，
让"检验单 → 入库明细"这条边存在。回写逻辑在
``api/quality.py::judge_order`` 与 ``services/wms_service.py::submit_inspection``。

设计约束
--------
- 幂等：先探测再 ADD COLUMN，可重复运行。
- 不动存量数据：存量检验单该列留 NULL，语义是"非来料检验"。
- 不做 NOT NULL / 外键约束：SQLite 的 ALTER 不支持加约束，
  且历史数据无法回填，两侧一致性由代码保证。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261030_iqc_linkage.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

ADD_COLUMNS = [
    ("inspection_order", "receipt_item_id", "BIGINT"),
]


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    """返回 {列名: 类型}；表不存在返回 {}。

    async 连接下不能走 conn.sync_connection（greenlet_spawn 报错），
    所以直接用 SQL 查元数据。
    """
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
    except Exception as exc:  # 防御：迁移异常不阻断部署
        print(f"[error] 迁移失败（请检查日志，不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
