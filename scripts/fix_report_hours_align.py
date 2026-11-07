"""订正 5–10 月存量报工工时：让「人工工时」不再与「设备机时」逐行相等。

为什么是数据订正，不是改报表
----------------------------
报表聚合本身是对的（`production_repo.py` 分别 `SUM(wr.labor_hours)` 与
`SUM(wr.machine_hours)`）。staging AH-THR 的 R9 连续 6 个月报「两者精确相等」，
根因在**数据**：旧的半年串跑器把两列写成了同一个表达式（见
`e2e/_report_hours.py` 开头）。串跑器早已改用 ``hours_for``，但 2026-05~10
的存量流水没跟着重算 —— 2026-11 之后新写的流水已经不等了，正好形成对照。

口径不从这里定义
----------------
``labor - machine == setup_time / 60`` 这条关系是 `_report_hours.py::hours_for`
的**代数变形**，不是本脚本另写一份实现：构造 ``unit_time=60`` 的虚拟 seg、
``qty = 已存 machine_hours``，则 ``hours_for`` 给出的 machine 恰好等于已存值，
labor 就是应有值。口径若被改坏，本脚本的 ``selftest()`` 会先报红。

只订正能无损还原的行
--------------------
- 区间内、两列相等、``machine_hours > 0``；
- ``operation_code`` 非空且能在 ``operations`` 表里查到；
- 该工序 ``setup_time > 0``。
其余一律跳过并计数上报：**operation_code 为空的老单（合法形态）无法关联工序，
不做猜测性赋值**；零工时的占位流水、无换型工序的合法相等同样不动。

幂等 / 可回滚
-------------
判据是「两列相等」，改完第二遍这些行不再入选 → 待订正 0。写库前把所有待改行的
原值、setup_time、新值落到快照 JSON，可据此逐行回滚。**默认 dry-run**，
必须显式 ``--apply`` 才写库。

用法::

    # 本地（SQLite）
    cd backend && .venv/Scripts/python.exe ../scripts/fix_report_hours_align.py AH-THR
    # staging 容器（PG）—— 需先 docker cp 本脚本与 e2e/_report_hours.py 到 /app/scripts/
    docker exec mfg1-backend python /app/scripts/fix_report_hours_align.py AH-THR --dry-run
    docker exec mfg1-backend python /app/scripts/fix_report_hours_align.py AH-THR --apply
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from collections import Counter
from pathlib import Path

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
for _cand in (_ROOT, _ROOT / "backend"):
    if (_cand / "app" / "core" / "config.py").is_file():
        sys.path.insert(0, str(_cand))
        break
# 工时口径单一真源：容器里放在脚本同目录，本地仓库放在 e2e/
sys.path.insert(0, str(_HERE))
sys.path.insert(0, str(_ROOT / "e2e"))

from sqlalchemy import text                             # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine   # noqa: E402

from app.core.config import get_settings                # noqa: E402
from _report_hours import hours_for                    # noqa: E402

START_DEFAULT = "2026-05-01"
END_DEFAULT = "2026-10-31"
EPS = 1e-6


def align_pair(machine_hours: float, setup_time: float) -> tuple[float, float] | None:
    """用 ``hours_for`` 反推应有 ``(labor, machine)``；不该订正时返回 None。

    ``unit_time=60`` 且 ``qty=machine_hours`` 时：
      ``machine = round(60 * qty / 60, 2) = round(machine_hours, 2)``（与已存值一致）
      ``labor   = round((60 * qty + setup_time) / 60, 2)``
    所以这里没有第二条口径，只是把真源用到「反推历史值」这个场景。
    """
    if machine_hours <= 0 or setup_time <= 0:
        return None
    seg = {"unit_time": 60.0, "setup_time": float(setup_time)}
    labor, machine = hours_for(seg, machine_hours)
    if abs(machine - machine_hours) > 0.005:
        return None  # 存量 machine_hours 精度异常，不猜
    return labor, machine


def selftest() -> bool:
    """判据自证：口径正确 + 口径被改坏时必须能识别。"""
    print("\nD0 工时订正判据自证")
    cases = [
        # name,                  machine_hours, setup_time, 期望 labor（None=不该订正）
        ("换型 5 分 → +0.08h",       2.0,  5.0,  2.08),
        ("换型 10 分 → +0.17h",      1.5, 10.0,  1.67),
        ("换型 20 分 → +0.33h",      0.5, 20.0,  0.83),
        ("换型 15 分 → +0.25h",      1.0, 15.0,  1.25),
        ("零换型：相等本就合法",      2.0,  0.0, None),
        ("零工时占位流水不订正",      0.0,  5.0, None),
        ("负工时不订正",             -1.0,  5.0, None),
    ]
    good = True
    for name, mh, st, expect in cases:
        got = align_pair(mh, st)
        labor = got[0] if got else None
        ok = (labor is None) if expect is None else (labor is not None and abs(labor - expect) < 0.005)
        print(f"  [{'OK ' if ok else 'FAIL'}] {name} · 期望 {expect} 实得 {labor}")
        good &= ok

    # 负向：把口径真源换成旧的「两列同一个表达式」，align_pair 必须失去差额。
    # 若这一步还返回 labor > machine，说明本脚本没真的绑定到口径真源。
    global hours_for
    _orig = hours_for
    hours_for = lambda seg, qty: (round(float(qty), 2) or 0.1,
                                  round(float(qty), 2) or 0.1)  # noqa: E731
    degraded = align_pair(2.0, 5.0)
    hours_for = _orig
    caught = degraded is None or degraded[0] <= degraded[1]
    print(f"  [{'OK ' if caught else 'FAIL'}] 口径退化（两列同式）被识别 · {degraded}")
    good &= caught
    return good


async def main(tenant_code: str, start: str, end: str, apply: bool, snapshot: str) -> int:
    if not selftest():
        print("[拒绝] 判据自证未通过，不碰数据")
        return 2

    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    try:
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("select tenant_id from tenants where code = :c"),
                {"c": tenant_code})).scalar()
            if not tid:
                print(f"[拒绝] 租户 {tenant_code} 不存在（注意传的是 code，不是 tenant_id）")
                return 2
            print(f"\n租户 {tenant_code} → tenant_id={tid} · 区间 {start} ~ {end}"
                  f" · {'★ APPLY 写库' if apply else 'dry-run 只打印'}\n")

            ops = (await conn.execute(
                text("select code, setup_time from operations where tenant_id = :t"),
                {"t": tid})).fetchall()
            setup_by_code = {str(r[0]): float(r[1] or 0) for r in ops}
            print(f"工序表 {len(ops)} 条 · 其中 setup_time>0 的 "
                  f"{sum(1 for v in setup_by_code.values() if v > 0)} 条")

            rows = (await conn.execute(text("""
                select id, report_date, operation_code, labor_hours, machine_hours
                  from work_reports where tenant_id = :t order by id
                """), {"t": tid})).fetchall()
            print(f"报工流水 {len(rows)} 条（日期过滤在 Python 层做，避开 DATE 绑定的 PG/SQLite 方言差异）")

            stats: Counter = Counter()
            changes: list[dict] = []
            for rid, rdate, op_code, labor, machine in rows:
                day = str(rdate)[:10]
                if not (start <= day <= end):
                    stats["区间外"] += 1
                    continue
                l = float(labor or 0)
                m = float(machine or 0)
                if abs(l - m) > EPS:
                    stats["已不等（幂等 SKIP）"] += 1
                    continue
                stats["区间内两列相等"] += 1
                if not op_code:
                    stats["operation_code 空·无法关联工序（不猜）"] += 1
                    continue
                st = setup_by_code.get(str(op_code))
                if st is None:
                    stats["工序表查不到该 code（不猜）"] += 1
                    continue
                pair = align_pair(m, st)
                if pair is None:
                    stats["零工时/无换型/精度异常·跳过"] += 1
                    continue
                new_labor, _ = pair
                if new_labor <= m + EPS:
                    stats["重算后仍相等·跳过"] += 1
                    continue
                changes.append({
                    "id": int(rid), "report_date": day, "operation_code": str(op_code),
                    "setup_time": st, "old_labor": l, "old_machine": m,
                    "new_labor": new_labor,
                })
                stats["待订正"] += 1

            print("\n分类统计：")
            for k in sorted(stats):
                print(f"  {k}: {stats[k]}")

            snap_path = Path(snapshot)
            snap_path.parent.mkdir(parents=True, exist_ok=True)
            snap_path.write_text(json.dumps({
                "tenant": tenant_code, "tenant_id": str(tid), "start": start, "end": end,
                "count": len(changes), "rows": changes,
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            print(f"\n快照（可逐行回滚）→ {snap_path} · {len(changes)} 行")
            if changes:
                print("  样例：", json.dumps(changes[0], ensure_ascii=False))

            if not apply:
                print("\n[dry-run] 未写库。确认无误后加 --apply 执行。")
                await conn.rollback()
                return 0

            for c in changes:
                await conn.execute(
                    text("update work_reports set labor_hours = :l "
                         "where id = :i and tenant_id = :t"),
                    {"l": c["new_labor"], "i": c["id"], "t": tid})
            print(f"\n[apply] 已订正 {len(changes)} 行 labor_hours")
            return 0
    finally:
        await engine.dispose()


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="订正存量报工人工工时（默认 dry-run）")
    ap.add_argument("tenant", nargs="?", default=os.environ.get("TENANT_CODE", "AH-THR"),
                    help="租户编码（不是 tenant_id），默认 AH-THR")
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--end", default=END_DEFAULT)
    ap.add_argument("--apply", action="store_true", help="真正写库；不加则 dry-run")
    ap.add_argument("--snapshot", default=os.environ.get(
        "HOURS_SNAPSHOT", "/tmp/report-hours-align.json"), help="快照 JSON 路径")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.tenant, a.start, a.end, a.apply, a.snapshot)))
