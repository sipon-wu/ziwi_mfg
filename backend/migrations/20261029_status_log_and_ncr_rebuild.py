#!/usr/bin/env python3
"""建通用状态流水表 `entity_status_logs`，并按新设计重建 `ncr_records`。

背景
----
评审（docs/精益与架构方案全面评审-2026-10-29.md）发现：
- P0-2：多数模块缺状态变更流水 → 决策流看板与精益体检算不出来
- P0-3：`ncr_records` 自身只有 `status`、无轨迹，违反了当天确立的精益五问 Q2

用户 2026-10-29 授权：可以推倒重来，新建表可调整或清除重建。
本脚本据此：① 新建通用流水表 ② 重建 `ncr_records`（**空表保护**）。

设计约束
--------
- 幂等：先探测再执行，可重复运行。
- 方言无关：用 SQLAlchemy metadata 生成 DDL，不手写 PG/SQLite 两份 SQL。
- **安全边界**：`ncr_records` 目前只存在于本地开发库（2026-10-28 才建），
  重建是安全的；但脚本仍强制校验——**表中有数据时拒绝 DROP**，
  除非显式传 `--force`。staging/生产库严禁对本表执行 DROP。
- 防御：异常只打印不抛，不阻断部署。

用法
----
    python backend/migrations/20261029_status_log_and_ncr_rebuild.py
    python backend/migrations/20261029_status_log_and_ncr_rebuild.py --force   # 非空也重建（慎用）
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

FORCE = "--force" in sys.argv


async def _has_table(conn, name: str) -> bool:
    return await conn.run_sync(
        lambda sync_conn: sync_conn.dialect.has_table(sync_conn, name)
    )


async def _count(conn, name: str) -> int:
    from sqlalchemy import text

    result = await conn.execute(text(f"SELECT COUNT(*) FROM {name}"))
    return result.scalar() or 0


async def apply() -> int:
    from sqlalchemy import text

    from app.core.database import Base, get_engine
    from app.models.status_log import EntityStatusLog  # noqa: F401
    from app.models.quality import NcrRecord  # noqa: F401

    engine = get_engine()
    dialect = engine.dialect.name
    changes = 0

    # 两张表均为本轮新建、模型可能继续调整，故统一走「空表保护下的重建」
    targets = [
        (EntityStatusLog.__table__, "entity_status_logs"),
        (NcrRecord.__table__, "ncr_records"),
    ]

    async with engine.begin() as conn:
        for table, name in targets:
            exists = await _has_table(conn, name)
            if not exists:
                await conn.run_sync(
                    lambda sc, t=table: Base.metadata.create_all(
                        sc, tables=[t], checkfirst=True
                    )
                )
                print(f"[apply] CREATE TABLE {name}（{dialect}）")
                changes += 1
                continue

            cnt = await _count(conn, name)
            if cnt > 0 and not FORCE:
                print(
                    f"[skip] {name} 有 {cnt} 行数据，拒绝重建"
                    "（如需强制重建请加 --force；staging/生产严禁执行）"
                )
                continue
            if cnt > 0:
                print(f"[warn] --force 生效：将丢弃 {name} 的 {cnt} 行数据")
            await conn.execute(text(f"DROP TABLE {name}"))
            await conn.run_sync(
                lambda sc, t=table: Base.metadata.create_all(sc, tables=[t], checkfirst=True)
            )
            print(f"[apply] DROP + CREATE TABLE {name}（{dialect}）")
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
