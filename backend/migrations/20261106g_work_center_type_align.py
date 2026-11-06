#!/usr/bin/env python3
"""按「工位承担工序的工艺性质」对齐 `work_centers.wc_type`（幂等）。

背景
----
`wc_type` 一直被当"工艺性质"手填，但它其实是 `operations.op_type` 的副本。
2026-11-06 对账（AH 33 个工位）：28 个恰好一致，**3 个有唯一主类型却不一致**：

| 工位 | 档案填的 | 工序实为 | 步数 |
|:--|:--|:--|:--|
| `WC-AH-CW060` 热套工位 | machining | heat_treat | 1 |
| `WC-AH-CW040` 灌胶区 | machining | heat_treat | heat_treat 5 : machining 2 |
| `WC-AH-FA070` PCB灌胶工位 | assembly | heat_treat | 1 |

（另有 `CW050 定子电检`、`RT040 动平衡` 是 1:1 并列，**没有主类型**，
本迁移有意不动 —— 硬挑一个只是把不确定性藏起来，界面会显示「混合」。）

改完之后，列表页的「类型」列走**派生值**（`services/work_center_nature.py`），
`wc_type` 降为档案兜底值。两者一旦再次分叉，界面标「待核对」而不是静默取一个。

★ 为什么不是"改这几行 SQL 就完事"
--------------------------------
写下 4 条 UPDATE 明天就又漂了。这里的口径是：**从工序反推**，谁不一致改谁。
将来工序调整了，重跑本脚本即可对齐；跑一次不该产生第二次写入（幂等自检）。
真正防止再漂的是 `wc_type_conflict` 那个标记 —— 它不依赖任何人记得跑脚本。

用法
----
    cd backend
    ./.venv/Scripts/python.exe migrations/20261106g_work_center_type_align.py --tenant t_xxx --dry-run
    ./.venv/Scripts/python.exe migrations/20261106g_work_center_type_align.py --tenant t_xxx

`--tenant` 缺失时**安静跳过返回 0**：`deploy.sh` 会无参数全量执行一遍 migrations，
缺参数就刷 usage 会让迁移日志更快变成没人看的东西。
"""
import argparse
import asyncio
import os
import sys
from collections import defaultdict

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text  # noqa: E402

#: op_type → 工艺性质。与 `app/core/work_center_nature.py::OP_TYPE_TO_NATURE`
#: 同一口径；迁移里不 import app 层，避免部署时 app 尚未可导入导致脚本炸掉。
#: 两边一致性由 `app/tests/test_work_center_nature.py` 断言（读本文件比对）。
OP_TYPE_TO_NATURE = {
    "inspect": "quality",
    "incoming_qc": "quality",
    "process_qc": "quality",
    "final_qc": "quality",
}


class _Rollback(Exception):
    pass


def _nature_of(op_type: str) -> str:
    return OP_TYPE_TO_NATURE.get(op_type, op_type)


async def _load_steps(conn, tenant: str) -> dict:
    """{wc_id: [(nature, steps), ...]}"""
    res = await conn.execute(
        text(
            "SELECT rs.wc_id AS wc_id, o.op_type AS op_type, COUNT(*) AS steps"
            " FROM route_steps rs"
            " JOIN operations o ON o.id = rs.operation_id"
            " WHERE rs.tenant_id = :t"
            " GROUP BY rs.wc_id, o.op_type"
        ),
        {"t": tenant},
    )
    out = defaultdict(lambda: defaultdict(int))
    for r in res.mappings():
        out[r["wc_id"]][_nature_of(r["op_type"])] += int(r["steps"])
    return {k: sorted(v.items(), key=lambda kv: (-kv[1], kv[0])) for k, v in out.items()}


def _primary(counts: list) -> tuple:
    """返回 (主类型 or None, 并列第一的类型列表)。"""
    if not counts:
        return None, []
    top = counts[0][1]
    leaders = [n for n, c in counts if c == top]
    return (leaders[0] if len(leaders) == 1 else None), leaders


async def apply(tenant: str, dry_run: bool) -> tuple:
    from app.core.database import get_engine

    engine = get_engine()
    changed = 0
    ties = []
    no_wc_steps = 0

    async with engine.begin() as conn:
        steps = await _load_steps(conn, tenant)
        res = await conn.execute(
            text(
                "SELECT id, code, name, wc_type FROM work_centers"
                " WHERE tenant_id = :t ORDER BY code"
            ),
            {"t": tenant},
        )
        rows = list(res.mappings())
        print(f"[info] 租户 {tenant}：工位 {len(rows)} 个，其中有工序的 "
              f"{len([r for r in rows if r['id'] in steps])} 个")

        plan = []
        for r in rows:
            counts = steps.get(r["id"]) or []
            if not counts:
                no_wc_steps += 1
                continue
            primary, leaders = _primary(counts)
            if primary is None:
                ties.append((r["code"], r["name"], r["wc_type"], leaders))
                continue
            if r["wc_type"] != primary:
                plan.append((r["id"], r["code"], r["name"], r["wc_type"], primary))

        for row in plan:
            print(f"[align] {row[1]} ({row[2]})：{row[3]} → {row[4]}")
        for code, name, stored, leaders in ties:
            print(f"[skip ] {code} ({name})：并列第一 {leaders}，"
                  f"无主类型，保留档案值 {stored}（界面显示「混合」）")
        if no_wc_steps:
            print(f"[skip ] {no_wc_steps} 个工位还没挂工序，保留档案值作兜底")

        if plan and not dry_run:
            for wid, code, _name, old, new in plan:
                await conn.execute(
                    text(
                        "UPDATE work_centers SET wc_type = :new"
                        " WHERE id = :id AND tenant_id = :t AND wc_type = :old"
                    ),
                    {"new": new, "id": wid, "t": tenant, "old": old},
                )
                changed += 1

        if dry_run:
            raise _Rollback()

    return changed, plan, ties


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default=None,
                    help="租户 tenant_id（不是登录编码）；不传则跳过本迁移")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，事务回滚")
    args = ap.parse_args()

    if not args.tenant:
        print("[skip] 未指定 --tenant，跳过工位类型对齐"
              "（deploy.sh 无参数全量执行迁移时会走到这里，属预期）")
        return 0

    try:
        changed, plan, ties = asyncio.run(apply(args.tenant, args.dry_run))
    except _Rollback:
        print("[done] --dry-run：已回滚，未写入任何数据")
        return 0
    except Exception as exc:  # 迁移不阻断部署
        print(f"[error] 迁移失败（不阻断部署）: {exc}")
        return 0

    print(f"[done] 对齐 {changed} 个工位的类型；"
          f"并列无主类型 {len(ties)} 个（有意保留）；"
          f"计划内共 {len(plan)} 条")
    return 0


if __name__ == "__main__":
    sys.exit(main())
