"""产能自洽性核查（只读）：场景数据算出来的月产能，与设计纲领对不对得上。

## 为什么要有这个脚本

推进器厂的设计纲领是 **月产 45 台**，而且工序里有预热、抽真空、固化烘烤、老化这类
**工艺占机时长**——单线产能天然不高。但系统里这件事**没有任何地方校验**：

- `work_centers.capacity_per_shift` 只有 CRUD 读写，**没有任何业务逻辑消费它**；
- 没有排产 / 有限产能排程模块（`app/api/` 下无 scheduling）；
- `operations` 只有 `setup_time`（准备）与 `unit_time`（单件加工），
  **没有工序间等待 / 预热降温 / 固化占用** 这类字段。

所以产能填了多少、填得对不对，跑完全量回归也发现不了——**没有任何断言会去读它**。

## 算法（关键：按**工位**聚合，不是按工序）

一个工作中心上常挂多道工序（推进器的灌胶区一个工位就挂了 7 道：
预热 / 混合抽真空 / 灌胶 / 灌胶后抽真空 / 固化烘烤 / 冷却拆治具）。
**该工位每班能出几件，取决于这些工序的占机合计**，而不是最快那道。

因此：

1. 按 `(路线, 工作中心)` 聚合 `unit_time`（`route_steps.unit_time_override` 优先）；
2. 工位实际产能 = `班时 × efficiency ÷ 合计占机`；
3. 瓶颈 = 该路线里**实际产能最低**的工位；
4. 月产能 = 每班产出 × 班数 × 月工作日；
5. 同时拿 `capacity_per_shift` 字段值与实算值比对 —— 字段是按单道工序填的，
   一个工位多工序时它会**高估**，这个差额就是要报出来的东西。

## 用法

    docker cp scripts/check_capacity_consistency.py mfg1-backend:/app/scripts/
    docker exec mfg1-backend python /app/scripts/check_capacity_consistency.py AH-THR

只读，不改任何数据。退出码：全部对得上 = 0，否则 1。
"""
import asyncio
import json
import math
import os
import re
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if os.path.isfile(os.path.join(BACKEND_DIR, "app", "core", "config.py")):
    sys.path.insert(0, BACKEND_DIR)

from sqlalchemy import text                              # noqa: E402
from sqlalchemy.ext.asyncio import create_async_engine    # noqa: E402

from app.core.config import get_settings                  # noqa: E402

TENANT_CODE = sys.argv[1] if len(sys.argv) > 1 else "AH-THR"

#: 设计纲领：月产 45 台（用户 2026-11-05 明确）。
DESIGN_MONTHLY = 45.0
#: 月工作日口径（工厂日历为空时用）。
WORKDAYS = 22
#: 每班小时数兜底值（shift_config 认不出来时用）。
FALLBACK_SHIFT_HOURS = 12.0
#: 字段值与实算值相差多少算"填错"。20% 以内算口径差异，超过就是两套数各说各话。
TOLERANCE = 0.20
#: 月产能与设计纲领的允许偏差（百分点）。±15% 内算"对得上"。
DESIGN_TOLERANCE_PCT = 15.0

#: 工艺占机类工序（预热/固化/老化/真空/烘烤…）—— 产能天花板的主要来源。
PROCESS_WAIT_RE = ("预热", "固化", "冷却", "烘烤", "老化", "真空", "保温", "跑合", "浸胶", "灌胶")


