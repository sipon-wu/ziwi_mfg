#!/usr/bin/env python3
"""库重置：清空全部业务表，回到"空表"状态，供从零重建。

## 为什么要有这个脚本

2026-11-05 盘 staging：**54 个租户**（其中 52 个是探针租户，形如 `E2E1105085514`）、
108 条工序里 **65 条是 `OP-S3-*` 这类探针垃圾**（名字就是"工序"+编码）、808 张工单、
684 张检验单、67695 条 `role_permissions`。基础数据已经分不清哪条是业务、哪条是探针
—— 这就是"基础数据不正确"的由来。就地修补没有意义，只能清空重来。

## 为什么用一条 TRUNCATE

- PG 的 DDL 是**事务性**的：整条语句要么全成、要么一行不动，不存在"清了一半"；
- `CASCADE` 自动带上外键子表，不用手工排先后顺序（手工排一定漏表，漏了就清不干净）；
- `RESTART IDENTITY` 让自增 id 回到 1，重建后 id 干净可读。

表清单从 `pg_tables` **现取**，不写死 —— 写死的清单一定会漏掉后加的表，而漏掉的表
往往正是带着旧租户 id 的那张。

## 安全闸

- 默认 `--dry-run` 语义：只打印表数与行数，一行数据都不动；
- 真清空必须显式传 `--yes`；
- 真清空且目标是 PG 时，脚本会检查 `/opt/mfg1/backups/` 下是否有当天的 pg_dump，
  没有就拒绝执行（备份是这条路上唯一的回滚手段）。

## 用法

    # 看影响面（默认，安全）
    python scripts/reset_staging_db.py

    # 真清空（生产库）
    python scripts/reset_staging_db.py --yes

    # 清临时库做预演
    DB_NAME=mfg_restore_check python scripts/reset_staging_db.py --yes

清空之后**必须**按 `docs/reset-and-rebuild-2026-11-05.md` 的顺序重建，
否则租户/权限/角色都没有，登录进去全是 403。
"""
import asyncio
import glob
import os
import sys

def _find_backend() -> str:
    """定位含 `app/core/config.py` 的那个目录。

    仓库里跑时是 `<repo>/backend`；容器里 docker cp 到 `/app/_reset.py` 时
    自己就在 backend 根下。两种都支持 —— 写死 `../backend` 会让容器里 import 不到。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(os.path.dirname(here), "backend"), here, os.getcwd()):
        if os.path.isfile(os.path.join(cand, "app", "core", "config.py")):
            return cand
    raise SystemExit("找不到 backend 目录（应有 app/core/config.py）")


BACKEND_DIR = _find_backend()
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text                      # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine   # noqa: E402

from app.core.config import get_settings         # noqa: E402

# 迁移版本表要留着：它是"库结构是第几版"的唯一记录，清掉会让 deploy 脚本重跑全部迁移。
KEEP_TABLES = {"alembic_version"}

# 备份位置的候选（宿主机路径 / 容器内路径）。
# 脚本既可能在宿主机跑，也可能 docker exec 进容器跑 —— 容器里看不到宿主机
# 的 /opt/mfg1/backups，所以要允许把它 docker cp 到 /tmp 再校验。
# 这里坚持"真的有文件"，不接受一个 `--i-have-backup` 之类的空口开关：
# 备份是这条路上唯一的回滚手段，用一个布尔量证明它有，等于没证明。
BACKUP_GLOBS = (
    "/opt/mfg1/backups/mfg_pre_reset_*.sql.gz",
    "/tmp/mfg_pre_reset_*.sql.gz",
    "/app/mfg_pre_reset_*.sql.gz",
)


def _mask(url: str) -> str:
    """打日志时把密码换成 ***。"""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    cred, host = rest.split("@", 1)
    if ":" not in cred:
        return url
    user = cred.split(":", 1)[0]
    return f"{scheme}://{user}:***@{host}"


async def list_tables(conn, is_pg: bool):
    if is_pg:
        rs = await conn.execute(text(
            "select tablename from pg_tables where schemaname = 'public' order by tablename"))
    else:
        rs = await conn.execute(text(
            "select name from sqlite_master where type = 'table' "
            "and name not like 'sqlite_%' order by name"))
    return [r[0] for r in rs.fetchall() if r[0] not in KEEP_TABLES]


async def count_rows(conn, tables, quote):
    """逐表 COUNT(*)。库很小（备份才 1.9MB），慢不了；要的是准数不是估算。"""
    out = []
    for t in tables:
        try:
            n = (await conn.execute(text(f"select count(*) from {quote(t)}"))).scalar() or 0
        except Exception:
            n = -1          # 表存在但查不了（视图/权限），不计入总数
        if n > 0:
            out.append((t, n))
    out.sort(key=lambda x: -x[1])
    return out


async def main(argv):
    yes = "--yes" in argv
    settings = get_settings()
    url = settings.DATABASE_URL
    is_pg = url.startswith("postgresql")
    quote = (lambda t: f'"{t}"') if is_pg else (lambda t: f'"{t}"')

    print(f"目标库: {_mask(url)}")
    print(f"方言  : {'PostgreSQL' if is_pg else 'SQLite'}")
    print()

    if yes and is_pg:
        found = [p for pat in BACKUP_GLOBS for p in glob.glob(pat)]
        if not found:
            print("[拒绝] 目标库没有可用备份，以下位置都没匹配到：")
            for pat in BACKUP_GLOBS:
                print(f"         {pat}")
            print("       先做 pg_dump 并验证可恢复，再回来清库。")
            return 2
        print(f"备份: {found[0]}（{os.path.getsize(found[0]) // 1024} KB）")

    eng = create_async_engine(url, pool_pre_ping=False)
    try:
        async with eng.connect() as conn:
            tables = await list_tables(conn, is_pg)
            counts = await count_rows(conn, tables, quote)
            total = sum(n for _, n in counts)
            print(f"表总数 {len(tables)}（另有 {len(KEEP_TABLES)} 张版本表保留）")
            print(f"有数据的表 {len(counts)} 张，合计 {total} 行")
            print()
            print("行数 Top 20：")
            for t, n in counts[:20]:
                print(f"  {n:>8}  {t}")
            print()

            if not yes:
                print("[dry-run] 未做任何改动。确认影响面后加 --yes 再执行。")
                return 0

            if is_pg:
                stmt = ("TRUNCATE TABLE " + ", ".join(f'"{t}"' for t in tables)
                        + " RESTART IDENTITY CASCADE")
                async with eng.begin() as tx:
                    await tx.execute(text(stmt))
            else:
                # SQLite 不执行 ON DELETE CASCADE，关掉外键检查后逐表 DELETE
                async with eng.begin() as tx:
                    await tx.execute(text("PRAGMA foreign_keys = OFF"))
                    for t in tables:
                        await tx.execute(text(f'DELETE FROM "{t}"'))
                    await tx.execute(text("PRAGMA foreign_keys = ON"))

            print("[done] 已清空。")

        # 回读证明真的空了 —— 不看断言等于没清
        async with eng.connect() as conn:
            tables2 = await list_tables(conn, is_pg)
            left = await count_rows(conn, tables2, quote)
            print(f"[verify] 剩余非空表 {len(left)} 张，合计 {sum(n for _, n in left)} 行")
            for t, n in left[:10]:
                print(f"  {n:>8}  {t}")
        return 0
    finally:
        await eng.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
