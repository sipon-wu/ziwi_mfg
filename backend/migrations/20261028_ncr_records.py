#!/usr/bin/env python3
"""建 M30 质量域的「不合格品评审」表 `ncr_records`（幂等、方言无关）。

背景
----
2026-10-28 SRM 第四层（SI&D / SCAR）设计时发现 M30 的结构性缺口：
`inspection_order.result`(ACC/REJ/UAI) 与 `inspection_result.result`(PASS/FAIL)
**只有判定、没有处置** —— REJ 之后的「退货 / 挑选 / 让步接收 / 返工 / 报废 / 索赔」
无处记录，导致 SCAR 既没有源头事件、也没有闭环证据。

本表是 SI&D 的地基。设计出处：
docs/架构v2-松耦合目标态与迁移路径-2026-10-28.md §3.13

设计约束
--------
- 幂等：先 has_table 探测，已存在则跳过；可重复运行。
- 方言无关：用 SQLAlchemy metadata.create_all 生成 DDL，不手写 PG/SQLite 两份 SQL。
- 防御：异常只打印不抛，不阻断部署。

用法
----
    python backend/migrations/20261028_ncr_records.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> int:
    from app.core.database import Base, get_engine
    from app.models.quality import NcrRecord  # noqa: F401  确保表注册进 metadata

    engine = get_engine()
    dialect = engine.dialect.name
    table = NcrRecord.__table__

    async with engine.begin() as conn:
        exists = await conn.run_sync(
            lambda sync_conn: sync_conn.dialect.has_table(sync_conn, table.name)
        )
        if exists:
            print(f"[skip] 表 {table.name} 已存在（{dialect}）")
            await engine.dispose()
            return 0

        await conn.run_sync(
            lambda sync_conn: Base.metadata.create_all(
                sync_conn, tables=[table], checkfirst=True
            )
        )
        print(f"[apply] CREATE TABLE {table.name}（{dialect}）")

    await engine.dispose()
    return 1


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
