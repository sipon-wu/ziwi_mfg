#!/usr/bin/env python3
"""建 `work_order_steps`（工单工序实例）并回填存量 —— 幂等，不阻断部署。

背景
----
用户 2026-11-10 定的产品口径：**报工管理应该是"全部工序列表"**，每行带当前生产
状态（数量、是否在工作、阻塞、缺料），点进去是这道工序的报工页；再上一层可以
把邻近/同质工序编成小组统一报工；扫码过站则自动完成该道工序的报工。

这三件事压在同一个地基上，而这个地基**当时不存在**：工单只有 `wo_status`（整单
状态），工序只在路线模板 `route_steps` 里，**没有任何一行表示"这张工单的第 3 道
工序现在是什么状态"**。于是：

- 报工管理只能做成"报工流水台账"（已经发生的事），做不成"我今天该干什么"；
- 扫码过站没法判断"这个码现在该过哪一道"—— 合装组套页能定位到合装工序，
  是因为那个页面**硬编码了"这里就是合装"**，换个工位就复用不了。

## 为什么是快照，不是实时 join `route_steps`

路线会改版（加一道工序、换工作中心、调顺序）。实时 join 的话，一张三个月前的工单
今天打开会显示"它从没走过的那道工序"，而它的报工记录里一行都对不上 ——
**历史被后来的改版改写了，脏数据却是当时的人背锅**。`bom_snapshots` 同一个道理。

## 回填口径

1. **只给挂了路线的工单展开**。无路线的老单是"报整单"的合法形态，硬给它造一道
   假工序，等于把"没有路线"这件事从数据上抹掉 —— 报表三桶里的
   `unrouted_output` 正是靠这个区分才成立。
2. **累计量从 `work_reports` 回算**，不按 `completed_qty` 摊。否则存量 5629 条
   报工在工序列表上全是 0，等于新页面一上线就是错的。
3. **报工没填工序码的行（`operation_code IS NULL`）不参与回算**。那是"报整单"，
   它本来就对应不到某一道工序；猜一个最像的填进去，会让工序流转量凭空多出来。

## 方言

- `CREATE TABLE` 走模型的 `__table__.create()`，唯一约束随之建立；
  但 **SQLAlchemy 2.0 的 CreateTable 不带索引**，两条普通索引必须在这里显式补，
  否则 `diff_schema.py` 直接报漂移。
- `CREATE INDEX IF NOT EXISTS` 幂等但不"服气"：重复执行不报错却每次都像一次变更。
  所以先用 `sqlite_master` / `pg_indexes` **实查**再决定要不要建（`_has_index`）。
- 回填的 `INSERT ... SELECT` 与相关子查询 `UPDATE` 两种方言都吃；
  刻意不用 `INSERT ... ON CONFLICT`（SQLite 3.24+ 才有）和 `DISTINCT ON`（PG 专有）。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261110_work_order_steps.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLE = "work_order_steps"

INDEXES = [
    ("ix_wo_step_tenant_wc_status",
     f"CREATE INDEX IF NOT EXISTS ix_wo_step_tenant_wc_status "
     f"ON {TABLE} (tenant_id, wc_id, status)"),
    ("ix_wo_step_tenant_wo",
     f"CREATE INDEX IF NOT EXISTS ix_wo_step_tenant_wo "
     f"ON {TABLE} (tenant_id, work_order_id)"),
]

# ① 按路线展开。step_seq 在同一 route 里理论上唯一；万一脏数据有重复，
#    唯一约束会让整笔事务失败 —— 所以用 MIN(id) 取一行，宁可少一条也不炸。
BACKFILL_STEPS = """
INSERT INTO work_order_steps
    (tenant_id, work_order_id, step_seq, operation_id, operation_code,
     operation_name, wc_id, step_type, planned_qty,
     input_qty, output_qty, scrap_qty, report_count,
     status, first_reported_at, last_reported_at, org_id)
SELECT wo.tenant_id, wo.id, rs.step_seq, rs.operation_id, o.code,
       COALESCE(rs.step_name, o.name), rs.wc_id,
       COALESCE(rs.step_type, 'production'),
       COALESCE(wo.planned_qty, 0),
       0, 0, 0, 0, 'pending', NULL, NULL, wo.org_id
FROM work_orders wo
JOIN route_steps rs ON rs.route_id = wo.route_id
LEFT JOIN operations o ON o.id = rs.operation_id
WHERE wo.route_id IS NOT NULL
  AND rs.id = (SELECT MIN(r2.id) FROM route_steps r2
               WHERE r2.route_id = rs.route_id AND r2.step_seq = rs.step_seq)
  AND NOT EXISTS (SELECT 1 FROM work_order_steps s
                  WHERE s.tenant_id = wo.tenant_id
                    AND s.work_order_id = wo.id
                    AND s.step_seq = rs.step_seq)
