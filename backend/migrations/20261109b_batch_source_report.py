#!/usr/bin/env python3
"""给 `batches` 加 `source_report_id`（部件码自动赋码的来源）—— 幂等，不阻断部署。

背景（台账 B-30）
----------------
方案书 §2.1 的三个赋码节点里，只有第三个（`MA020` 合装 → 成品码）通了，
前两个 —— 工序1 `CW010` 槽绝缘插入 → 定子码、工序7 `RT010` 保持架压装 →
转子码 —— 此前没有任何代码在出码，只能有人去批次管理页手敲一条。

手敲的码和自动出的码**不是一回事**：①容易重复/跳号；②没人保证物料挂对
（挂错等于追溯链第一环就错）；③3 台带打印机的工位只有 1 台用得上。

自动赋码之后，「这个码是哪来的」必须有据可查 —— 否则追溯只能靠 `batch_no`
里的日期段猜，猜不出工单，更猜不出谁报的工。所以加这一列。

## 为什么是 `source_report_id` 而不是 `work_order_id`

工单可以反查（报工 → 工单），反过来「工单出了哪些码」也能 JOIN 出来；
但如果只存工单，一张工单分批报了 3 次、每次 5 件，就永远说不清**哪个码是
哪一批**出的。报工是赋码的触发动作，来源就该记到触发那一刻。

同一列顺带当幂等键：同一次报工重试时先按它查一遍，不会重复出码。

可空：来料码（`batch_type='raw'`）与合装扫码出的成品码都不来自报工，
留 NULL 是正确语义，**不回填、不猜**（回填等于编造来源）。

## 方言

- `ALTER TABLE batches ADD COLUMN source_report_id BIGINT` 两端都成立，可空不需要 DEFAULT。
- `CREATE INDEX IF NOT EXISTS` 幂等但**谎报变更数**：重复执行不报错却每次都算一次
  变更（见 C-95 踩坑）。所以先用 `sqlite_master` / `pg_indexes` 实查。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261109b_batch_source_report.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLE = "batches"
COLUMN = "source_report_id"
COLUMN_DDL = "BIGINT"
INDEX_NAME = "ix_batches_tenant_source_report"
INDEX_DDL = (
    f"CREATE INDEX IF NOT EXISTS {INDEX_NAME} "
    f"ON {TABLE} (tenant_id, source_report_id)"
)


async def _fetch_columns(conn, dialect: str, table: str) -> dict:
    """{列名: 类型大写}。取不到（表不存在）返回空 dict。"""
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


async def _has_index(conn, dialect: str, index: str) -> bool:
    """索引是否已存在。**必须实查**，不能靠 `IF NOT EXISTS` 自己判断变更数。"""
    try:
        if dialect == "sqlite":
            res = await conn.execute(text(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name=:n"
            ), {"n": index})
        else:
            res = await conn.execute(text(
                "SELECT 1 FROM pg_indexes WHERE indexname=:n"
            ), {"n": index})
        return res.first() is not None
    except Exception:
        return False


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        existing = await _fetch_columns(conn, dialect, TABLE)
        if not existing:
            print(f"[skip] 表 {TABLE} 不存在")
            await engine.dispose()
            return 0

        if COLUMN in existing:
            print(f"[skip] {TABLE}.{COLUMN} 已存在 ({existing[COLUMN]})")
        else:
            await conn.execute(text(
                f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} {COLUMN_DDL}"))
            print(f"[apply] ALTER TABLE {TABLE} ADD COLUMN {COLUMN} {COLUMN_DDL}")
            changes += 1

        if await _has_index(conn, dialect, INDEX_NAME):
            print(f"[skip] 索引 {INDEX_NAME} 已存在")
        else:
            try:
                await conn.execute(text(INDEX_DDL))
                print(f"[apply] {INDEX_DDL}")
                changes += 1
            except Exception as exc:  # noqa: BLE001 — 索引失败不阻断
                print(f"[warn] 建索引失败（不影响功能，只影响追溯查询速度）: {exc}")

        # 如实报账：存量批次的来源都不可考，不该凭空有 source_report_id
        if COLUMN in await _fetch_columns(conn, dialect, TABLE):
            linked = (await conn.execute(text(
                f"SELECT COUNT(*) FROM {TABLE} WHERE {COLUMN} IS NOT NULL"
            ))).scalar() or 0
            total = (await conn.execute(text(
                f"SELECT COUNT(*) FROM {TABLE}"
            ))).scalar() or 0
            print(f"[info] {TABLE} 共 {total} 行，其中带报工来源 {linked} 行"
                  f"（存量应为 0 —— 来源只能由赋码时写入，不由迁移猜）")

    await engine.dispose()
    return changes


def main() -> int:
    try:
        n = asyncio.run(apply())
        print(f"[done] 迁移完成，共 {n} 处变更")
    except Exception as exc:  # 迁移不阻断部署
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0
    return 0


if __name__ == "__main__":
    sys.exit(main())
