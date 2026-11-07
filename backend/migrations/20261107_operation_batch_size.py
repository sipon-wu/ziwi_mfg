#!/usr/bin/env python3
"""给 `operations` 加 `batch_size`（同装量，件/批）——幂等，不阻断部署。

背景
----
「炉 / 烘箱 / 罐」这类工序的工艺时间是**一炉**的时长，不是一件的。
推进器定子线的「固化烘烤」工艺 **120 分/炉、一炉 4 个**，而 `operations.unit_time`
的语义是「每件占用设备的分钟数」——没有这一列时只能把 30（=120÷4）手填进去，
于是**「4」这个事实在库里不存在**：

- 换个人看到 30，看不出它是 120÷4，产能复核时拿工艺卡（120）对不上；
- 那条线会因此被低估 4 倍：单班闭环下线 1 台（22 台/月）而不是 2 台（44）。

加列之后的唯一口径：

    每件占机 = (unit_time + setup_time) / batch_size

`batch_size = 1` 时退化为原来的 `unit_time + setup_time`，**存量语义不变**。
消费方是 `scripts/check_capacity_consistency.py`（口径 A/B/C 都走这个式子）。

方言
----
`ALTER TABLE operations ADD COLUMN batch_size INTEGER NOT NULL DEFAULT 1` 两端都成立。
`NOT NULL` 必须配 `DEFAULT`：加列为 NOT NULL 而不给默认值，PG 在有存量行时直接报错
（PG 方言铁律第 1 条 —— `default=` 只是 ORM 层默认，不会进 DDL）。

本迁移**只做 DDL**，不写业务数据：
「哪道工序是几件一批」是业务事实（客户工艺卡上的数），不该由迁移脚本猜。
本仓的靶场数据由种子脚本负责（`scripts/seed_thruster_staging.py` 里
`CW040-5 固化烘烤` 的 `unit_time=120, batch_size=4`）。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261107_operation_batch_size.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

TABLE = "operations"
COLUMN = "batch_size"
#: 方言无关：SQLite 与 PG 都接受 INTEGER NOT NULL DEFAULT 1。
DDL = "INTEGER NOT NULL DEFAULT 1"


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


async def apply() -> int:
    from app.core.database import get_engine

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    async with engine.begin() as conn:
        existing = await _fetch_columns(conn, dialect, TABLE)
        if not existing:
            print(f"[skip] 表 {TABLE} 不存在")
        elif COLUMN in existing:
            print(f"[skip] {TABLE}.{COLUMN} 已存在 ({existing[COLUMN]})")
        else:
            await conn.execute(text(
                f"ALTER TABLE {TABLE} ADD COLUMN {COLUMN} {DDL}"))
            print(f"[apply] ALTER TABLE {TABLE} ADD COLUMN {COLUMN} {DDL}")
            changes += 1

        # 自检：加完必须没有 NULL 也没有 0（0 会让产能核算除零）
        if COLUMN in (await _fetch_columns(conn, dialect, TABLE)):
            bad = (await conn.execute(text(
                f"SELECT COUNT(*) FROM {TABLE} "
                f"WHERE {COLUMN} IS NULL OR {COLUMN} < 1"
            ))).scalar() or 0
            if bad:
                print(f"[warn] {bad} 行 {COLUMN} < 1，产能核算会除零 —— 按 1 回填")
                await conn.execute(text(
                    f"UPDATE {TABLE} SET {COLUMN} = 1 "
                    f"WHERE {COLUMN} IS NULL OR {COLUMN} < 1"))
                changes += 1

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
