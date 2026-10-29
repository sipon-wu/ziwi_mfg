#!/usr/bin/env python3
"""S3：建 `organizations` 组织树表 + 给受数据范围约束的业务表补 `org_id`（幂等、方言无关）。

背景
----
`user_organizations.org_id` 自 B7 起就"指向 organizations.id"，但该表从未建立
（`app/api/roles.py` 原注释自陈"本轮整个 org 树链路未建表"）。后果：
`roles.scope` 的 DEPT / DEPT_CHILD 无承载点，数据范围无法落地。

本次同时补齐数据范围所需列：`work_orders` / `inspection_order` / `ncr_records` /
`receipt_orders` 加 `org_id`（`issue_orders` 复用已有 `department_id`，不重复加）。

设计约束
--------
- 幂等：has_table / information_schema 双重探测，可重复运行。
- 方言无关：建表走 metadata.create_all；加列走 ``ALTER TABLE ADD COLUMN``
  （SQLite 3.35+ 与 PG 均支持，且列可空、无默认值，不需要重建表）。
- 防御：异常只打印不抛，不阻断部署。
- **不建 user_organizations.org_id 外键**：存量数据可能有孤儿 org_id，
  加外键会让迁移失败。完整性由服务层保证（删除组织前校验成员归属）。

用法
----
    python backend/migrations/20261029_organizations.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# 需要补 org_id 的业务表（issue_orders 已有 department_id，不在此列）
ORG_ID_TABLES = (
    "work_orders",
    "inspection_order",
    "ncr_records",
    "receipt_orders",
)


async def _table_exists(conn, name: str) -> bool:
    def _check(sync_conn):
        return sync_conn.dialect.has_table(sync_conn, name)
    return await conn.run_sync(_check)


async def _column_exists(conn, table: str, column: str) -> bool:
    """方言无关的列探测。必须用 SQL 查，不能碰 conn.sync_connection（async 下会炸）。"""
    from sqlalchemy import text
    dialect = conn.dialect.name
    if dialect == "sqlite":
        rows = await conn.execute(text(f"PRAGMA table_info({table})"))
        return any(r[1] == column for r in rows.fetchall())
    rows = await conn.execute(text(
        "SELECT column_name FROM information_schema.columns "
        "WHERE table_name = :t AND column_name = :c"
    ), {"t": table, "c": column})
    return rows.fetchone() is not None


async def apply() -> int:
    from sqlalchemy import text
    from app.core.database import Base, get_engine
    from app.models.organization import Organization  # noqa: F401  注册进 metadata

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        # ── 1. 建 organizations 表 ──
        if await _table_exists(conn, "organizations"):
            print(f"[skip] 表 organizations 已存在（{dialect}）")
        else:
            await conn.run_sync(
                lambda sync_conn: Base.metadata.create_all(
                    sync_conn, tables=[Organization.__table__], checkfirst=True
                )
            )
            print(f"[apply] CREATE TABLE organizations（{dialect}）")
            changes += 1

        # ── 2. 给业务表补 org_id ──
        for table in ORG_ID_TABLES:
            if not await _table_exists(conn, table):
                print(f"[skip] 表 {table} 不存在，跳过加列")
                continue
            if await _column_exists(conn, table, "org_id"):
                print(f"[skip] {table}.org_id 已存在")
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN org_id BIGINT"))
            print(f"[apply] ALTER TABLE {table} ADD COLUMN org_id")
            changes += 1

        # ── 3. 索引：数据范围过滤会按 org_id 走 WHERE ──
        for table in ORG_ID_TABLES:
            if not await _table_exists(conn, table):
                continue
            idx = f"ix_{table}_org"
            try:
                await conn.execute(text(
                    f"CREATE INDEX IF NOT EXISTS {idx} ON {table} (tenant_id, org_id)"
                ))
                print(f"[apply] CREATE INDEX {idx}")
            except Exception as exc:
                print(f"[warn] 索引 {idx} 创建失败（不影响功能）: {exc}")

    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处结构变更")
    except Exception as exc:  # 防御：迁移异常不阻断部署
        print(f"[error] 迁移失败（请检查日志，不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
