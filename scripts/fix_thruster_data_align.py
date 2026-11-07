"""推进器厂（AH-THR）产能数据对齐 —— 把产能闸报出的三处硬伤补平。

只做**数据订正**，不建表、不改结构。幂等：跑第二遍全部 SKIP。

## 为什么需要单独一个脚本

1. `MA035 支架组装` 的路线步骤 `wc_id` 是 NULL。根因在种子脚本：它把工位写成
   `WC-AH-MA035`，而工位清单里只有 `WC-AH-MA030 油封/支架工位`，**没有 MA035 这个
   工位** —— 播种时解析不到，就落成 NULL。后果不是"少一行"，是：
   - 这道工序不占任何工位排队 → 产能核算里凭空多一条并行通道；
   - 该工位口径 A 的「最慢一道」漏了它（55 应变成 48）。

   走 API 改不了：`save_steps` 有 `if route["status"] != "draft": raise`，而这条路线
   已发布、且被 31 张工单引用，不适合为了补一个外键去做版本切换。所以直连库订正。

2. `FA090` 的工序名写成「定子注油」，但它在**整机总装线**第 16 道、挂在「注油工位」，
   注的是合装后的整机（BOM 对应润滑脂 EP2）。定子灌胶在定子线 CW040 已完成，
   名字与位置对不上。

3. 改完这两处后，`capacity_per_shift` 要跟着重算 —— 那一步交给
   `scripts/seed_thruster_supplement.py s1`（口径 A 的唯一写入口，不要在这里重算，
   否则又多一份"第二实现"）。

## 用法

    cd backend && .venv/Scripts/python.exe ../scripts/fix_thruster_data_align.py AH-THR
    docker exec mfg1-backend python /app/scripts/fix_thruster_data_align.py AH-THR

加 `--dry-run` 只打印将要改什么。
"""
import argparse
import asyncio
import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
for _cand in (os.path.dirname(_HERE), os.path.join(os.path.dirname(_HERE), "backend")):
    if os.path.isfile(os.path.join(_cand, "app", "core", "config.py")):
        sys.path.insert(0, _cand)
        BACKEND_DIR = _cand
        break
else:
    BACKEND_DIR = os.path.dirname(_HERE)

from sqlalchemy import text                                  # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine        # noqa: E402

from app.core.config import get_settings                      # noqa: E402

#: 悬空工序 → 应该挂的工位编码。
#: 依据：工位名「油封/支架工位」本身就同时覆盖油封（MA030）和支架（MA035），
#: 两者共用一台伺服压机/螺丝枪工位；种子脚本里 MA035 的 `WC-AH-MA035` 是笔误。
ORPHAN_STEP_WC = {"MA035": "WC-AH-MA030"}

#: 工序名订正：(code, 旧名, 新名)。只在**当前名恰好是旧名**时才改，避免覆盖人工改过的值。
OP_RENAME = [("FA090", "定子注油", "整机注油")]


async def main(tenant_code: str, dry_run: bool) -> int:
    engine = create_async_engine(get_settings().DATABASE_URL, echo=False)
    changed = 0
    try:
        async with engine.begin() as conn:
            tid = (await conn.execute(
                text("select tenant_id from tenants where code = :c"),
                {"c": tenant_code})).scalar()
            if not tid:
                print(f"[拒绝] 租户 {tenant_code} 不存在")
                return 2
            print(f"租户 {tenant_code} → tenant_id={tid}"
                  f"{'（dry-run，不写库）' if dry_run else ''}\n")

            # ── 1. 悬空工序补工位 ────────────────────────────────────
            for op_code, wc_code in ORPHAN_STEP_WC.items():
                wc_id = (await conn.execute(
                    text("select id from work_centers where tenant_id = :t and code = :c"),
                    {"t": tid, "c": wc_code})).scalar()
                if not wc_id:
                    print(f"[MISS] 工位 {wc_code} 不存在，跳过 {op_code}")
                    continue
                rows = (await conn.execute(text("""
                    select s.id, s.step_seq, r.code
                      from route_steps s
                      join operations o on o.id = s.operation_id
                      join process_routes r on r.id = s.route_id
                     where s.tenant_id = :t and o.code = :op and s.wc_id is null
                    """), {"t": tid, "op": op_code})).fetchall()
                if not rows:
                    print(f"[skip] {op_code} 的路线步骤都已挂工位")
                    continue
                for sid, seq, rcode in rows:
                    print(f"[FIX ] {rcode} 第 {seq} 道 {op_code}  wc_id NULL → {wc_code}({wc_id})")
                    if not dry_run:
                        await conn.execute(
                            text("update route_steps set wc_id = :w where id = :i"),
                            {"w": wc_id, "i": sid})
                    changed += 1

            # ── 2. 工序名订正 ────────────────────────────────────────
            for code, old, new in OP_RENAME:
                rows = (await conn.execute(text("""
                    select id, name from operations
                     where tenant_id = :t and code = :c and name = :n
                    """), {"t": tid, "c": code, "n": old})).fetchall()
                if not rows:
                    print(f"[skip] {code} 名称不是「{old}」，保持原样")
                    continue
                for oid, name in rows:
                    print(f"[FIX ] 工序 {code} 名称「{name}」→「{new}」")
                    if not dry_run:
                        await conn.execute(
                            text("update operations set name = :n where id = :i"),
                            {"n": new, "i": oid})
                    changed += 1

            if dry_run:
                await conn.rollback()
    finally:
        await engine.dispose()

    print(f"\n[done] {'将改动' if dry_run else '已改动'} {changed} 处")
    if changed and not dry_run:
        print("下一步：重算产能与班次 → "
              "python scripts/seed_thruster_supplement.py s1")
    return 0


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="推进器厂产能数据对齐（只订正数据）")
    ap.add_argument("tenant", nargs="?", default=os.environ.get("TENANT_CODE", "AH-THR"),
                    help="租户编码（不是 tenant_id），默认 AH-THR")
    ap.add_argument("--dry-run", action="store_true", help="只打印，不写库")
    a = ap.parse_args()
    sys.exit(asyncio.run(main(a.tenant, a.dry_run)))
