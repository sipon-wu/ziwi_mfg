#!/usr/bin/env python3
"""T03 三条执行路径后端补口 —— 结构迁移 + 数据回填（幂等，可重复执行）。

做了什么
--------
1. **建表** ``maintenance_task_items``（点检/保养的项级载体）。
   建表直接复用 ORM 元数据（``Base.metadata.tables[...].create(checkfirst=True)``），
   不手写 DDL —— 手写的 DDL 与模型一旦有一处不一致，``scripts/diff_schema.py``
   立刻报漂移，而"哪一处对"没人说得清。
2. **加列**：
   - ``maintenance_plans.checklist_template``  JSON   点检项模板（配置态）
   - ``issue_orders.short_closed``            BOOLEAN NOT NULL DEFAULT false
   - ``issue_orders.shortage_reason``         TEXT
   - ``inspection_order.standard_id``         BIGINT NULL
3. **回填** ``inspection_order.standard_id``（尽力而为，失败留 NULL 并标 degraded）：
   - 证据优先：本单**已录结果**实际用过的标准（``inspection_result.item_id →
     inspection_item.standard_id``，取出现次数最多者）。这是唯一"有证据"的路径 ——
     检验员当时确实是按这份标准的项在录。
   - 其次同质单迁移：同租户内**同一 qc_point_id**、且已回填成功的单所用的标准
     （多数票）。
   - 都没有 → 留 NULL。``GET /inspection-orders/{id}/checklist`` 会返回
     ``degraded=true`` 并列出全部启用项。

为什么必须模型和迁移脚本**都写**
---------------------------------
``create_all`` 只建**表**，不补**列**。库里靠手工 SQL 补过、模型却没声明时：
本地老库能跑，全新环境（建库即 create_all）直接缺列 → 必崩。这条踩过。

PG / SQLite 双向可跑
--------------------
- 加列前先查 ``information_schema`` / ``PRAGMA``（用 ``inspect``，**不碰
  ``conn.sync_connection``**：async 下会 greenlet_spawn 报错）；
- ``short_closed`` 的默认值按方言分流：PG 写 ``false``（写 0 会被拒），
  SQLite 写 ``0``（``false`` 关键字要高版本）；
- 不用部分索引，故不涉及 ``postgresql_where`` / ``sqlite_where`` 的语义差。

用法
----
    cd backend && ./.venv/Scripts/python.exe ../scripts/migrate_2026_11_02_uplift.py            # 默认 --up
    cd backend && ./.venv/Scripts/python.exe ../scripts/migrate_2026_11_02_uplift.py --up
    cd backend && ./.venv/Scripts/python.exe ../scripts/migrate_2026_11_02_uplift.py --down

``--down`` 只删列、**不删表**（``maintenance_task_items`` 里的点检记录留作数据打捞，
代码不读即等于下线）。
"""
import argparse
import asyncio
import os
import sys
from collections import Counter, defaultdict

BACKEND = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "backend")
if BACKEND not in sys.path:
    sys.path.insert(0, BACKEND)


# (表, 列, 类型-PG, 类型-其它方言)
NEW_COLUMNS = [
    ("maintenance_plans", "checklist_template", "JSON", "JSON"),
    ("issue_orders", "short_closed", "BOOLEAN NOT NULL DEFAULT false",
     "BOOLEAN NOT NULL DEFAULT 0"),
    ("issue_orders", "shortage_reason", "TEXT", "TEXT"),
    ("inspection_order", "standard_id", "BIGINT", "BIGINT"),
]

NEW_TABLE = "maintenance_task_items"


async def _has_table(conn, table: str) -> bool:
    from sqlalchemy import inspect

    def _check(sync_conn):
        return table in inspect(sync_conn).get_table_names()

    return await conn.run_sync(_check)


async def _has_column(conn, table: str, column: str) -> bool:
    from sqlalchemy import inspect

    def _check(sync_conn):
        insp = inspect(sync_conn)
        if table not in insp.get_table_names():
            return False
        return any(c["name"] == column for c in insp.get_columns(table))

    return await conn.run_sync(_check)


async def _create_task_items_table(conn) -> bool:
    """建 ``maintenance_task_items``（已存在则跳过）。返回是否真的建了。"""
    import app.models  # noqa: F401  —— 导入后表才注册进 metadata
    from app.core.database import Base

    if await _has_table(conn, NEW_TABLE):
        print(f"[skip] 表 {NEW_TABLE} 已存在")
        return False
    table = Base.metadata.tables[NEW_TABLE]

    def _create(sync_conn):
        table.create(bind=sync_conn, checkfirst=True)

    await conn.run_sync(_create)
    print(f"[apply] CREATE TABLE {NEW_TABLE}")
    return True


