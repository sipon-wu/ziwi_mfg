#!/usr/bin/env python3
"""按租户整体清除：删掉一个租户的全部业务数据与身份数据，最后删租户行本身。

## 为什么要有这个脚本

2026-11-05 单租户收敛：用户要求「租户不就一个吗，推进器厂。帐号角色根据生产场景
需要创建就可以了」。staging 上除了 `AH-THR` 还有一个 `mfg_demo`（平台自带的演示/
回归库），62 张工单 + 16 条路线 + 43 道工序全是演示数据，会把覆盖检验的口径搞乱。

`reset_staging_db.py` 是全库清空，粒度太粗；`probe_artifacts.py` 只回收探针后缀，
对整租户无效。缺的是**按租户定点清除**。

## 为什么不能只删 tenants 那一行

各业务表都存 `tenant_id` 但没有外键（本库 123 张表只有 7 条 FK），删租户行**不会**
带掉任何业务数据，只会留下 60 多万行"查不到归属"的孤儿 —— 而多租户仓储是按
`tenant_id` 过滤的，孤儿永远看不见、永远没人清，等于把垃圾埋进库底。

## 三类表的处理

1. **有 `tenant_id` 的**：直接 `DELETE ... WHERE tenant_id = :t`，表清单从
   `information_schema` **现取**（写死的清单一定会漏掉后加的表）。
2. **没有 `tenant_id` 但通过角色关联的**：`role_permissions`。它只有
   `role_id/permission_id`，必须先按该租户的 `roles.id` 反查删掉，否则删 roles 会被
   外键挡住（这是全库仅有的 7 条 FK 之一）。
3. **完全没有归属线索的**：`change_log`（只有 table_name/row_id）。同步日志，删了
   不影响业务，留着也不会被任何查询读到 —— 脚本**不动它**，只在报告里说明。

## 安全闸

- 默认 **dry-run**；真删必须 `--yes`；
- **拒绝删掉最后一个租户**：删完库里必须还有别的租户，否则整个平台登录不了；
- PG 上要求 `/opt/mfg1/backups/` 里存在 **24 小时内的** `mfg_pre_*.sql.gz`——
  备份是这条路上唯一的回滚手段，不接受空口开关；
- 单事务；删完回读断言：该租户在所有表里归 0、**其他租户的行数与删前一致**。

## 用法

    # 看影响面（默认，安全）
    python scripts/purge_tenant.py --tenant mfg_demo

    # 真删
    python scripts/purge_tenant.py --tenant mfg_demo --yes

    # 清扫探针开的租户（回归跑完的收尾步骤，见下）
    python scripts/purge_tenant.py --probe-tenants
    python scripts/purge_tenant.py --probe-tenants --yes

    # 容器里
    docker cp scripts/purge_tenant.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/purge_tenant.py --tenant mfg_demo --yes

## 复跑一次回归就会多 3 个租户

`tenant_onboarding_e2e` / `perm_base_edge_e2e` / `tenant_role_preset_e2e` 每跑一次
就用 `strftime("%m%d%H%M%S")` 后缀**开一个新租户**（开通流程本身就得开租户，
那是被验证的功能，不是脏写）。它们不清理，于是 `/tenants` 越堆越多，
"库里只剩艾华"这个收官状态在每轮回归后失真。

`--probe-tenants` 就是这步收尾：编码匹配 `^(E2E|RP)[A-Za-z]*[0-9]{10}$` 的租户
全部按租户清除。**后缀锁死 10 位**（与 `probe_artifacts.py` 同一条教训：
放宽成 `{8,}` 会把 `20261105` 这类日期后缀的业务编码一起吃掉）。
单个租户仍走原来的四条安全闸，"不能删到只剩零个租户"由每条子命令各自校验。
"""
import argparse
import asyncio
import glob
import os
import re
import subprocess
import sys
import time

# ── 探针租户识别 ───────────────────────────────────────────────────────────
# 前缀取自三个探针实际用的编码（E2E1105115724 / RPfull1105115821 / RPqc…）；
# 末尾 10 位是 `strftime("%m%d%H%M%S")`，**位数固定**，不许模糊匹配。
PROBE_TENANT_RE = re.compile(r"^(E2E|RP)[A-Za-z]*[0-9]{10}$")

