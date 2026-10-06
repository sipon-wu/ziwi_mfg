#!/usr/bin/env python3
"""Integration Gateway — API Key 表幂等迁移（IG MVP）。

用途
----
在已存在表的库上创建 `api_keys` 表（OA / HR / LIMS / ERP 对接的认证原语）。

设计约束
--------
- 幂等：先探测再执行，可重复运行；只做 CREATE，不做 DROP。
- 跨平台：SQLite（本地回归库）与 PostgreSQL（生产）走同一份脚本。

用法
----
    backend/.venv/Scripts/python.exe backend/migrations/20261003_api_keys.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import inspect  # noqa: E402


def _collect_tables(sync_conn) -> set:
    return set(inspect(sync_conn).get_table_names())


async def apply(url: str) -> int:
    from sqlalchemy.ext.asyncio import create_async_engine

    import app.models  # noqa: F401  注册 metadata
    from app.core.database import Base
    from app.models.api_key import ApiKey

    tables = [ApiKey.__table__]
    engine = create_async_engine(url)
    changes = 0

    async with engine.begin() as conn:
        existing = await conn.run_sync(_collect_tables)

    try:
        async with engine.begin() as conn:
            missing = [t for t in tables if t.name not in existing]
            if missing:
                await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=missing))
                for t in missing:
                    print(f"[apply] CREATE TABLE {t.name}")
                    changes += 1
            else:
                print("[skip] api_keys 表已存在")
    except Exception as exc:  # 防御：建表异常不阻断部署
        print(f"[error] 建表失败（请检查日志）: {exc}")

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
