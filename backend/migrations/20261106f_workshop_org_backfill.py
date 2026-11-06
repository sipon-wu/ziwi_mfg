#!/usr/bin/env python3
"""建"车间"组织层 + 把 33 个 `WC-AH-*` 工位归到车间（幂等）。

背景
----
`constants.modules.ORG_TYPES` 里 `workshop` 是合法组织类型，
`ORG_CHILD_TYPES[company] = (workshop, dept)` 也早写好了"公司→车间→部门/班组"
的层级白名单 —— 但**没有任何租户真的建过车间**（staging 艾华 32 条组织里
0 条 workshop，制造部 `AH-MFG` 下直接挂 4 条 team）。

结果 `work_centers.org_id`（列注释"所属组织ID"）33 行全为 NULL：
产能、OEE、安灯都只能按工位单点看，无法按车间聚合。

本迁移做两件事：
1. 在租户根公司下建两个车间（幂等，按 `uq_org_tenant_code` 复用）
2. 按工位编码把 33 个 `WC-AH-*` 的 `org_id` 指到对应车间

车间划分口径（2026-11-06 与客户对齐，来源《推进器生产工艺流程及数据采集表》）
--------------------------------------------------------------------
工艺卡工序序号 1~19 在**一般车间**、20~30 在**无尘车间**（序号 30「CW190 入库
终检包装」经确认并入无尘车间）。

映射到系统工位（车间归属看**工位所在的工序段**，不看工单）：

- 一般车间 19 个：定子线 7（CW010/020/030/035/040/050/060）+ 转子线 6
  （RT010~RT060）+ 总装前段 6（MA020/030/040/050/060/070，至三相端子焊接）
- 无尘车间 14 个：PCB 电装 6（FA040/020/030/035/070/080）+ 线外气密与注油 3
  （MA080/090/FA090）+ 固定架 1（FA1000）+ 下线测试 3（EL010/020/030）
  + 入库 1（CW190）

19 + 14 = 33，与租户内 `WC-AH-%` 工位数一致；脚本内置计数自检，
对不上直接报错退出（防止编码清单手抖后静默漏掉工位）。

为什么车间挂在**公司根节点**下而不是制造部下
--------------------------------------------
`ORG_CHILD_TYPES['dept'] = ('team',)` —— 部门下只允许挂班组，挂 workshop 会被
服务层拒绝。且车间是**空间维度**（这块区域洁净度多少），部门是**行政维度**
（这条线归谁管），两者正交。所以车间与制造部平级，是本系统的正确形态。
本次不动现有 team 层级（定子线/转子线/总装线/包装入库组仍挂制造部）。

★ 不要顺手把 `work_centers` 登记进 `ORG_SCOPED_TABLES`
---------------------------------------------------------
`work_centers.org_id` 是**业务属性**（这个工位归哪个车间管），不是数据范围。
登记进白名单会让「写入侧自动补成操作者自己的组织」+「车间主任按 DEPT_CHILD
看不到挂在公司根下的工位」两件事同时发生。详见 `constants/modules.py` 的
`EXCLUDED_FROM_ORG_SCOPE`。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261106f_workshop_org_backfill.py --tenant t_xxx --dry-run
    ./.venv/Scripts/python.exe migrations/20261106f_workshop_org_backfill.py --tenant t_xxx

`--tenant` 必填：本迁移会写 `organizations` 与 `work_centers`，不给租户等于全库扫描。
`--dry-run` 只打印计划，事务回滚。

★ 为什么 `--tenant` 缺失时**安静跳过**而不是报错退出
--------------------------------------------------
``deploy.sh`` 第 5 步会 `for m in /app/migrations/*.py; do python $m || true; done`
**无参数全量执行**一遍。本迁移若在缺参数时 argparse 直接 error，每次部署都会刷一段
红色 usage 到日志里，久了就没人看迁移日志了 —— 而"没人看日志"正是之前 5 个迁移
从未在 staging 上执行过的成因。所以缺参数时打印一行说明、返回 0，让日志保持干净。
"""
import argparse
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import bindparam, text  # noqa: E402


def _in_sql(sql: str):
    """把 ``IN :codes`` 变成可展开的参数（SQLAlchemy 2.0 必须显式声明）。

    不写 ``expanding=True`` 时，元组会被当成**一个标量**传下去，
    在 PG 上直接抛 "argument of IN must not be empty" / 类型不匹配；
    在 SQLite 上则是静默匹配 0 行 —— 后者更糟，迁移会打印"回填 0 行"而
    看起来像"本来就没数据"。
    """
    return text(sql).bindparams(bindparam("codes", expanding=True))