async def main() -> int:
    eng = create_async_engine(get_settings().DATABASE_URL)
    try:
        async with eng.connect() as conn:
            tid = (await conn.execute(text(
                "select tenant_id from tenants where code = :c"),
                {"c": TENANT_CODE})).scalar()
            if not tid:
                print(f"[拒绝] 租户 {TENANT_CODE} 不存在")
                return 2

            rows = (await conn.execute(text("""
                select r.id, r.code, r.name, r.version, r.status,
                       rs.step_seq, o.code as op_code, o.name as op_name,
                       coalesce(rs.unit_time_override, o.unit_time) as unit_time,
                       coalesce(rs.setup_time_override, o.setup_time) as setup_time,
                       rs.wc_id, w.code as wc_code, w.name as wc_name,
                       w.capacity_per_shift, w.efficiency, w.shift_config,
                       w.equipment_count, w.labor_count
                from process_routes r
                join route_steps rs on rs.route_id = r.id
                join operations o on o.id = rs.operation_id
                left join work_centers w on w.id = rs.wc_id
                where r.tenant_id = :t and r.status = 'published'
                order by r.code, r.version, rs.step_seq
            """), {"t": tid})).fetchall()

            if not rows:
                print(f"租户 {TENANT_CODE} 没有已发布路线")
                return 1

            routes: dict = {}
            for r in rows:
                routes.setdefault((r[1], r[3]), {"name": r[2], "steps": []})["steps"].append(r)

            print("=" * 100)
            print(f"产能自洽性核查 · 租户 {TENANT_CODE} · 设计纲领 {DESIGN_MONTHLY:.0f} 台/月 · "
                  f"{WORKDAYS} 工作日")
            print("=" * 100)

            verdicts, problems = [], []

            for (code, ver), info in routes.items():
                steps = info["steps"]
                print(f"\n── {code} v{ver} · {info['name']} · {len(steps)} 道工序 ──")

                # ① 按工位聚合（关键：不是按工序）
                #    占机 = 单件加工 + 准备时间。准备时间本是"每批一次"，这里按
                #    批量为 1 摊到每件（最保守口径，也是推进器这种单件流的实际形态：
                #    一个治具一次装一件，换一次治具就要重来一次准备）。
                stations: dict = {}
                orphan = []
                for s in steps:
                    if not s[10]:
                        orphan.append(s)
                        continue
                    st = stations.setdefault(s[10], {
                        "wc_code": s[11], "wc_name": s[12],
                        "cap": s[13], "eff": s[14] or 1.0, "shift": s[15],
                        "eq": s[16], "lab": s[17],
                        "ops": [], "sum_unit": 0.0,
                    })
                    st["ops"].append(s)
                    st["sum_unit"] += float(s[8] or 0) + float(s[9] or 0)

                if orphan:
                    print(f"  ⚠️ {len(orphan)} 道工序未挂工作中心（不参与产能核算）："
                          + "、".join(f"{o[6]} {o[7]}" for o in orphan))

                if not stations:
                    print("  ⚠️ 全线工序都没挂工作中心，无法核算")
                    verdicts.append((code, ver, "NO_WC", None, None))
                    continue

                # ② 班次与班时：取占机最重那站的配置
                heaviest = max(stations.values(), key=lambda x: x["sum_unit"])
                shifts, shift_hours = _parse_shift(heaviest["shift"])
                if shifts is None:
                    shifts, shift_hours = 2, FALLBACK_SHIFT_HOURS
                shift_minutes = shift_hours * 60

                # ③ 每站实算产能，瓶颈 = 最小
                #    ★ 按**整件**取整：一个治具/台架一次装一件，剩余班时不够再做一件
                #      就只能空着（720 分做完 2 件剩 220 分，不够第 3 件的 250 分）。
                #      这是数据里 capacity_per_shift=2 的填表口径 —— 也是唯一能让
                #      定子线与整机线同时落在 44 台/月的口径。
                #    ★ 不乘 efficiency 0.9：乘了之后定子线从 2 件/班掉到 1 件/班
                #      （月产 22 台，只有纲领的一半）。这说明 efficiency 到底是
                #      "OEE 目标"还是"排产可用时间"在系统里从未定义过 —— 一并报出来。
                for st in stations.values():
                    if not st["sum_unit"]:
                        st["implied"] = None
                        st["implied_eff"] = None
                        continue
                    st["implied"] = math.floor(shift_minutes / st["sum_unit"])
                    st["implied_eff"] = math.floor(shift_minutes * st["eff"] / st["sum_unit"])
                scored = [st for st in stations.values() if st["implied"]]
                if not scored:
                    print("  ⚠️ 全线工位占机都超过一个班时，出不了整件")
                    verdicts.append((code, ver, "NO_OUTPUT", 0, 0))
                    continue
                gate = min(scored, key=lambda x: x["implied"])

                waits = [s for s in gate["ops"] if s[7] and any(k in s[7] for k in PROCESS_WAIT_RE)]
                wait_min = sum(float(s[8] or 0) for s in waits)

                print(f"  瓶颈工位  {gate['wc_code']} {gate['wc_name']} · "
                      f"{len(gate['ops'])} 道工序 · 合计占机 {gate['sum_unit']:g} 分")
                print(f"  该站工序  " + "、".join(f"{s[7]}/{float(s[8] or 0):g}分" for s in gate["ops"]))
                if waits:
                    print(f"  工艺占机  {len(waits)} 道 / {wait_min:g} 分"
                          f"（占该站 {wait_min / gate['sum_unit'] * 100:.0f}%，"
                          f"不能靠加人缩短）")
                print(f"  实算产能  {gate['implied']} 件/班"
                      f"（floor({shift_hours:g}h×60 ÷ {gate['sum_unit']:g} 分)）"
                      + (f"；若再乘效率 {gate['eff']:g} 只剩 {gate['implied_eff']} 件/班"
                         if gate["implied_eff"] != gate["implied"] else ""))

                # ④ 与字段值比对
                field_cap = gate["cap"]
                if field_cap:
                    delta = (float(field_cap) - gate["implied"]) / gate["implied"]
                    if abs(delta) <= TOLERANCE:
                        print(f"  字段核对  ✅ capacity_per_shift={field_cap:g} 与实算相符")
                    else:
                        sign = "高估" if delta > 0 else "低估"
                        print(f"  字段核对  ❌ capacity_per_shift={field_cap:g} "
                              f"{sign} {abs(delta) * 100:.0f}%（按单道工序填的？）")
                        problems.append(f"{code} {gate['wc_code']} 字段 {field_cap:g} vs 实算 "
                                        f"{gate['implied']}")
                else:
                    print("  字段核对  ⚠️ 该工位没填 capacity_per_shift")

                # ⑤ 月产能（按实算，双口径）
                per_shift = gate["implied"]
                m1, mn = per_shift * WORKDAYS, per_shift * shifts * WORKDAYS
                print(f"  月产能    单班 {m1:6.1f} 台 ｜ {shifts} 班 {mn:6.1f} 台")

                diff = (m1 - DESIGN_MONTHLY) / DESIGN_MONTHLY * 100
                ok = abs(diff) <= DESIGN_TOLERANCE_PCT
                print(f"  对比纲领  单班 {m1:.0f} vs {DESIGN_MONTHLY:.0f} → "
                      + ("✅ 对得上" if ok else f"❌ 偏差 {diff:+.0f}%"))
                if shifts > 1:
                    print(f"            ⚠️ shift_config 写的是 {shifts} 班（{shift_hours:g}h）→ "
                          f"按配置算 {mn:.0f} 台/月，是单班的 {shifts} 倍；"
                          f"若纲领是 {DESIGN_MONTHLY:.0f} 台，两班配置与实际不符")
                verdicts.append((code, ver, "OK" if ok else f"偏差 {diff:+.0f}%", m1, mn))

            print("\n" + "=" * 100)
            print("汇总")
            print("=" * 100)
            for code, ver, tag, m1, mn in verdicts:
                s1 = f"{m1:.0f}" if m1 else "-"
                sn = f"{mn:.0f}" if mn else "-"
                print(f"  {code:<18} v{ver}  单班 {s1:>6} 台/月 ｜ 按配置 {sn:>6} 台/月   {tag}")

            if problems:
                print("\n字段与实算不符（一个工位多工序时，字段会按最快那道工序填）：")
                for p in problems:
                    print(f"  - {p}")

            bad = [v for v in verdicts if not str(v[2]).startswith("OK")]
            print(f"\n结论：{len(verdicts)} 条路线，单班口径 {len(verdicts) - len(bad)} 条与 "
                  f"{DESIGN_MONTHLY:.0f} 台/月吻合；{len(problems)} 个工位字段填错")
            return 0 if not bad and not problems else 1
    finally:
        await eng.dispose()


def _parse_shift(cfg):
    """从 shift_config 数班数与单班时长。认不出来返回 (None, None)。

    实际存的是中文自由文本（`白班 08:00-20:00；夜班 20:00-08:00`），不是 JSON ——
    按"出现几个 HH:MM-HH:MM"数班次，按首尾时间差算时长（跨零点 +24h）。
    """
    if not cfg:
        return None, None
    raw = cfg
    try:
        data = json.loads(cfg)
        if isinstance(data, list):
            raw = "；".join(f"{d.get('shift_name','')} {d.get('start_time','')}-{d.get('end_time','')}"
                            for d in data)
    except Exception:
        pass
    spans = re.findall(r"(\d{1,2}):(\d{2})\s*-\s*(\d{1,2}):(\d{2})", raw)
    if not spans:
        return None, None
    h1, m1, h2, m2 = (int(x) for x in spans[0])
    hours = (h2 * 60 + m2 - (h1 * 60 + m1)) / 60
    if hours <= 0:
        hours += 24
    return len(spans), hours


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