async def _add_columns(conn) -> int:
    from sqlalchemy import text

    added = 0
    dialect = conn.dialect.name
    for table, column, pg_type, other_type in NEW_COLUMNS:
        if await _has_column(conn, table, column):
            print(f"[skip] {table}.{column} 已存在")
            continue
        col_type = pg_type if dialect == "postgresql" else other_type
        await conn.execute(text(
            f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
        print(f"[apply] ALTER TABLE {table} ADD COLUMN {column} {col_type}")
        added += 1
    return added


async def _backfill_standard_id(conn) -> dict:
    """尽力回填 ``inspection_order.standard_id``，返回回填统计。"""
    from sqlalchemy import text

    orders = (await conn.execute(text(
        "SELECT id, tenant_id, qc_point_id, standard_id FROM inspection_order"
    ))).mappings().all()
    total = len(orders)
    already = sum(1 for o in orders if o["standard_id"] is not None)
    todo = [o for o in orders if o["standard_id"] is None]
    if not todo:
        return {"total": total, "already": already, "by_evidence": 0,
                "by_peer": 0, "null": 0, "filled": already}

    # ── 路径 1：证据（本单已录结果实际用到的标准） ──
    evidence_rows = (await conn.execute(text(
        "SELECT ir.order_id, ii.standard_id, COUNT(*) AS cnt "
        "FROM inspection_result ir "
        "JOIN inspection_item ii ON ii.id = ir.item_id "
        "WHERE ii.standard_id IS NOT NULL "
        "GROUP BY ir.order_id, ii.standard_id"
    ))).mappings().all()
    votes = defaultdict(Counter)
    for r in evidence_rows:
        votes[r["order_id"]][r["standard_id"]] += int(r["cnt"] or 0)

    by_evidence = 0
    resolved = {}
    for o in todo:
        counter = votes.get(o["id"])
        if not counter:
            continue
        # 票数最多者；平票取较小 standard_id（可复现，不随机）
        best = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        resolved[o["id"]] = (best, "evidence")
        by_evidence += 1

    # ── 路径 2：同质单迁移（同租户 + 同 qc_point_id 的多数票） ──
    peer_votes = defaultdict(Counter)
    for o in orders:
        if o["standard_id"] is None:
            continue
        if o["qc_point_id"] is None:
            continue
        peer_votes[(o["tenant_id"], o["qc_point_id"])][o["standard_id"]] += 1
    by_peer = 0
    for o in todo:
        if o["id"] in resolved or o["qc_point_id"] is None:
            continue
        counter = peer_votes.get((o["tenant_id"], o["qc_point_id"]))
        if not counter:
            continue
        best = sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[0][0]
        resolved[o["id"]] = (best, "peer")
        by_peer += 1

    for order_id, (std_id, _src) in resolved.items():
        await conn.execute(text(
            "UPDATE inspection_order SET standard_id = :sid WHERE id = :id"),
            {"sid": std_id, "id": order_id})
    if resolved:
        print(f"[apply] 回填 inspection_order.standard_id：{len(resolved)} 张单")

    filled = already + len(resolved)
    return {"total": total, "already": already, "by_evidence": by_evidence,
            "by_peer": by_peer, "null": total - filled, "filled": filled}


async def _drop_columns(conn) -> int:
    """``--down``：只删列，不删表（点检记录留作数据打捞）。"""
    from sqlalchemy import text

    dropped = 0
    for table, column, _pg, _other in reversed(NEW_COLUMNS):
        if not await _has_column(conn, table, column):
            print(f"[skip] {table}.{column} 不存在")
            continue
        try:
            await conn.execute(text(f"ALTER TABLE {table} DROP COLUMN {column}"))
            print(f"[apply] ALTER TABLE {table} DROP COLUMN {column}")
            dropped += 1
        except Exception as exc:  # noqa: BLE001 —— 老 SQLite 不支持 DROP COLUMN
            print(f"[warn] {table}.{column} 删列失败（方言限制）：{exc}")
    print(f"[note] 表 {NEW_TABLE} 保留（--down 不删表，数据留作打捞）")
    return dropped


async def run(direction: str = "up") -> int:
    from app.core.database import ensure_engine

    engine = ensure_engine()
    dialect = engine.dialect.name
    print(f"[info] dialect={dialect} direction={direction}")
    changes = 0
    async with engine.begin() as conn:
        if direction == "up":
            if await _create_task_items_table(conn):
                changes += 1
            changes += await _add_columns(conn)
            stats = await _backfill_standard_id(conn)
            total = stats["total"] or 0
            rate = (stats["filled"] / total * 100) if total else 0.0
            print(f"[stat] inspection_order 共 {total} 张；已挂标准 {stats['filled']} 张"
                  f"（回填率 {rate:.1f}%）")
            print(f"[stat]   其中 原有 {stats['already']} + 证据回填 "
                  f"{stats['by_evidence']} + 同质单回填 {stats['by_peer']}")
            print(f"[stat]   仍为 NULL（degraded）{stats['null']} 张")
        else:
            changes += await _drop_columns(conn)
    await engine.dispose()
    print(f"[done] {direction} 完成，共 {changes} 处结构变更")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="T03 结构迁移 + standard_id 回填")
    ap.add_argument("--up", action="store_true", help="建表/加列/回填（默认）")
    ap.add_argument("--down", action="store_true", help="删列（不删表）")
    args = ap.parse_args()
    direction = "down" if args.down and not args.up else "up"
    try:
        return asyncio.run(run(direction))
    except Exception as exc:  # noqa: BLE001 —— 迁移失败不阻断部署
        print(f"[error] 迁移失败：{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