"""

# ② 累计量回算。四个字段各一个相关子查询，条件必须**完全一致**
#    （同一工单 + 同一工序码 + 非 rejected），否则"产出有、次数没有"这种
#    半截状态会出现，而且完全不会报错。
BACKFILL_AGG = """
UPDATE work_order_steps SET
    input_qty = COALESCE((SELECT SUM(r.input_qty) FROM work_reports r
        WHERE r.work_order_id = work_order_steps.work_order_id
          AND r.operation_code = work_order_steps.operation_code
          AND (r.status IS NULL OR r.status <> 'rejected')), 0),
    output_qty = COALESCE((SELECT SUM(r.output_qty) FROM work_reports r
        WHERE r.work_order_id = work_order_steps.work_order_id
          AND r.operation_code = work_order_steps.operation_code
          AND (r.status IS NULL OR r.status <> 'rejected')), 0),
    scrap_qty = COALESCE((SELECT SUM(r.scrap_qty) FROM work_reports r
        WHERE r.work_order_id = work_order_steps.work_order_id
          AND r.operation_code = work_order_steps.operation_code
          AND (r.status IS NULL OR r.status <> 'rejected')), 0),
    report_count = COALESCE((SELECT COUNT(*) FROM work_reports r
        WHERE r.work_order_id = work_order_steps.work_order_id
          AND r.operation_code = work_order_steps.operation_code
          AND (r.status IS NULL OR r.status <> 'rejected')), 0),
    first_reported_at = (SELECT MIN(r.reported_at) FROM work_reports r
        WHERE r.work_order_id = work_order_steps.work_order_id
          AND r.operation_code = work_order_steps.operation_code
          AND (r.status IS NULL OR r.status <> 'rejected')),
    last_reported_at = (SELECT MAX(r.reported_at) FROM work_reports r
        WHERE r.work_order_id = work_order_steps.work_order_id
          AND r.operation_code = work_order_steps.operation_code
          AND (r.status IS NULL OR r.status <> 'rejected'))
WHERE operation_code IS NOT NULL
"""

# ③ 状态推导。判据与运行时**完全一致**（`ProductionService._step_status`）：
#    有计划量时按累计合格产出判完工，计划量为 0 时不判完工（不然一律立刻完工）。
BACKFILL_STATUS = f"""
UPDATE {TABLE} SET status = CASE
    WHEN report_count = 0 THEN 'pending'
    WHEN planned_qty > 0 AND output_qty >= planned_qty THEN 'completed'
    ELSE 'in_progress'
END
"""


async def _table_exists(conn, dialect: str, table: str) -> bool:
    if dialect == "sqlite":
        res = await conn.execute(text(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=:n"), {"n": table})
    else:
        res = await conn.execute(text(
            "SELECT 1 FROM information_schema.tables "
            "WHERE table_schema='public' AND table_name=:n"), {"n": table})
    return res.first() is not None


async def _has_index(conn, dialect: str, index: str) -> bool:
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"), {"n": index})
        else:
            res = await conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname=:n"), {"n": index})
        return res.first() is not None
    except Exception:  # noqa: BLE001
        return False


async def _count(conn, sql: str) -> int:
    res = await conn.execute(text(sql))
    row = res.first()
    return int(row[0] or 0) if row else 0


async def apply() -> int:
    from app.core.database import get_engine
    from app.models.production import WorkOrderStep

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        existed = await _table_exists(conn, dialect, TABLE)
        if existed:
            print(f"[skip] 表 {TABLE} 已存在")
        else:
            await conn.run_sync(lambda sync_conn: WorkOrderStep.__table__.create(sync_conn))
            print(f"[apply] CREATE TABLE {TABLE}")
            changes += 1

        for name, ddl in INDEXES:
            if await _has_index(conn, dialect, name):
                print(f"[skip] 索引 {name} 已存在")
                continue
            try:
                await conn.execute(text(ddl))
                print(f"[apply] {ddl}")
                changes += 1
            except Exception as exc:  # noqa: BLE001 — 索引失败不阻断
                print(f"[warn] 建索引 {name} 失败（只影响查询速度）: {exc}")

        before = await _count(conn, f"SELECT COUNT(*) FROM {TABLE}")
        res = await conn.execute(text(BACKFILL_STEPS))
        inserted = res.rowcount if res.rowcount and res.rowcount > 0 else 0
        after = await _count(conn, f"SELECT COUNT(*) FROM {TABLE}")
        delta = after - before
        if delta > 0:
            print(f"[apply] 按路线展开工序 {delta} 行（{before} → {after}）")
            changes += 1
        else:
            print(f"[skip] 没有需要展开的工单（{TABLE} 当前 {after} 行）")
        _ = inserted

        res = await conn.execute(text(BACKFILL_AGG))
        print(f"[apply] 报工累计量回算（影响 {res.rowcount or 0} 行）")

        await conn.execute(text(BACKFILL_STATUS))
        print("[apply] 工序状态推导完成")

    # 回读：把结果数字打出来，别只说"完成"
    async with engine.connect() as conn:
        rows = await conn.execute(text(
            f"SELECT status, COUNT(*) FROM {TABLE} GROUP BY status"))
        dist = {r[0]: r[1] for r in rows}
        total = sum(dist.values())
        print(f"[check] 工序实例 {total} 行，状态分布 {dist}")
        orphans = await _count(
            conn,
            f"SELECT COUNT(*) FROM {TABLE} s "
            f"LEFT JOIN work_orders w ON w.id = s.work_order_id WHERE w.id IS NULL")
        print(f"[check] 悬空（指向不存在的工单）{orphans} 行")

    await engine.dispose()
    return changes


if __name__ == "__main__":
    n = asyncio.run(apply())
    print(f"\n共 {n} 处变更")