# ── 没有 tenant_id 列、但必须跟着租户一起清的"旁路"关系 ─────────────────────
# (要删的表, 过滤表达式)。表达式里的 :t 是 tenants.tenant_id 的取值。
SIDE_CLEANUP = [
    # 外键指向 roles，必须先于 roles 删；不删会因 FK 约束整条事务失败
    ("role_permissions",
     "role_id IN (select id from roles where tenant_id = :t)"),
]


def _find_backend() -> str:
    """定位含 `app/core/config.py` 的那个目录。

    仓库里跑时是 `<repo>/backend`；容器里 docker cp 到 `/app/scripts/` 时
    `here` 的上一级就是 `/app`。两种都要支持。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(os.path.dirname(here), "backend"), here,
                 os.path.dirname(here), os.getcwd()):
        if os.path.isfile(os.path.join(cand, "app", "core", "config.py")):
            return cand
    raise SystemExit("找不到 backend 目录（应有 app/core/config.py）")


BACKEND_DIR = _find_backend()
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text                      # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine   # noqa: E402

from app.core.config import get_settings         # noqa: E402

BACKUP_GLOB = "/opt/mfg1/backups/mfg_pre_*.sql.gz"
BACKUP_MAX_AGE_H = 24

# 备份位置的候选（宿主机 / 容器内）。
# 脚本既可能在宿主机跑，也可能 docker exec 进容器跑 —— 容器里看不到宿主机的
# /opt/mfg1/backups，所以允许先 `docker cp` 到容器 /tmp 再校验。
# 坚持"真的有文件"，不接受 `--i-have-backup` 之类的空口开关：备份是这条路
# 上唯一的回滚手段，用一个布尔量证明它有，等于没证明。
BACKUP_GLOBS = (
    "/opt/mfg1/backups/mfg_pre_*.sql.gz",
    "/tmp/mfg_pre_*.sql.gz",
    "/app/mfg_pre_*.sql.gz",
)


def _mask(url: str) -> str:
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    cred, host = rest.split("@", 1)
    if ":" not in cred:
        return url
    return f"{scheme}://{cred.split(':', 1)[0]}:***@{host}"


def _fresh_backup():
    """返回 24 小时内的备份路径；没有就返回 None。"""
    cands = [(p, os.path.getmtime(p)) for pat in BACKUP_GLOBS for p in glob.glob(pat)]
    cands = [c for c in cands if time.time() - c[1] < BACKUP_MAX_AGE_H * 3600]
    if not cands:
        return None
    return max(cands, key=lambda c: c[1])[0]


async def _tenant_tables(conn, is_pg: bool):
    """现取所有带 tenant_id 列的表名。"""
    if is_pg:
        rs = await conn.execute(text(
            "select table_name from information_schema.columns "
            "where table_schema='public' and column_name='tenant_id' "
            "order by table_name"))
    else:
        rs = await conn.execute(text(
            "select name from sqlite_master where type='table' "
            "and name not like 'sqlite_%' order by name"))
        out = []
        for r in rs.fetchall():
            cols = (await conn.execute(text(f'PRAGMA table_info("{r[0]}")'))).fetchall()
            if any(c[1] == "tenant_id" for c in cols):
                out.append(r[0])
        return out
    return [r[0] for r in rs.fetchall()]


async def _count(conn, sql: str, params: dict) -> int:
    return (await conn.execute(text(sql), params)).scalar() or 0


async def main(argv):
    ap = argparse.ArgumentParser(
        description="按租户整体清除（默认 dry-run）")
    ap.add_argument("--tenant",
                    help="tenant_id 或租户编码，如 mfg_demo / MFG1")
    ap.add_argument("--probe-tenants", action="store_true",
                    help="清扫探针开的租户（编码匹配 E2E*/RP* + 10 位时间后缀）")
    ap.add_argument("--yes", action="store_true", help="真的执行删除")
    ap.add_argument("--skip-backup-check", action="store_true",
                    help="跳过 24 小时备份检查（仅限刚 create_all 完的空库重建 / 本地演练）")
    ap.add_argument("--if-exists", action="store_true",
                    help="租户不存在时视为成功（重建链里的幂等收尾步骤用）")
    args = ap.parse_args(argv)

    if bool(args.tenant) == bool(args.probe_tenants):
        print("[拒绝] --tenant 与 --probe-tenants 必须二选一")
        return 2

    settings = get_settings()
    url = settings.DATABASE_URL
    is_pg = url.startswith("postgresql")

    print(f"目标库: {_mask(url)}")
    print(f"方言  : {'PostgreSQL' if is_pg else 'SQLite'}")
    print()

    eng = create_async_engine(url, pool_pre_ping=False)
    try:
        async with eng.connect() as conn:
            if args.probe_tenants:
                rows = (await conn.execute(text(
                    "select tenant_id, code, name from tenants "
                    "order by tenant_id"))).fetchall()
                targets = [r for r in rows if PROBE_TENANT_RE.match(r[1] or "")]
                keep = [r for r in rows if not PROBE_TENANT_RE.match(r[1] or "")]
                print(f"探针租户 {len(targets)} 个 / 保留 {len(keep)} 个")
                for t in targets:
                    print(f"      将清除  {t[0]} · {t[1]} · {t[2]}")
                for t in keep:
                    print(f"      保留    {t[0]} · {t[1]} · {t[2]}")
                if not targets:
                    print("\n没有匹配的探针租户，无需清扫。")
                    return 0
                if not keep:
                    # 同一条底线：扫完不能一个租户都不剩
                    print("\n[拒绝] 清扫后库里将没有任何租户，平台会登录不了。")
                    return 2
                if not args.yes:
                    print("\n[dry-run] 未做任何改动。核对无误后加 --yes 执行。")
                    return 0
                # 逐个委派给自己：单租户的四条安全闸（不能删到 0 个、
                # 备份存在性、单事务、删后回读 + 误伤校验）一条都不重写。
                print()
                rc = 0
                for tid, code, _name in targets:
                    cmd = [sys.executable, os.path.abspath(__file__),
                           "--tenant", code, "--yes"]
                    if args.skip_backup_check:
                        cmd.append("--skip-backup-check")
                    # 探针租户没有业务价值，但备份闸仍按参数决定，不在这里越权放开
                    r = subprocess.run(cmd, capture_output=True, text=True,
                                       encoding="utf-8", errors="replace")
                    tail = (r.stdout or "").strip().splitlines()[-1:] or ["(无输出)"]
                    print(f"  [{code}] rc={r.returncode} · {tail[0]}")
                    if r.returncode != 0:
                        rc = 1
                        print((r.stderr or "")[-400:])
                print()
                print(f"[结论] 探针租户清扫：目标 {len(targets)} 个 / rc={rc}"
                      + ("" if rc == 0 else "（有失败，见上）"))
                return rc

            row = (await conn.execute(text(
                "select tenant_id, code, name from tenants "
                "where tenant_id = :k or code = :k limit 1"), {"k": args.tenant})).first()
            if not row:
                if args.if_exists:
                    print(f"租户 {args.tenant!r} 不存在，无需清除（--if-exists）。")
                    return 0
                print(f"[拒绝] 租户 {args.tenant!r} 不存在（既不匹配 tenant_id 也不匹配 code）")
                return 2
            tid, code, name = row[0], row[1], row[2]

            others = (await conn.execute(text(
                "select tenant_id, code, name from tenants where tenant_id <> :t"), {"t": tid})).fetchall()
            if not others:
                # 删完就没有任何租户了 —— 平台会立刻登录不了，而且这个检查只能在这里做
                print(f"[拒绝] {tid} 是库里**唯一**的租户，删掉平台将无法登录。")
                return 2

            print(f"目标  : {tid} / {code} / {name}")
            # 本地库可能堆了几十个探针租户，全打出来没人看得懂 —— 只列前几个 + 总数
            others_show = "；".join(f"{o[0]}/{o[1]}" for o in others[:3])
            more = f" …（共 {len(others)} 个）" if len(others) > 3 else ""
            print(f"保留  : {others_show}{more}")
            print()

            if args.yes and is_pg and not args.skip_backup_check:
                bk = _fresh_backup()
                if not bk:
                    print(f"[拒绝] {BACKUP_MAX_AGE_H} 小时内没有备份，以下位置都没匹配到：")
                    for _p in BACKUP_GLOBS:
                        print(f"             {_p}")
                    print("       先做 pg_dump 并验证可恢复，再回来执行。")
                    return 2
                print(f"备份  : {bk}（{os.path.getsize(bk) // 1024} KB）")

            tables = await _tenant_tables(conn, is_pg)
            print(f"[1/4] 目标租户在各表的数据（共 {len(tables)} 张表带 tenant_id）")
            hits, total = [], 0
            for t in tables:
                n = await _count(conn, f'select count(*) from "{t}" where tenant_id = :t', {"t": tid})
                if n:
                    hits.append((t, n))
                    total += n
            hits.sort(key=lambda kv: -kv[1])
            for t, n in hits:
                print(f"      {t:<26} {n:>6} 行")
            print(f"      合计 {total} 行 / {len(hits)} 张表")

            side = []
            for tbl, expr in SIDE_CLEANUP:
                n = await _count(conn, f'select count(*) from "{tbl}" where {expr}', {"t": tid})
                if n:
                    side.append((tbl, n))
                    print(f"      {tbl:<26} {n:>6} 行（旁路：无 tenant_id 列）")

            if not hits and not side:
                print("      目标租户没有任何业务数据，只剩租户行。")

            if not args.yes:
                print()
                print("[dry-run] 未做任何改动。核对无误后加 --yes 执行。")
                return 0

            # 删前快照：其他租户的行数，删完必须一模一样
            baseline = {}
            for t in tables:
                baseline[t] = await _count(
                    conn, f'select count(*) from "{t}" where tenant_id <> :t', {"t": tid})

            print()
            print("[2/4] 执行删除（单事务）")
            deleted = []
            async with eng.begin() as tx:
                # ① 旁路表先删（外键指向 roles，必须先于 roles）
                for tbl, expr in SIDE_CLEANUP:
                    res = await tx.execute(text(f'delete from "{tbl}" where {expr}'), {"t": tid})
                    if res.rowcount:
                        deleted.append((tbl, res.rowcount))
                # ② 全部带 tenant_id 的表。
                #    顺序不敏感（业务表之间无外键），但 roles/users 必须在 user_roles、
                #    user_organizations 之后 —— 排序时把它们放最后。
                ordered = sorted(tables, key=lambda t: (t in ("roles", "users"), t))
                for t in ordered:
                    if t == "tenants":
                        continue        # 租户行单独在 ③ 删，避免重复计数
                    res = await tx.execute(
                        text(f'delete from "{t}" where tenant_id = :t'), {"t": tid})
                    if res.rowcount:
                        deleted.append((t, res.rowcount))
                # ③ 最后删租户行
                res = await tx.execute(
                    text("delete from tenants where tenant_id = :t"), {"t": tid})
                deleted.append(("tenants", res.rowcount))

            for t, n in deleted:
                print(f"      {t:<26} 删除 {n:>6} 行")
            print(f"      合计删除 {sum(n for _, n in deleted)} 行")

        # ---- 回读校验 ----
        print()
        print("[3/4] 回读校验：目标租户归零")
        bad = 0
        async with eng.connect() as conn:
            left = []
            for t in tables:
                n = await _count(conn, f'select count(*) from "{t}" where tenant_id = :t', {"t": tid})
                if n:
                    left.append((t, n))
            for tbl, expr in SIDE_CLEANUP:
                n = await _count(conn, f'select count(*) from "{tbl}" where {expr}', {"t": tid})
                if n:
                    left.append((tbl, n))
            n = await _count(conn, "select count(*) from tenants where tenant_id = :t", {"t": tid})
            if n:
                left.append(("tenants", n))

            if left:
                bad += 1
                print("      [FAIL] 仍有残留：")
                for t, n in left:
                    print(f"             {t} 剩 {n} 行")
            else:
                print(f"      [OK] {len(tables)} 张表 + {len(SIDE_CLEANUP)} 张旁路表 + tenants 全部归零")

            print()
            print("[4/4] 回读校验：其他租户未受影响")
            drift = []
            for t, expect in baseline.items():
                got = await _count(conn, f'select count(*) from "{t}" where tenant_id <> :t', {"t": tid})
                if got != expect:
                    drift.append((t, expect, got))
            if drift:
                bad += 1
                print("      [FAIL] 其他租户行数变了（误伤）：")
                for t, e, g in drift:
                    print(f"             {t} 应 {e} 实 {g}")
            else:
                print(f"      [OK] {len(baseline)} 张表的非目标租户行数一行不差")

            # change_log 只按 table_name/row_id 记账，没有 tenant_id，无法按租户清。
            # 留在这里，不会被任何按租户过滤的查询读到。
            cl = await _count(conn, "select count(*) from change_log", {})
            if cl:
                print(f"      注：change_log 共 {cl} 行（无 tenant_id 列，按设计不清）")

        print()
        if bad:
            print("[结论] 校验未通过，请检查上面 FAIL 项。")
            return 1
        print("[结论] 租户已清除，校验全通过。")
        return 0
    finally:
        await eng.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
