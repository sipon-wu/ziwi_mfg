#!/usr/bin/env python3
"""给 3 张子表补 `tenant_id` 并回填（幂等）。

背景
----
E-S4 复核（2026-10-31 真实 HTTP 实测）撞出一条**结构性漂移**：

    GET /wms/inventory-counts/{id} → 500
    sqlite3.OperationalError: no such column: ci.tenant_id

``inventory_count_items`` 表里根本没有 ``tenant_id`` 列，而
``InventoryCountItemRepository`` 继承 ``MultiTenantRepository`` —— 基类的
``query()`` 会自动往 SELECT 的 WHERE 里拼 ``<主表别名>.tenant_id = :_tenant_id``。
于是**读明细 100% 报错**，而创建接口返回 200（INSERT 列清单是手写的、不含该列），
看起来像"建成功了只是读不出来"。

同类扫描（把库里所有表过一遍 PRAGMA）发现另外两张也是同一形态：

- ``material_request_items``（领料申请明细，``MaterialRequestItemRepository``）
- ``approval_nodes``（审批节点，``ApprovalRepository``）

两者都是 0 行 —— 不是没坏，是**从来没被真正用过**，坑还没轮到踩。
（另有 permissions / role_permissions / change_log / dictionary_items /
metric_definitions / import_templates 也无该列，但它们是平台全局表，
走 SingleTenantRepository 或本就不带租户语义，不在本次范围。）

为什么是"补列"而不是"把 repo 改成单租户基类"
------------------------------------------
项目约定子表一律带 ``tenant_id``（见 ``receipt_order_items`` /
``issue_order_items``），且已有 ``20261030_subtable_org.py`` 沿这条线走过一遍。
子表不带租户列，既读不了（SELECT 注入失败），也让"按租户归档/清理"这类
运维动作无处下手。补列是与既有约定对齐，不是新造一套规则。

回填只认父单归属，取不到就留 NULL —— 不做猜测性填充。

设计约束
--------
- 幂等：先探测再 ADD COLUMN；回填只写 ``tenant_id IS NULL`` 的行。
- 方言无关：SQLite 与 PG 都用 ``ALTER TABLE ... ADD COLUMN VARCHAR(50)``；
  回填用 ``UPDATE t SET tenant_id = (SELECT ...)`` 半连接形式，
  不用 PG 专有的 ``UPDATE ... FROM``。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261031_subtable_tenant_id.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402
from sqlalchemy import inspect as sa_inspect  # noqa: E402


ADD_COLUMNS = [
    ("inventory_count_items", "tenant_id", "VARCHAR(50)"),
    ("material_request_items", "tenant_id", "VARCHAR(50)"),
    ("approval_nodes", "tenant_id", "VARCHAR(50)"),
    # 补记（C-58）：备件领用上线时又踩到同一形态 —— spare_part_inventories
    # 同样没有该列，读流水直接 no such column。第一次扫描时它 0 行，
    # 归进了"平台/未使用表"而漏掉。**0 行不代表没坏，只代表坑还没轮到踩。**
    ("spare_part_inventories", "tenant_id", "VARCHAR(50)"),
]

# 子表归属一律继承父单：明细不该有自己的租户，跟父单走才不会漂
BACKFILL = [
    ("inventory_count_items",
     "UPDATE inventory_count_items SET tenant_id = ("
     " SELECT c.tenant_id FROM inventory_counts c WHERE c.id = inventory_count_items.count_id"
     ") WHERE tenant_id IS NULL AND count_id IS NOT NULL"),
    ("material_request_items",
     "UPDATE material_request_items SET tenant_id = ("
     " SELECT r.tenant_id FROM material_requests r WHERE r.id = material_request_items.request_id"
     ") WHERE tenant_id IS NULL AND request_id IS NOT NULL"),
    ("approval_nodes",
     "UPDATE approval_nodes SET tenant_id = ("
     " SELECT i.tenant_id FROM approval_instances i WHERE i.id = approval_nodes.approval_id"
     ") WHERE tenant_id IS NULL AND approval_id IS NOT NULL"),
    ("spare_part_inventories",
     "UPDATE spare_part_inventories SET tenant_id = ("
     " SELECT p.tenant_id FROM spare_parts p WHERE p.id = spare_part_inventories.part_id"
     ") WHERE tenant_id IS NULL AND part_id IS NOT NULL"),
]


async def _column_exists(conn, table: str, column: str) -> bool:
    def _check(sync_conn):
        return column in [c["name"] for c in sa_inspect(sync_conn).get_columns(table)]

    return await conn.run_sync(_check)


async def _enforce_not_null(conn, engine, table: str, column: str) -> None:
    """把补出来的列收紧成 NOT NULL，与模型保持一致（否则结构漂移报告恒报 3 处）。

    - PG：直接 ``ALTER COLUMN ... SET NOT NULL``。
    - SQLite：不支持改列可空性，走**建新表 → 拷数据 → 换名**的老办法。
      表结构从模型生成，避免手写 DDL 与模型再次分叉。
    """
    from sqlalchemy.schema import CreateTable
    from app.core.database import Base
    # 元数据是懒注册的：不 import 模型模块，Base.metadata 里查不到这些表
    import app.models.wms  # noqa: F401
    import app.models.approval  # noqa: F401
    import app.models.tpm  # noqa: F401

    dialect = engine.dialect.name
    if dialect != "sqlite":
        await conn.execute(text(f"ALTER TABLE {table} ALTER COLUMN {column} SET NOT NULL"))
        print(f"  · {table}.{column} 已收紧为 NOT NULL")
        return

    tbl = Base.metadata.tables.get(table)
    if tbl is None:
        print(f"  ! 元数据里找不到 {table}，跳过收紧")
        return

    def _old_cols(sync_conn):
        return [c["name"] for c in sa_inspect(sync_conn).get_columns(table)]

    old_cols = await conn.run_sync(_old_cols)
    shared = [c for c in tbl.columns.keys() if c in old_cols]

    ddl = str(CreateTable(tbl).compile(dialect=engine.dialect))
    await conn.execute(text(f"ALTER TABLE {table} RENAME TO {table}__old"))
    await conn.execute(text(ddl))
    await conn.execute(text(
        f"INSERT INTO {table} ({', '.join(shared)}) "
        f"SELECT {', '.join(shared)} FROM {table}__old"))
    await conn.execute(text(f"DROP TABLE {table}__old"))
    print(f"  · {table} 已按模型重建（{column} NOT NULL）")


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    changes = 0
    async with engine.begin() as conn:
        for table, column, coltype in ADD_COLUMNS:
            if await _column_exists(conn, table, column):
                print(f"  · {table}.{column} 已存在，跳过")
                continue
            await conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {coltype}"))
            changes += 1
            print(f"  + {table}.{column} 已添加")

        for table, sql in BACKFILL:
            if not await _column_exists(conn, table, "tenant_id"):
                continue
            res = await conn.execute(text(sql))
            n = res.rowcount or 0
            if n:
                changes += 1
            print(f"  ~ {table} 回填 {n} 行")

        # 补出来的列在 SQLite 上是可空的，与模型的 NOT NULL 不一致 →
        # 结构漂移报告会一直挂着 3 处。这里按方言收紧。
        for table, column, _ in ADD_COLUMNS:
            if not await _column_exists(conn, table, column):
                continue
            await _enforce_not_null(conn, engine, table, column)
            changes += 1

    return changes


async def main():
    print("迁移：子表补 tenant_id（inventory_count_items / material_request_items / approval_nodes）")
    try:
        n = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未完全成功（不阻断）：{e}")
        return 0
    print(f"完成，变更 {n} 处")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
