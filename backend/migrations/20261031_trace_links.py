#!/usr/bin/env python3
"""补齐批次追溯的两条 JOIN 边（幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #C-35（X6 客诉 → NCR → 批次追溯 → 召回）：

1. ``issue_orders`` 只有 ``source_doc_no``（工单号字符串）挂工单，没有
   ``work_order_id``。追溯全靠字符串 JOIN，工单号一改、前端漏传，链条当场断；
   而 ``receipt_orders`` 早就补过这一列（P0-2），两边不对称纯属遗漏。
2. 生产入库明细从来没写过 ``batch_no`` → **成品在系统里没有批号**。
   客诉报了批号，库里什么都查不到，追溯与召回都无从下手。

本迁移做三件事：

A. ``issue_orders`` 加 ``work_order_id`` 列；
B. 已存在的领料单按 ``source_doc_no = work_orders.wo_no`` 回填该列；
C. **仅对尚未收货**（``received_qty = 0``）的生产入库明细回填成品批次号
   ``batch_no = wo_no``。已收货的不动 —— 那些入库单的库存已经落账，
   事后改批号会让明细与 ``inventory`` 对不上，属于篡改账面。

设计约束
--------
- 幂等：列已存在则跳过 ALTER，回填条件带 ``IS NULL``。
- 方言无关：只做 ALTER TABLE ADD COLUMN 与 UPDATE，不写 PG/SQLite 专有语法。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_trace_links.py
"""
import asyncio
import os
import sys

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

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        # ── A. issue_orders.work_order_id ──
        if await _has_column(conn, "issue_orders", "work_order_id"):
            print("[skip] issue_orders.work_order_id 已存在")
        else:
            await conn.execute(text(
                "ALTER TABLE issue_orders ADD COLUMN work_order_id BIGINT"))
            print("[apply] ALTER TABLE issue_orders ADD COLUMN work_order_id")
            changes += 1

        # ── B. 回填领料单的工单 id ──
        res = await conn.execute(text(
            "UPDATE issue_orders SET work_order_id = ("
            "  SELECT w.id FROM work_orders w WHERE w.wo_no = issue_orders.source_doc_no"
            ") WHERE work_order_id IS NULL AND source_doc_no IS NOT NULL "
            "AND EXISTS (SELECT 1 FROM work_orders w "
            "            WHERE w.wo_no = issue_orders.source_doc_no)"))
        backfilled = res.rowcount or 0
        print(f"[apply] 回填 issue_orders.work_order_id：{backfilled} 行")
        changes += backfilled

        # ── C. 未收货的生产入库明细补成品批次号 ──
        # 只碰 received_qty = 0 的：已收货的改批号会让明细与库存台账对不上。
        res2 = await conn.execute(text(
            "UPDATE receipt_order_items SET batch_no = ("
            "  SELECT w.wo_no FROM receipt_orders r "
            "  JOIN work_orders w ON w.id = r.work_order_id "
            "  WHERE r.id = receipt_order_items.receipt_id"
            ") WHERE (batch_no IS NULL OR batch_no = '') "
            "AND (received_qty IS NULL OR received_qty = 0) "
            "AND EXISTS (SELECT 1 FROM receipt_orders r "
            "            JOIN work_orders w ON w.id = r.work_order_id "
            "            WHERE r.id = receipt_order_items.receipt_id "
            "              AND r.receipt_type = 'production')"))
        filled = res2.rowcount or 0
        print(f"[apply] 回填生产入库明细成品批次号：{filled} 行")
        changes += filled

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