#: (编码, 名称, 排序, 备注) —— 车间节点
WORKSHOPS = [
    ("AH-WS-GEN", "一般车间", 10,
     "工艺卡工序序号 1~19：定子线 / 转子线 / 总装前段（至三相端子焊接）"),
    ("AH-WS-CLN", "无尘车间", 20,
     "工艺卡工序序号 20~30：PCB 电装 / 线外气密 / 注油 / 固定架 / EOL / 老化 / 入库"),
]

GEN_CODES = [
    # 定子线（序号 1~6）
    "WC-AH-CW010", "WC-AH-CW020", "WC-AH-CW030", "WC-AH-CW035",
    "WC-AH-CW040", "WC-AH-CW050", "WC-AH-CW060",
    # 转子线（序号 7~12）
    "WC-AH-RT010", "WC-AH-RT020", "WC-AH-RT030",
    "WC-AH-RT040", "WC-AH-RT050", "WC-AH-RT060",
    # 总装前段（序号 13~19）
    "WC-AH-MA020", "WC-AH-MA030", "WC-AH-MA040",
    "WC-AH-MA050", "WC-AH-MA060", "WC-AH-MA070",
]

CLN_CODES = [
    # PCB 电装（序号 20~24）
    "WC-AH-FA040", "WC-AH-FA020", "WC-AH-FA030", "WC-AH-FA035",
    "WC-AH-FA070", "WC-AH-FA080",
    # 线外测试 + 注油（序号 25~26）
    "WC-AH-MA080", "WC-AH-MA090", "WC-AH-FA090",
    # 固定架 + 标贴（序号 27）
    "WC-AH-FA1000",
    # 下线测试（序号 28~29）
    "WC-AH-EL010", "WC-AH-EL020", "WC-AH-EL030",
    # 入库终检包装（序号 30）—— 确认并入无尘车间
    "WC-AH-CW190",
]

#: 编码清单自检：数量写错就是漏工位，宁可当场炸掉
EXPECT = {"GEN": 19, "CLN": 14}


def _check_code_lists() -> None:
    for name, codes, expect in (
        ("GEN", GEN_CODES, EXPECT["GEN"]),
        ("CLN", CLN_CODES, EXPECT["CLN"]),
    ):
        dup = {c for c in codes if codes.count(c) > 1}
        if dup:
            raise SystemExit(f"[fatal] {name} 编码清单有重复：{sorted(dup)}")
        if len(codes) != expect:
            raise SystemExit(
                f"[fatal] {name} 应为 {expect} 个工位，实际 {len(codes)} 个"
            )
    overlap = set(GEN_CODES) & set(CLN_CODES)
    if overlap:
        raise SystemExit(f"[fatal] 两个车间抢同一个工位：{sorted(overlap)}")


async def _find_root(conn, tenant: str):
    """定位租户根公司。没有就退出 —— 本迁移不负责造根节点。"""
    res = await conn.execute(
        text(
            "SELECT id, code, name, path, level FROM organizations"
            " WHERE tenant_id = :t AND parent_id IS NULL"
            "   AND org_type = 'company' AND status = 'active'"
            " ORDER BY id LIMIT 1"
        ),
        {"t": tenant},
    )
    return res.mappings().first()


async def _ensure_workshop(conn, tenant: str, root, code: str, name: str,
                           sort_order: int, remark: str) -> int:
    """幂等拿到车间组织 id；不存在则建（path 在拿到自增 id 后回填）。"""
    res = await conn.execute(
        text("SELECT id FROM organizations WHERE tenant_id = :t AND code = :c"),
        {"t": tenant, "c": code},
    )
    row = res.first()
    if row:
        return int(row[0]), False

    level = int(root["level"]) + 1
    ins = await conn.execute(
        text(
            "INSERT INTO organizations"
            " (tenant_id, parent_id, code, name, org_type, path, level,"
            "  sort_order, status, remark)"
            " VALUES (:t, :p, :c, :n, 'workshop', :ph, :lv, :so, 'active', :rm)"
            " RETURNING id"
        ),
        {
            "t": tenant, "p": int(root["id"]), "c": code, "n": name,
            "ph": f"{root['path']}/pending", "lv": level,
            "so": sort_order, "rm": remark,
        },
    )
    new_id = int(ins.scalar())
    await conn.execute(
        text("UPDATE organizations SET path = :path WHERE id = :id"),
        {"path": f"{root['path']}/{new_id}", "id": new_id},
    )
    return new_id, True


