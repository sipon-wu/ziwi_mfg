#!/usr/bin/env python3
"""探针造数回收：把 E2E/边界用例跑完后留下的临时主数据与单据删干净。

## 为什么要有这个脚本

`e2e/basic_data_edge_e2e.py` 这类边界用例必须"造自己的数据才能测"——造新的产品、
新的路线、新的工单，测完不收拾。跑一轮留 7 个产品 / 5 条路线 / 5 张工单 / 4 道工序 /
2 个物料，再叠上 `route_steps`、`product_bom`、`bom_snapshots` 等子行，大约 43 行。

一轮看不出来，跑二十轮就是"基础数据里一半是垃圾"，而这正是 2026-11-05 清库的起因。
`reset_staging_db.py` 是核弹，解决不了"每周都要清一次"；缺的是**定点回收**。

## 探针数据的识别特征

探针为了不撞号，命名统一带 `-<时间戳>` 后缀，时间戳来自
`datetime.now().strftime("%m%d%H%M%S")`，即 **10 位数字**（如 `1105111153`
= 11-05 11:11:53）。

**为什么必须锁死 10 位**：种子数据里也有"带数字后缀"的合法编码，比如保养任务
`MT-1-20261105`（8 位日期）。放宽成 `{8,}` 会把它一起算成探针垃圾 —— 实测过一次，
误报 3 行保养任务 + 1 行 `users.cloud_uuid`。所以这里用 `{10}$` 并且**不做模糊放宽**。

## 为什么引用关系要手工登记

本库**几乎不用外键**（123 张表只有 7 条 FK，全在身份/权限/实验室那条线上）。业务表
之间靠 `<xxx>_id` / `<xxx>_code` 列名约定维持关系，删了父行不会报错，只会留孤儿。
所以下面 `REFS` 是一张**显式登记表**：哪张表的哪一列指向哪张根表的哪个键。
新增引用列时**必须往 `REFS` 里加一行**，否则那批子行会变成孤儿且永远不会被回收。

## 安全闸

1. 默认 **dry-run**：只打印命中清单与逐表计数，一行不动；
2. 真删必须 `--yes`；
3. 删除前先把"该保留的根行"（不匹配后缀的那些）id 存下来，删完逐条回读断言
   **一行不少** —— 这是唯一能证明"没误伤业务数据"的证据，光看打印清单不算；
4. 删除后断言根表里**不再有任何匹配行**，且 `REFS` 里的引用残留为 0；
5. 全流程一个事务，异常整体回滚。

## 个别根表不吃默认规则

跑完 48 个探针后，除了 `-<10位>` 这种统一后缀，还会留下**每个探针自己一套**的命名：
拆分/合并子单 `E2E-MG1-1105115414-M1`、仓储写实 `WO-W-115609`、SPC 闭环 `RW-NC-WR111`、
`closed_loop_test` 的 `WO_20261105121007_c45196_1`、权限探针的账号 `tmpu1105115407`
（前缀直接接时间戳，没有分隔符）。这些由 `ROOT_PATTERNS` **逐表列举**补上，
每条都对应一个具体探针源码里的命名，不写"看起来像"的通配。

## `organizations` 为什么不在这张清单里

平台底座探针会在组织树里挂 `DEPT-<ts>` / `TEAM-<ts>` 叶子节点（每轮 8 个）。
本工具**不动它们**：组织是结构数据，业务行靠 `org_id` 指过去，删节点会留下
一批"归属指向不存在的组织"的行，而那类孤儿正是 `purge_tenant.py` 覆盖、
本工具覆盖不到的地方。要清得单独写一条"节点无引用才可删"的守卫。

## 用法

    # 看影响面（默认，安全）
    python scripts/probe_artifacts.py

    # 只看某个后缀
    python scripts/probe_artifacts.py --suffix 1105111153

    # 只清某个租户（推荐：清艾华前先确认 mfg_demo 的演示数据别被带走）
    python scripts/probe_artifacts.py --tenant AH-THR

    # 真删
    python scripts/probe_artifacts.py --tenant AH-THR --yes

## 容器里怎么跑

宿主机 backend 目录在容器里是 `/app`，脚本本身可以直接 `docker cp` 进去：

    docker cp scripts/probe_artifacts.py mfg1-db:/tmp/     # 只是中转
    docker cp scripts/probe_artifacts.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/probe_artifacts.py --tenant AH-THR
"""
import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict


def _find_backend() -> str:
    """定位含 `app/core/config.py` 的那个目录。

    仓库里跑时是 `<repo>/backend`；容器里 docker cp 到 `/app/scripts/` 时
    `here` 的上一级就是 `/app`。两种都要支持 —— 写死 `../backend` 会让容器里 import 不到。
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

# 探针后缀：`-` 或 `_` 接 10 位数字收尾。10 位是硬约束，理由见模块 docstring。
DEFAULT_PATTERN = r"[-_][0-9]{10}$"

# 根表：探针直接创建、带自己编码的那些表。
# (表名, 编码列, 人类可读名, id 列)
ROOTS = [
    ("work_orders",    "wo_no", "工单",  "id"),
    ("process_routes", "code",  "工艺路线", "id"),
    ("products",       "code",  "产品",  "id"),
    ("operations",     "code",  "工序",  "id"),
    ("materials",      "code",  "物料",  "id"),
    ("work_centers",   "code",  "工作中心", "id"),
    ("roles",          "code",  "角色",  "id"),
    ("users",          "username", "账号", "id"),
]

# 个别根表的编码形态与 `[-_]<10位>` 不同，单独给规则（**逐表覆盖，不合并**）。
#
# `users` 为什么不能套用默认规则：权限探针建的账号是 `tmpu1105115407` 这种
# 「前缀 + 直接接 10 位时间戳」，**中间没有分隔符**，默认规则一条都匹配不上；
# 反过来若把默认规则放宽成"结尾 10 位数字"，`users.cloud_uuid` 那类值会被误伤
# （见模块 docstring 里 `{8,}` 的教训）。所以这里**不猜格式，只认白名单前缀**：
# 前缀全部取自探针源码里实际用的用户名，没在名单里的账号一律不动。
#
# 其余几张表的补充规则同理：每一条都对应一个**具体探针源码里的命名**，
# 不是"看起来像探针"。列举时只写能唯一指认探针的前缀/形状，绝不写
# `^WO-` 这种会把场景种子一起卷进去的通配。
ROOT_PATTERNS = {
    "users": [r"^(tmpu|rouser|busyu|idleu|delu|delidle|norole|emptyu|"
              r"inspector_|probe_|e2e_)[a-z_]*[0-9]{10}$"],
    "work_orders": [
        # 拆分/合并的子单：`E2E-MG1-1105115414-M1`、`WO-DUP-1105115428-B`
        r"[-_][0-9]{10}-[A-Z][0-9]?$",
        # 整类前缀就是探针的：`E2E-SP-*` / `E2E-MG*` / `WO-E2E-*`
        r"^E2E[-_]",
        # 仓储写实：`WO-W-115609`
        r"^WO-W-[0-9]{6}$",
        # SPC/NCR 闭环：`RW-NC-WR111`
        r"^RW-NC-WR[0-9]+$",
        # closed_loop_test：`WO_20261105121007_c45196_1`
        r"^WO_[0-9]{14}_[0-9a-f]+_[0-9]+$",
        # 自动编号：`WO-20261105-115506`
        r"^WO-[0-9]{8}-[0-9]{6}$",
    ],
    "products": [
        r"^E2E[-_]",              # `E2E-FG-001`
        r"^GE[0-9]{11}$",         # `GE3` + 10 位时间戳（edge 探针）
    ],
    "materials": [
        r"^E2E[-_]",              # `E2E-MAT` / `E2E-TRACE-*` / `E2E_LOOP_*`
        r"^P-E2E$",               # 工单生命周期探针的成品
        r"^MAT-TC4-[0-9]{6}$",    # 批次追溯探针
    ],
    "process_routes": [
        r"^RTE-P-GE-[0-9]+-V[0-9]+$",   # 路线编辑探针的版本拷贝
        r"^RT-TS-[0-9]{6}$",            # trial 探针
    ],
}


#: 这些表的专用规则**取代**默认规则，不与之合并（账号就是这样：只认前缀白名单，
#: 不给"结尾 10 位数字"任何机会）。其余表是"默认规则 + 补充规则"取并集。
ROOT_EXCLUSIVE = {"users"}

#: `--suffix` 模式（人工指定精确后缀）下专用规则全部退场，只按给定后缀匹配 ——
#: 否则"只清这一批"会被白名单规则扩大成"清掉所有探针账号"。
_SUFFIX_MODE = False


def _rx_for(tbl: str, fallback: re.Pattern) -> re.Pattern:
    """取该根表适用的正则：默认规则 ∪ 补充规则（exclusive 表只用补充规则）。"""
    if _SUFFIX_MODE:
        return fallback
    pats = ROOT_PATTERNS.get(tbl)
    if not pats:
        return fallback
    alts = [f"(?:{p})" for p in pats]
    if tbl not in ROOT_EXCLUSIVE:
        alts.insert(0, f"(?:{fallback.pattern})")
    return re.compile("|".join(alts))

# 打印明细时补一列区分同码多行 —— `RT-S3-*` 有 v1/v2 两条，只打编码会看成重复命中。
DISPLAY_EXTRA = {
    "process_routes": "version",
    "work_orders": "wo_status",
}

# 引用登记表：(子表, 子表列, 根表, 根表键列)。
# 顺序即删除顺序 —— 先子后父。本库无外键，顺序不会报错，但会决定"删完还剩多少孤儿"。
REFS = [
    ("route_steps",             "route_id",       "process_routes", "id"),
    ("route_steps",             "operation_id",   "operations",     "id"),
    ("product_bom",             "product_id",     "products",       "id"),
    ("product_bom",             "material_code",  "materials",      "code"),
    ("bom_snapshots",           "work_order_id",  "work_orders",    "id"),
    ("work_order_status_logs",  "work_order_id",  "work_orders",    "id"),
    ("work_reports",            "work_order_id",  "work_orders",    "id"),
    ("work_reports",            "operation_code", "operations",     "code"),
    ("issue_orders",            "work_order_id",  "work_orders",    "id"),
    ("receipt_orders",          "work_order_id",  "work_orders",    "id"),
    ("material_requests",       "work_order_id",  "work_orders",    "id"),
    ("inspection_order",        "work_order_id",  "work_orders",    "id"),
    ("andon_call",              "work_order_id",  "work_orders",    "id"),
    ("equipment_downtimes",     "work_order_id",  "work_orders",    "id"),
    ("maintenance_tasks",       "work_order_id",  "work_orders",    "id"),
    ("ncr_records",             "work_order_id",  "work_orders",    "id"),
    ("product_versions",        "product_id",     "products",       "id"),
    ("product_routes",          "product_id",     "products",       "id"),
    ("product_routes",          "route_id",       "process_routes", "id"),
    ("process_routes",          "source_route_id", "process_routes", "id"),
    ("trial_orders",            "source_route_id", "process_routes", "id"),
    ("trial_routes",            "source_route_id", "process_routes", "id"),
    ("ppap_submissions",        "product_id",     "products",       "id"),
    ("fmea_documents",          "product_id",     "products",       "id"),
    ("fmea_hierarchies",        "operation_id",   "operations",     "id"),
    ("inventory",               "material_id",    "materials",      "id"),
    ("inventory_transactions",  "material_id",    "materials",      "id"),
    ("inventory_items",         "material_code",  "materials",      "code"),
    ("inventory_alerts",        "material_id",    "materials",      "id"),
    ("inventory_count_items",   "material_id",    "materials",      "id"),
    ("batches",                 "material_id",    "materials",      "id"),
    ("inspection_order",        "material_id",    "materials",      "id"),
    ("qc_point_config",         "material_id",    "materials",      "id"),
    ("receipt_order_items",     "material_id",    "materials",      "id"),
    ("issue_order_items",       "material_id",    "materials",      "id"),
    ("material_request_items",  "material_id",    "materials",      "id"),
    ("material_substitutes",    "material_id",    "materials",      "id"),
    ("material_substitutes",    "material_code",  "materials",      "code"),
    ("ncr_records",             "material_id",    "materials",      "id"),
    ("customer_complaints",     "product_code",   "products",       "code"),
    # 账号是"根"的一种：探针建的账号要连角色关联一起清，否则 users 删了、
    # user_roles 留着，角色页上会显示"该角色有 N 个成员"但点开是空名单。
    ("user_roles",              "user_id",        "users",          "id"),
    ("user_organizations",      "user_id",        "users",          "id"),
    # 角色同理，而且 role_permissions 是全库仅有的 7 条外键之一 ——
    # 不先删它会直接 FK 报错，整条事务回滚。
    ("role_permissions",        "role_id",        "roles",          "id"),
    ("user_roles",              "role_id",        "roles",          "id"),
]


def _mask(url: str) -> str:
    """打日志时把密码换成 ***。"""
    if "@" not in url or "://" not in url:
        return url
    scheme, rest = url.split("://", 1)
    cred, host = rest.split("@", 1)
    if ":" not in cred:
        return url
    return f"{scheme}://{cred.split(':', 1)[0]}:***@{host}"


async def _table_exists(conn, name: str, is_pg: bool) -> bool:
    if is_pg:
        n = (await conn.execute(text(
            "select count(*) from information_schema.tables "
            "where table_schema='public' and table_name=:t"), {"t": name})).scalar()
    else:
        n = (await conn.execute(text(
            "select count(*) from sqlite_master where type='table' and name=:t"),
            {"t": name})).scalar()
    return bool(n)


async def _column_exists(conn, table: str, column: str, is_pg: bool) -> bool:
    if is_pg:
        n = (await conn.execute(text(
            "select count(*) from information_schema.columns "
            "where table_schema='public' and table_name=:t and column_name=:c"),
            {"t": table, "c": column})).scalar()
    else:
        rs = await conn.execute(text(f'PRAGMA table_info("{table}")'))
        return any(r[1] == column for r in rs.fetchall())
    return bool(n)


async def _resolve_tenant(conn, key: str) -> str:
    """把 `AH-THR` / `t_xxxx` 归一成 `tenants.tenant_id`。

    与 `UserRepository.resolve_login_tenant` 同一口径：客户手上只有租户编码，
    服务端存的是 `t_xxxx`。这里查不到就直接退出，不猜。
    """
    row = (await conn.execute(text(
        "select tenant_id from tenants where tenant_id=:k or code=:k limit 1"),
        {"k": key})).first()
    if not row:
        raise SystemExit(f"[拒绝] 租户 {key!r} 在 tenants 表里不存在（既不匹配 tenant_id 也不匹配 code）")
    return row[0]


async def discover(conn, is_pg: bool, rx: re.Pattern, tenant_id):
    """找出所有探针根行。

    匹配放在 **Python 侧**做，不用 SQL 正则：PG 是 `~`、SQLite 要注册 REGEXP 函数，
    两套写法容易只在一个方言上生效。根表都不大（全库才 4 千行），拉回来过滤最稳。
    """
    where, params = "", {}
    if tenant_id:
        where, params = " where tenant_id = :tid", {"tid": tenant_id}

    hits = {}          # 表 -> [[id, 编码, 展示串], ...]
    for tbl, code_col, label, id_col in ROOTS:
        if not await _table_exists(conn, tbl, is_pg):
            print(f"  [跳过] 表 {tbl} 不存在")
            continue
        rxx = _rx_for(tbl, rx)
        extra = DISPLAY_EXTRA.get(tbl)
        sel = f'"{id_col}", "{code_col}"' + (f', "{extra}"' if extra else "")
        rs = await conn.execute(text(f'select {sel} from "{tbl}"{where}'), params)
        rows = []
        for r in rs.fetchall():
            code = r[1]
            if not (code and rxx.search(str(code))):
                continue
            disp = str(code) + (f" ({r[2]})" if extra and r[2] is not None else "")
            rows.append([r[0], code, disp])
        if rows:
            hits[tbl] = rows
            print(f"  {label:<6} {tbl:<16} {len(rows):>3} 行")
    return hits


async def count_refs(conn, is_pg: bool, hits: dict):
    """统计每个引用列上挂了多少行（只看子表，不含根表自身）。"""
    root_ids = {t: [r[0] for r in v] for t, v in hits.items()}
    root_codes = {t: [r[1] for r in v] for t, v in hits.items()}
    out = []           # (子表, 子列, 根表, 行数)
    for tbl, col, root, root_key in REFS:
        if root not in hits:
            continue
        if not await _table_exists(conn, tbl, is_pg):
            continue
        if not await _column_exists(conn, tbl, col, is_pg):
            continue
        vals = root_ids[root] if root_key == "id" else root_codes[root]
        if not vals:
            continue
        # 参数化 IN：占位符按方言生成，值走绑定，不拼字符串
        names = [f"v{i}" for i in range(len(vals))]
        ph = ", ".join(f":{n}" for n in names)
        params = dict(zip(names, vals))
        n = (await conn.execute(
            text(f'select count(*) from "{tbl}" where "{col}" in ({ph})'), params)).scalar() or 0
        if n:
            out.append((tbl, col, root, n))
    return out


async def main(argv):
    ap = argparse.ArgumentParser(
        description="回收 E2E 探针留下的临时主数据与单据（默认 dry-run）")
    ap.add_argument("--yes", action="store_true", help="真的执行删除（不加只打印）")
    ap.add_argument("--suffix", action="append", default=None,
                    help="只清指定后缀，如 1105111153（可重复）；不给则按 10 位时间戳规则自动发现")
    ap.add_argument("--tenant", default=None,
                    help="限定租户（tenant_id 或租户编码，如 AH-THR）；不给则全库扫")
    args = ap.parse_args(argv)

    global _SUFFIX_MODE
    _SUFFIX_MODE = bool(args.suffix)
    if args.suffix:
        # 显式后缀：精确尾匹配，零误报。给多个时用 | 拼。
        pattern = r"[-_](" + "|".join(re.escape(s) for s in args.suffix) + r")$"
        label = "指定后缀 " + " / ".join(args.suffix)
    else:
        pattern = DEFAULT_PATTERN
        label = f"自动规则 {pattern}"
    rx = re.compile(pattern)

    settings = get_settings()
    url = settings.DATABASE_URL
    is_pg = url.startswith("postgresql")

    print(f"目标库: {_mask(url)}")
    print(f"方言  : {'PostgreSQL' if is_pg else 'SQLite'}")
    print(f"识别  : {label}")
    if not _SUFFIX_MODE:
        for _t, _p in ROOT_PATTERNS.items():
            print(f"        （{_t} 专用）" + " | ".join(_p))
    print()

    eng = create_async_engine(url, pool_pre_ping=False)
    try:
        async with eng.connect() as conn:
            tenant_id = None
            if args.tenant:
                tenant_id = await _resolve_tenant(conn, args.tenant)
                print(f"租户  : {args.tenant} → {tenant_id}")
                print()

            print("[1/4] 发现探针根行")
            hits = await discover(conn, is_pg, rx, tenant_id)
            if not hits:
                print("      没有命中，库里是干净的。")
                return 0
            total_root = sum(len(v) for v in hits.values())
            print(f"      合计 {total_root} 行根数据")

            print()
            print("[2/4] 统计引用行（子表）")
            refs = await count_refs(conn, is_pg, hits)
            if refs:
                for tbl, col, root, n in refs:
                    print(f"      {tbl:<24} .{col:<16} → {root:<15} {n:>3} 行")
            else:
                print("      没有子表引用")
            total_refs = sum(n for *_, n in refs)

            # 明细：让人能肉眼核对到底删哪些，而不是只看计数
            print()
            print("      命中明细：")
            for tbl, code_col, label_, _id in ROOTS:
                for _rid, _code, disp in hits.get(tbl, []):
                    print(f"        {tbl:<16} {disp}")

            print()
            # 这里说的是"按列计的命中行"，不是"将被删的唯行数"：同一行可能同时命中
            # 两列（route_steps 既有 route_id 也有 operation_id 指向探针数据），
            # 真删时第二列 rowcount 为 0，实际删除数看 [3/4] 的回读。
            print(f"      引用命中（按列计，同表多列可能重复计）：{total_refs} 行")

            if not args.yes:
                print()
                print("[dry-run] 未做任何改动。核对无误后加 --yes 执行。")
                return 0

            # ---- 删除前快照「必须保留的行」，删完逐条回读 ----
            keep = {}
            for tbl, code_col, _label, id_col in ROOTS:
                where, params = "", {}
                if tenant_id:
                    where, params = " where tenant_id = :tid", {"tid": tenant_id}
                rxx = _rx_for(tbl, rx)
                rs = await conn.execute(
                    text(f'select "{id_col}", "{code_col}" from "{tbl}"{where}'), params)
                keep[tbl] = {r[0] for r in rs.fetchall()
                             if not (r[1] and rxx.search(str(r[1])))}

            print()
            print("[3/4] 执行删除（单事务）")
            deleted = defaultdict(int)
            async with eng.begin() as tx:
                def _del(sql, params):
                    return tx.execute(text(sql), params)

                # 先子后父：REFS 顺序即删除顺序，这里按登记表逐条删
                for tbl, col, root, root_key in REFS:
                    if root not in hits:
                        continue
                    if not await _table_exists(tx, tbl, is_pg):
                        continue
                    if not await _column_exists(tx, tbl, col, is_pg):
                        continue
                    vals = ([r[0] for r in hits[root]] if root_key == "id"
                            else [r[1] for r in hits[root]])
                    if not vals:
                        continue
                    names = [f"v{i}" for i in range(len(vals))]
                    ph = ", ".join(f":{n}" for n in names)
                    res = await _del(
                        f'delete from "{tbl}" where "{col}" in ({ph})',
                        dict(zip(names, vals)))
                    if res.rowcount:
                        deleted[tbl] += res.rowcount

                # 再删根表（按 ROOTS 顺序，工单在最前 —— 它引用了产品和路线）
                for tbl, code_col, _label, id_col in ROOTS:
                    if tbl not in hits:
                        continue
                    vals = [r[0] for r in hits[tbl]]
                    names = [f"v{i}" for i in range(len(vals))]
                    ph = ", ".join(f":{n}" for n in names)
                    res = await _del(
                        f'delete from "{tbl}" where "{id_col}" in ({ph})',
                        dict(zip(names, vals)))
                    deleted[tbl] += res.rowcount

            for tbl, n in sorted(deleted.items(), key=lambda kv: -kv[1]):
                print(f"      {tbl:<24} 删除 {n:>3} 行")
            print(f"      合计删除 {sum(deleted.values())} 行")

        # ---- 回读校验：不看断言等于没删 ----
        print()
        print("[4/4] 回读校验")
        bad = 0
        async with eng.connect() as conn:
            left = await discover(conn, is_pg, rx, tenant_id)
            if left:
                bad += 1
                print(f"      [FAIL] 仍残留 {sum(len(v) for v in left.values())} 行根数据")
                for tbl, rows in left.items():
                    for _rid, _code, disp in rows:
                        print(f"             {tbl} {disp}")
            else:
                print("      [OK] 根表已无匹配行")

            for tbl, keep_ids in keep.items():
                if not keep_ids:
                    continue
                names = [f"v{i}" for i in range(len(keep_ids))]
                ph = ", ".join(f":{n}" for n in names)
                id_col = next(c[3] for c in ROOTS if c[0] == tbl)
                n = (await conn.execute(
                    text(f'select count(*) from "{tbl}" where "{id_col}" in ({ph})'),
                    dict(zip(names, list(keep_ids))))).scalar() or 0
                if n != len(keep_ids):
                    bad += 1
                    print(f"      [FAIL] {tbl} 保留行少了 {len(keep_ids) - n} 行"
                          f"（应 {len(keep_ids)} 实 {n}）—— 误伤，需从备份恢复")
            if not bad:
                print(f"      [OK] 业务数据完整：{sum(len(v) for v in keep.values())} 行根数据一行不少")

            residue = await count_refs(conn, is_pg, hits)
            if residue:
                bad += 1
                print("      [FAIL] 仍有子表引用探针数据：")
                for tbl, col, root, n in residue:
                    print(f"             {tbl}.{col} → {root} 剩 {n} 行")
            else:
                print("      [OK] 子表无悬空引用")

        print()
        if bad:
            print("[结论] 校验未通过，请检查上面 FAIL 项。")
            return 1
        print("[结论] 清理完成，校验全通过。")
        return 0
    finally:
        await eng.dispose()


if __name__ == "__main__":
    sys.exit(asyncio.run(main(sys.argv[1:])))
