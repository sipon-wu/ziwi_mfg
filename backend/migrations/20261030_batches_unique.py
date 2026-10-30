#!/usr/bin/env python3
"""批次唯一化 + 存量库存行回填 `batch_id`（幂等）。

背景
----
台账 ``docs/BACKLOG.md`` #B-9：收货时只把 ``batch_no`` 当字符串写进入库明细和
库存行，``batches`` 表里**没有对应记录** —— 实测收货带 ``batch_no=QD-xxx`` 后，
``select * from batches where batch_no='QD-xxx'`` 查不到任何行。

后果是三条链路一起断：
- **冻结**：判 REJ 想锁批次，没有可锁的对象；
- **追溯**：``inventory.batch_id`` 恒为 NULL，批次正反向追溯无从 JOIN；
- **召回**：不知道哪些库存属于问题批次。

（``inventory.batch_no`` 也多半是空的 —— 待检区入账按 ``batch_id IS NULL``
聚合成一行，命中已有行只 UPDATE 数量，收货传的批次号从第二次起就被丢弃。）

本迁移做三件事
--------------
1. **回填批次实体**：把入库明细里出现过的 ``(tenant_id, material_id, batch_no)``
   补进 ``batches``（``status='active'``、``is_locked=0``）。
2. **回填库存行 batch_id**：``inventory`` 里 ``batch_id IS NULL`` 但
   ``batch_no`` 非空的行，指向对应批次。
3. **加唯一索引** ``uq_batches_tenant_material_no``，与 ``models/wms.py`` 的
   ``UniqueConstraint`` 对齐（新库由 ``create_all`` 内联建约束，老库由本迁移补）。
   建索引前去重：同组保留 **id 最小** 的那条，把 ``inventory`` 与
   ``inventory_transactions`` 的 ``batch_id`` 改指到保留者，再删重复行。

设计约束
--------
- **幂等**：回填用 ``NOT EXISTS`` 判重；已有覆盖唯一索引就跳过建索引。
- **方言无关**：不写 ``EXTRACT`` / ``ILIKE`` / ``TIMESTAMP '...'``；
  索引探测按 SQLite ``PRAGMA`` / PG ``pg_indexes`` 分支。
- **不猜批次归属**：只回填 ``batch_no`` 明确非空的行。待检区那些
  ``batch_no`` 也为空的聚合行保持原样 —— 猜错批次比空着更危险。
- 失败不阻断部署（与其它迁移一致）。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261030_batches_unique.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

INDEX_NAME = "uq_batches_tenant_material_no"
INDEX_COLUMNS = ["tenant_id", "material_id", "batch_no"]


async def _has_unique_index(conn, dialect: str) -> bool:
    """batches 表上是否已有覆盖 (tenant_id, material_id, batch_no) 的唯一索引。"""
    try:
        if dialect == "sqlite":
            listed = await conn.execute(text("PRAGMA index_list(batches)"))
            for row in listed:
                # PRAGMA index_list: (seq, name, unique, origin, partial)
                if not row[2]:
                    continue
                info = await conn.execute(text(f"PRAGMA index_info({row[1]})"))
                cols = [r[2] for r in info]
                if cols == INDEX_COLUMNS:
                    return True
            return False
        listed = await conn.execute(
            text("SELECT indexdef FROM pg_indexes WHERE tablename = :t"),
            {"t": "batches"},
        )
        for (ddl,) in listed:
            up = (ddl or "").upper()
            if "UNIQUE" in up and all(c in up for c in INDEX_COLUMNS):
                return True
        return False
    except Exception as exc:
        print(f"[warn] 检查索引失败，按「不存在」处理：{exc}")
        return False


async def _backfill_batches(conn) -> int:
    """把入库明细里出现过的批次补进 batches 表，返回新增行数。

    只处理 ``batch_no`` 非空的明细。``is_locked`` 一律 0 —— 历史上判过 REJ 的
    批次无从判断是哪些，宁可留给人看（台账里已记），不在这里猜。
    """
    dup = await conn.execute(
        text(
            "SELECT r.tenant_id, r.material_id, r.batch_no "
            "FROM receipt_order_items r "
            "WHERE r.batch_no IS NOT NULL AND r.batch_no <> '' "
            "GROUP BY r.tenant_id, r.material_id, r.batch_no"
        )
    )
    rows = [(r[0], r[1], r[2]) for r in dup]
    created = 0
    for tenant_id, material_id, batch_no in rows:
        exists = await conn.execute(
            text(
                "SELECT id FROM batches WHERE tenant_id = :t "
                "AND material_id = :m AND batch_no = :b"
            ),
            {"t": tenant_id, "m": material_id, "b": batch_no},
        )
        if exists.first():
            continue
        await conn.execute(
            text(
                "INSERT INTO batches (tenant_id, batch_no, material_id, "
                "supplier_batch_no, manufacture_date, expiry_date, status, "
                "is_locked, lock_reason) "
                "VALUES (:t, :b, :m, NULL, NULL, NULL, 'active', 0, NULL)"
            ),
            {"t": tenant_id, "m": material_id, "b": batch_no},
        )
        created += 1
    if created:
        print(f"[apply] 补建批次记录 {created} 条（来源：入库明细的 batch_no）")
    return created


async def _backfill_inventory(conn, dialect: str) -> int:
    """库存行 batch_id 为空但 batch_no 有值的，指向对应批次。"""
    res = await conn.execute(
        text(
            "UPDATE inventory SET batch_id = ("
            "  SELECT b.id FROM batches b "
            "  WHERE b.tenant_id = inventory.tenant_id "
            "    AND b.material_id = inventory.material_id "
            "    AND b.batch_no = inventory.batch_no"
            ") WHERE batch_id IS NULL "
            "  AND batch_no IS NOT NULL AND batch_no <> '' "
            "  AND EXISTS (SELECT 1 FROM batches b "
            "              WHERE b.tenant_id = inventory.tenant_id "
            "                AND b.material_id = inventory.material_id "
            "                AND b.batch_no = inventory.batch_no)"
        )
    )
    n = res.rowcount if res.rowcount and res.rowcount > 0 else 0
    if n:
        print(f"[apply] 回填 inventory.batch_id {n} 行")
    return n


async def _dedupe(conn) -> int:
    """同 (tenant_id, material_id, batch_no) 只留 id 最小的一条。"""
    dup = await conn.execute(
        text(
            "SELECT tenant_id, material_id, batch_no FROM batches "
            "GROUP BY tenant_id, material_id, batch_no HAVING COUNT(*) > 1"
        )
    )
    groups = [(r[0], r[1], r[2]) for r in dup]
    removed = 0
    for tenant_id, material_id, batch_no in groups:
        rows = await conn.execute(
            text(
                "SELECT id FROM batches WHERE tenant_id = :t "
                "AND material_id = :m AND batch_no = :b ORDER BY id"
            ),
            {"t": tenant_id, "m": material_id, "b": batch_no},
        )
        ids = [r[0] for r in rows]
        if len(ids) < 2:
            continue
        keep, drop = ids[0], ids[1:]
        print(f"[info] 批次重复 {tenant_id}/{material_id}/{batch_no}："
              f"保留 id={keep}，合并 {drop}")
        for bid in drop:
            # 先改指库存与流水，再删批次 —— 顺序反了会把库存行的指向变成孤儿
            for table in ("inventory", "inventory_transactions"):
                try:
                    await conn.execute(
                        text(f"UPDATE {table} SET batch_id = :keep WHERE batch_id = :drop"),
                        {"keep": keep, "drop": bid},
                    )
                except Exception as exc:
                    print(f"[warn] 改指 {table} 失败，跳过：{exc}")
            await conn.execute(text("DELETE FROM batches WHERE id = :i"), {"i": bid})
            removed += 1
    return removed


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        changes += await _backfill_batches(conn)
        changes += await _backfill_inventory(conn, dialect)
        changes += await _dedupe(conn)

        if await _has_unique_index(conn, dialect):
            print(f"[skip] batches 上已有唯一索引覆盖 {INDEX_COLUMNS}")
        else:
            await conn.execute(
                text(
                    f"CREATE UNIQUE INDEX IF NOT EXISTS {INDEX_NAME} "
                    f"ON batches ({', '.join(INDEX_COLUMNS)})"
                )
            )
            print(f"[apply] CREATE UNIQUE INDEX {INDEX_NAME} ON batches "
                  f"({', '.join(INDEX_COLUMNS)})")
            changes += 1

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
