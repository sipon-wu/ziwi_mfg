#!/usr/bin/env python3
"""单号唯一约束：给 6 张单据表补 `(tenant_id, xxx_no)` 唯一索引（幂等）。

背景
----
``docs/scenario-verification-2026-10-29.md`` §六「剩余断点」之一。

改造前的事实：``receipt_orders.receipt_no`` / ``issue_orders.issue_no`` /
``work_orders.wo_no`` / ``trial_orders.order_no`` / ``ncr_records.ncr_no`` /
``inspection_order.order_no`` **没有任何唯一约束**。后果不是"报错"，
而是"静默产生两张同号单"：

- 库存流水、对账、追溯全部失去唯一锚点，两张单只能靠 id 区分，
  人一按单号查就查出一堆；
- 前端连点两下提交、脚本重试、并发导入都会命中；
- 等到发现时，数据已经脏了，清理成本远高于当初加一个索引。

为什么带 tenant_id
------------------
``APP-001`` 这种单号在不同租户之间**本来就该允许重复**。只做单列唯一会
把多租户扯死（第二个租户建单直接撞唯一键）。

幂等与安全
----------
- 先探测索引是否存在，再建；
- 建之前先查有没有既存重复：**有重复就跳过该表并打印明细**，不删数据、
  不改数据。宁可让这张表暂时没约束，也不能在部署时替用户决定删哪张单；
- 异常一律不阻断部署（返回 0）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_unique_doc_no.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

# (表, 单号列, 索引名)
UNIQUE_INDEXES = [
    ("work_orders",      "wo_no",      "uq_work_order_tenant_no"),
    ("receipt_orders",   "receipt_no", "uq_receipt_order_tenant_no"),
    ("issue_orders",     "issue_no",   "uq_issue_order_tenant_no"),
    ("trial_orders",     "order_no",   "uq_trial_order_tenant_no"),
    ("ncr_records",      "ncr_no",     "uq_ncr_record_tenant_no"),
    ("inspection_order", "order_no",   "uq_inspection_order_tenant_no"),
]


async def _index_exists(conn, dialect: str, table: str, index: str) -> bool:
    """async 连接下不能走 conn.sync_connection（greenlet_spawn 报错），用 SQL 查。"""
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(f"PRAGMA index_list({table})"))
            return any(r[1] == index for r in res)
        res = await conn.execute(text(
            "SELECT 1 FROM pg_indexes WHERE schemaname = current_schema() "
            "AND tablename = :t AND indexname = :i"
        ), {"t": table, "i": index})
        return res.first() is not None
    except Exception:
        return False


async def _table_exists(conn, dialect: str, table: str) -> bool:
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:t"), {"t": table})
            return res.first() is not None
        res = await conn.execute(text(
            "SELECT 1 FROM information_schema.tables WHERE table_name = :t"), {"t": table})
        return res.first() is not None
    except Exception:
        return False


async def _duplicates(conn, table: str, col: str):
    res = await conn.execute(text(
        f"SELECT tenant_id, {col}, COUNT(*) AS c FROM {table} "
        f"GROUP BY tenant_id, {col} HAVING COUNT(*) > 1 ORDER BY c DESC"
    ))
    return [(r[0], r[1], r[2]) for r in res]


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        for table, col, index in UNIQUE_INDEXES:
            if not await _table_exists(conn, dialect, table):
                print(f"[skip] 表 {table} 不存在")
                continue
            if await _index_exists(conn, dialect, table, index):
                print(f"[skip] 索引 {index} 已存在")
                continue

            dups = await _duplicates(conn, table, col)
            if dups:
                print(f"[skip] {table}.{col} 存在 {len(dups)} 组重复单号，"
                      f"不自动清理，请人工确认后再建索引：")
                for tenant, no, cnt in dups[:10]:
                    print(f"        tenant={tenant} {col}={no} ×{cnt}")
                continue

            await conn.execute(text(
                f"CREATE UNIQUE INDEX {index} ON {table} (tenant_id, {col})"))
            print(f"[apply] CREATE UNIQUE INDEX {index} ON {table} (tenant_id, {col})")
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