async def apply(tenant: str, dry_run: bool) -> int:
    from app.core.database import get_engine

    engine = get_engine()
    total_changed = 0

    async with engine.begin() as conn:
        root = await _find_root(conn, tenant)
        if not root:
            print(f"[fatal] 租户 {tenant} 没有根公司组织（company / parent_id IS NULL）")
            print("        本迁移不造根节点。请先在组织管理里建公司根，再跑本脚本。")
            raise SystemExit(2)
        print(f"[info] 根公司：id={root['id']} code={root['code']} "
              f"name={root['name']} path={root['path']}")

        # ── 1. 车间节点 ──
        ws_ids = {}
        for code, name, so, remark in WORKSHOPS:
            oid, created = await _ensure_workshop(
                conn, tenant, root, code, name, so, remark)
            ws_ids[code] = oid
            print(f"[{'create' if created else 'reuse '}] 车间 {code} "
                  f"({name}) id={oid}")

        # ── 2. 工位归属 ──
        plan = [
            ("GEN", "AH-WS-GEN", "一般车间", GEN_CODES),
            ("CLN", "AH-WS-CLN", "无尘车间", CLN_CODES),
        ]
        for tag, ws_code, ws_name, codes in plan:
            target = ws_ids[ws_code]
            res = await conn.execute(
                _in_sql(
                    "SELECT id, code, org_id FROM work_centers"
                    " WHERE tenant_id = :t AND code IN :codes ORDER BY code"
                ),
                {"t": tenant, "codes": tuple(codes)},
            )
            rows = list(res.mappings())
            missing = sorted(set(codes) - {r["code"] for r in rows})
            todo = [r for r in rows if r["org_id"] != target]
            print(f"[info] {ws_name}：目标 {len(codes)} 个工位，"
                  f"库内命中 {len(rows)} 个，需更新 {len(todo)} 个")
            if missing:
                print(f"[warn] {ws_name}：库里没有这些工位编码 → {missing}")
            if todo:
                upd = await conn.execute(
                    _in_sql(
                        "UPDATE work_centers SET org_id = :oid"
                        " WHERE tenant_id = :t AND code IN :codes"
                        "   AND (org_id IS NULL OR org_id <> :oid)"
                    ),
                    {"oid": target, "t": tenant, "codes": tuple(codes)},
                )
                n = upd.rowcount or 0
                print(f"[apply] {ws_name}：回填 {n} 行 org_id → {target}")
                total_changed += n
            else:
                print(f"[skip ] {ws_name}：已全部归属完毕")

        # ── 3. 覆盖自检：还有没有 WC-AH-* 没归车间 ──
        res = await conn.execute(
            text(
                "SELECT COUNT(*) FROM work_centers"
                " WHERE tenant_id = :t AND code LIKE 'WC-AH-%' AND org_id IS NULL"
            ),
            {"t": tenant},
        )
        left = int(res.scalar() or 0)
        res = await conn.execute(
            text(
                "SELECT COUNT(*) FROM work_centers"
                " WHERE tenant_id = :t AND code LIKE 'WC-AH-%'"
            ),
            {"t": tenant},
        )
        total = int(res.scalar() or 0)
        print(f"[check] WC-AH-* 工位共 {total} 个，仍无车间归属 {left} 个")
        if left:
            res = await conn.execute(
                text(
                    "SELECT code FROM work_centers"
                    " WHERE tenant_id = :t AND code LIKE 'WC-AH-%'"
                    "   AND org_id IS NULL ORDER BY code"
                ),
                {"t": tenant},
            )
            print(f"[warn] 未归类：{[r[0] for r in res]}")

        if dry_run:
            raise _Rollback()

    await engine.dispose()
    return total_changed


class _Rollback(Exception):
    """dry-run 用：退出事务块即回滚。"""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=None,
                    help="租户 tenant_id（不是登录编码）；不传则跳过本迁移")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，事务回滚")
    args = ap.parse_args()

    if not args.tenant:
        print("[skip] 未指定 --tenant，跳过车间建模回填"
              "（deploy.sh 无参数全量执行迁移时会走到这里，属预期）")
        return 0

    _check_code_lists()

    try:
        n = asyncio.run(apply(args.tenant, args.dry_run))
    except _Rollback:
        print("[done] --dry-run：已回滚，未写入任何数据")
        return 0
    except SystemExit:
        raise
    except Exception as exc:
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0

    print(f"[done] 迁移完成，共更新 {n} 个工位的车间归属")
    return 0


if __name__ == "__main__":
    sys.exit(main())
