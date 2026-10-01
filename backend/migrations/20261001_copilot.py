#!/usr/bin/env python3
"""AI Copilot（E1）—— 方言自适应的幂等迁移脚本。

用途
----
在**已存在表**的库上创建 Copilot 相关表，并在 PostgreSQL 上启用 pgvector：

    1) CREATE EXTENSION IF NOT EXISTS vector   （仅 PG）
    2) copilot_sessions / copilot_messages / copilot_feedbacks /
       copilot_ask_logs / metric_definitions / copilot_doc_chunks
       （复用 SQLAlchemy metadata，幂等）
    3) PG: copilot_doc_chunks.embedding vector(1024) 列 + ivfflat 索引（可选）

设计约束
--------
- 幂等：先探测再执行，可重复运行；只做 CREATE，不做 DROP。
- 跨平台：SQLite（本地回归库）与 PostgreSQL（生产）走同一份脚本。
- 不新增独立向量库（复用现有 PG + pgvector）。

用法
----
    # PostgreSQL（读 backend/.env）
    backend/.venv/Scripts/python.exe backend/migrations/20261001_copilot.py

    # 指定库
    ZIWI_MIGRATION_DB_URL="sqlite+aiosqlite:///D:/.../ziwa_alpha.db" \\
        backend/.venv/Scripts/python.exe backend/migrations/20261001_copilot.py
"""

import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import inspect, text  # noqa: E402

EMBED_DIM = 1024  # 与 AI_EMBED_MODEL（text-embedding-v3）向量维度对齐


def _engine_kwargs(url: str) -> dict:
    if url.startswith("sqlite"):
        return {}
    return {"pool_size": 5, "max_overflow": 10}


def _collect_tables(sync_conn) -> set:
    return set(inspect(sync_conn).get_table_names())


async def apply(url: str) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    # 导入模型以注册 metadata
    import app.models  # noqa: F401
    from app.core.database import Base
    from app.models.copilot import (
        CopilotAskLog,
        CopilotDocChunk,
        CopilotFeedback,
        CopilotMessage,
        CopilotSession,
        MetricDefinition,
    )

    tables = [
        CopilotSession.__table__,
        CopilotMessage.__table__,
        CopilotFeedback.__table__,
        CopilotAskLog.__table__,
        MetricDefinition.__table__,
        CopilotDocChunk.__table__,
    ]

    engine = create_async_engine(url, **_engine_kwargs(url))
    changes = 0

    async with engine.begin() as conn:
        dialect = conn.dialect.name
        existing = await conn.run_sync(_collect_tables)

        # ── 1. pgvector 扩展（仅 PG）────────────────────────────────
        if dialect == "postgresql":
            try:
                await conn.execute(text("CREATE EXTENSION IF NOT EXISTS vector"))
                print("[apply] CREATE EXTENSION IF NOT EXISTS vector")
                changes += 1
            except Exception as exc:  # 权限不足时降级为关键词检索
                print(f"[warn] 启用 pgvector 失败（将降级为关键词检索）: {exc}")
        else:
            print("[skip] 非 PostgreSQL，跳过 pgvector 扩展")

        # ── 2. 建表（幂等：create_all 只建缺失表）────────────────────
        missing = [t for t in tables if t.name not in existing]
        if missing:
            await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=missing))
            for t in missing:
                print(f"[apply] CREATE TABLE {t.name}")
                changes += 1
        else:
            print("[skip] Copilot 表均已存在")

        # ── 3. PG: 向量列 + 索引 ────────────────────────────────────
        if dialect == "postgresql" and "copilot_doc_chunks" in existing + {t.name for t in tables}:
            cols = await conn.run_sync(
                lambda c: {col["name"] for col in inspect(c).get_columns("copilot_doc_chunks")}
            )
            if "embedding" not in cols:
                try:
                    await conn.execute(
                        text(f"ALTER TABLE copilot_doc_chunks ADD COLUMN embedding vector({EMBED_DIM})")
                    )
                    print("[apply] ALTER TABLE copilot_doc_chunks ADD COLUMN embedding vector")
                    changes += 1
                except Exception as exc:
                    print(f"[warn] 增加 embedding 列失败（将降级为关键词检索）: {exc}")

    await engine.dispose()
    return changes


async def main() -> int:
    url = os.environ.get("ZIWI_MIGRATION_DB_URL")
    if not url:
        os.environ.setdefault("APP_ENV", "development")
        import app.core.database as db_mod  # noqa: E402
        url = db_mod.settings.DATABASE_URL

    print(f"[migration] target = {url}")
    changes = await apply(url)
    print(f"[migration] 完成，共执行 {changes} 条 DDL")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
