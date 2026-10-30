#!/usr/bin/env python3
"""子表组织归属：给 3 张子表补 `org_id` 并回填（幂等）。

背景
----
``docs/BACKLOG.md`` #B-2。

切强制模式后，数据范围（``ORG_SCOPED_TABLES`` 白名单 + ``{col} IN (...ids)``）
只覆盖 5 张主表。三张高频子表**完全不过滤**：

- ``work_reports``（报工明细）
- ``inspection_result``（检验结果明细）
- ``inventory_transactions``（库存流水）

后果不是"看不到"而是**全看到** —— 带 DEPT / DEPT_CHILD 范围的角色在这三张表上
拿到的是全公司数据。权限看起来切开了，实际漏在这三张表上。

归属规则（写入侧，见各 repo 的 INSERT）
------------------------------------
- ``work_reports``          取**报工人**组织。车间主任要看到"本车间工人报的工"，
                            而不是"本车间被下的工单的报工" —— 工单通常由生产部/计划
                            下达，若按工单归属，车间主任一条报工都看不到。
- ``inspection_result``     继承**检验单** org_id（子查询）。子表若用录入人组织，
                            "品质部录入 + 生产部检验单"会让生产部负责人看得到单头
                            看不到明细。
- ``inventory_transactions``取**操作人**组织（``MultiTenantRepository`` 自动注入）。

本迁移的回填顺序与此一致，避免存量数据与新增数据两套语义。

设计约束
--------
- 幂等：先探测再 ADD COLUMN；回填只写 ``org_id IS NULL`` 的行。
- 不回填出脏值：取不到归属就留 NULL（NULL 落在过滤外，等价于"仅 ALL 范围可见"），
  不做猜测性填充。
- 方言无关：回填用 ``UPDATE ... FROM`` 只有 PG 支持，故统一写成
  ``UPDATE t SET org_id = (SELECT ... WHERE ...)`` 半连接形式，PG/SQLite 都吃。
- 失败不阻断部署。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261030_subtable_org.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

ADD_COLUMNS = [
    ("work_reports", "org_id", "BIGINT"),
    ("inspection_result", "org_id", "BIGINT"),
    ("inventory_transactions", "org_id", "BIGINT"),
]

# 回填：优先"操作人组织"，取不到再退回父单组织（仅 work_reports 有第二跳）
BACKFILL = [
    ("work_reports",
     "UPDATE work_reports SET org_id = ("
     " SELECT u.primary_org_id FROM users u WHERE u.id = work_reports.reporter_id"
     ") WHERE org_id IS NULL AND reporter_id IS NOT NULL"),
    ("work_reports",
     "UPDATE work_reports SET org_id = ("
     " SELECT wo.org_id FROM work_orders wo WHERE wo.id = work_reports.work_order_id"
     ") WHERE org_id IS NULL AND work_order_id IS NOT NULL"),
    ("inspection_result",
     "UPDATE inspection_result SET org_id = ("
     " SELECT io.org_id FROM inspection_order io WHERE io.id = inspection_result.order_id"
     ") WHERE org_id IS NULL AND order_id IS NOT NULL"),
    ("inventory_transactions",
     "UPDATE inventory_transactions SET org_id = ("
     " SELECT u.primary_org_id FROM users u WHERE u.id = inventory_transactions.created_by"
     ") WHERE org_id IS NULL AND created_by IS NOT NULL"),
]


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(f"PRAGMA table_info({table})"))
            return {r[1]: (r[2] or "").upper() for r in res}
        res = await conn.execute(
            text(
                "SELECT column_name, data_type FROM information_schema.columns "
                "WHERE table_name = :t"
            ),
            {"t": table},
        )
        return {r[0]: (r[1] or "").upper() for r in res}
    except Exception:
        return {}


async def _count_null(conn, table: str) -> int:
    try:
        res = await conn.execute(
            text(f"SELECT COUNT(*) FROM {table} WHERE org_id IS NULL")
        )
        return int(res.scalar() or 0)
    except Exception:
        return -1


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        # ① 补列
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

        # ② 回填
        for table, sql in BACKFILL:
            try:
                res = await conn.execute(text(sql))
                n = res.rowcount if res.rowcount is not None and res.rowcount >= 0 else 0
            except Exception as exc:
                print(f"[warn] 回填 {table} 失败，跳过：{exc}")
                continue
            if n:
                print(f"[apply] 回填 {table} {n} 行")
                changes += n
            else:
                print(f"[skip] {table} 无需回填")

        # ③ 报账：还剩多少行没有归属
        for table, _, _ in ADD_COLUMNS:
            left = await _count_null(conn, table)
            if left > 0:
                print(
                    f"[info] {table} 仍有 {left} 行 org_id 为 NULL"
                    f"（取不到归属，按「仅 ALL 范围可见」处理）"
                )

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
