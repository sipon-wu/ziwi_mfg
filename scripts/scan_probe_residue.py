"""临时只读扫描：哪些表还躺着「探针后缀」的主数据（不进库、不删任何行）。

用法（容器内）::

    docker cp scripts/_scan_probe_codes.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/_scan_probe_codes.py AH-THR
"""
import asyncio
import os
import re
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.isfile(os.path.join(BACKEND_DIR, "app", "core", "config.py")):
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text                       # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine   # noqa: E402

from app.core.config import get_settings          # noqa: E402

TENANT_CODE = sys.argv[1] if len(sys.argv) > 1 else "AH-THR"
# 只认「分隔符 + 10 位时间戳收尾」这一种形态：探针造的主数据几乎都是它。
SUFFIX = re.compile(r"[-_][0-9]{10}$")


async def main():
    eng = create_async_engine(get_settings().DATABASE_URL)
    try:
        async with eng.connect() as conn:
            tid = (await conn.execute(text(
                "select tenant_id from tenants where code = :c"),
                {"c": TENANT_CODE})).scalar()
            if not tid:
                print(f"租户 {TENANT_CODE} 不存在")
                return 1

            tables = [r[0] for r in (await conn.execute(text(
                "select table_name from information_schema.columns "
                "where table_schema='public' and column_name='code' "
                "order by table_name"))).fetchall()]
            # `permissions` 这类全局字典表没有 tenant_id（权限码是平台级的），
            # 按租户扫会直接报 UndefinedColumn —— 先过滤掉。
            has_tid = {r[0] for r in (await conn.execute(text(
                "select table_name from information_schema.columns "
                "where table_schema='public' and column_name='tenant_id'"))).fetchall()}
            tables = [t for t in tables if t in has_tid]

            print(f"租户 {TENANT_CODE} → {tid}，带 code 列的表 {len(tables)} 张")
            print(f"{'表':<28}{'探针行':>8}{'总行':>8}   样例")
            total_probe = 0
            for t in tables:
                rows = (await conn.execute(text(
                    f'select code from "{t}" where tenant_id = :t'), {"t": tid})).fetchall()
                hit = [str(r[0]) for r in rows if r[0] and SUFFIX.search(str(r[0]))]
                if not hit:
                    continue
                total_probe += len(hit)
                sample = ", ".join(hit[:3]) + (f" …共{len(hit)}" if len(hit) > 3 else "")
                print(f"{t:<28}{len(hit):>8}{len(rows):>8}   {sample}")
            print(f"\n合计探针后缀主数据 {total_probe} 行（内存里算的，SQL 不带正则，方言无差异）")
        return 0
    finally:
        await eng.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
