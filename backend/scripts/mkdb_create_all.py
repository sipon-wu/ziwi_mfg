"""在空库上按模型建表（create_all），并回读实际建了多少张。

清库重建链路的第一步，见 `docs/reset-and-rebuild-2026-11-05.md` §7.2。

用法（容器内，必须先 `CREATE DATABASE` 建好空库）：
    docker exec -e DB_NAME=mfg_clean mfg1-backend python /app/scripts/mkdb_create_all.py

输出两行数字必须相等，否则模型注册不全（漏 `import app.models` 的某个子模块）：
    模型表数: 123
    实际建表数: 123
"""
import asyncio
import os
import sys

# 直接 `python scripts/xxx.py` 时 sys.path[0] 是 scripts/ 而不是 backend/，
# 不补这一行会 ModuleNotFoundError: No module named 'app'（与 seed_permissions.py 同款）。
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

import app.models  # noqa: E402,F401  注册全部模型
from app.core.database import Base, init_db, get_engine  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from sqlalchemy import text  # noqa: E402


async def main():
    s = get_settings()
    print("库:", s.DB_NAME)
    await init_db()
    print("模型表数:", len(Base.metadata.tables))
    eng = get_engine()
    async with eng.connect() as conn:
        n = (await conn.execute(text(
            "select count(*) from pg_tables where schemaname='public'"))).scalar()
    print("实际建表数:", n)
    await eng.dispose()


asyncio.run(main())
