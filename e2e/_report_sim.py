"""报表模拟对账：用推进器厂（AH-THR）半年真实流水，逐日 / 逐月跑一遍报表接口。

为什么必须"模拟"而不是"打开页面看一眼"
--------------------------------------
报表最危险的错不是 500，是**口径悄悄错了但数字看着合理**：
- 曾对全部工序 ``SUM(output_qty)``，多工序工单把产量乘上工序数：
  当日全厂显示 1760，实际完工 74。页面不报错、不告警，肉眼看不出。
- 改成完工口径后，``total_output``（末道工序）与 ``total_wip_output``
  （工序累计）极易被混用，两个数字都"有出处"，但谁也对不上谁。

所以本脚本不信任任何单一接口，做**跨层交叉验证**：明细行合计 = 汇总、
日报之和 = 月报、半年 = 六个月之和。任何一层口径串了，这三条必有一条断。

对账项
------
R1 日报：``rows`` 各项合计 == 顶层汇总（五项 + 行数）
R2 月报：``rows`` 各项合计 == 顶层汇总（五项 + 工单数）
R3 月报 == 该月日报之和（跨层，最容易在区间边界上错）
R4 半年合计 == 六个月之和 == 133 个工作日之和
R5 休息日零产出（工厂日历判 rest/holiday 的日子不得有报工）
R6 完工口径 ≤ 工序流转口径（完工只认末道工序，超过必然是口径串了）
R7 派生指标（达产率 / 报废率 / 单台工时）落在物理合理区间
    R7a 达产率**只判下限**：cap 是按订单节拍估出来的理论能力，不是硬天花板
R8 工单数：月报工单数 == 该月日报出现过的不同工单数
R9 人工工时 ≠ 设备机时（有产出的月份两者精确相等 = 播种时两列写了同一个数）

判据自证
--------
D0 在真正抓数前先用一组负向用例把 R7a 判据钉死：零产出、负产出、
cap≤0、NaN/Inf、非数值、下限调高后达不到，全部必须 FAIL；
100.1%（staging 实测）与 150% 必须 PASS。
**没有「预期 FAIL」的用例就没有闸** —— 若有人把判据改成恒真，
这些预期 FAIL 会集体翻绿，D0 立刻报红。可用 ``--self-test`` 离线单跑。

跑法（staging，数据在那里；本地库已被清空）::

    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      ./backend/.venv/Scripts/python.exe e2e/_report_sim.py

本机工作代理不一定常开，脚本会主动摘掉 ``*_PROXY`` 环境变量（否则 502）。
"""
from __future__ import annotations

import json
import os
import sys
from datetime import date, timedelta
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

for _k in ("HTTP_PROXY", "HTTPS_PROXY", "http_proxy", "https_proxy", "ALL_PROXY", "all_proxy"):
    os.environ.pop(_k, None)

import httpx  # noqa: E402

import _factory_calendar as fc  # noqa: E402

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1").rstrip("/")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
START = date.fromisoformat(os.environ.get("SIM_START", "2026-05-01"))
END = date.fromisoformat(os.environ.get("SIM_END", "2026-10-31"))

OKS: list[str] = []
FAILS: list[str] = []


def ok(name: str, detail: str = "") -> None:
    OKS.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def bad(name: str, detail: str = "") -> None:
    FAILS.append(f"{name} · {detail}" if detail else name)
    print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def daterange(a: date, b: date):
    d = a
    while d <= b:
        yield d
        d += timedelta(days=1)


# 汇总层字段名。★ 注意明细行**不叫这个**：``DailyReportRow.wip_output``
#   与 ``MonthlyReport.total_wip_output`` 是同一个概念的两个名字（schema 里
#   各自声明过，测试也钉着 wip_output），所以行内合计必须按 ROW_KEY 取。
FIELDS = ("total_output", "total_wip_output", "total_scrap",
          "total_hours", "total_machine_hours")
ROW_KEY = {"total_wip_output": "wip_output"}   # 汇总名 → 明细行名


def near(a, b, tol: float = 0.01) -> bool:
    try:
        return abs(float(a or 0) - float(b or 0)) <= tol
    except (TypeError, ValueError):
        return False


def attainment_ok(rate, cap=None, min_pct: float = 0.0) -> tuple[bool, str]:
    """达产率**单向**判据：只判「达不到」，超出理论上限一律算达标。

    与 ``scripts/check_capacity_consistency.py::design_verdict()`` 同一条原则：
    ``cap = 工作日 × 2 台 × 3 张单`` 是**按订单节拍估出来的理论能力**，不是
    物理硬天花板。staging 实测 799/798 = 100.1%，说明这个估算偏保守，不是
    业务缺陷 —— 拿 ``rate <= 100`` 当硬上限判死，等于把**余量**当**缺陷**
    （2026-11-07 用户拍板「按 45 台/月产能」时已把纲领判定单向化）。

    闸只管一件事：**交不出货**。所以下限（``rate <= min_pct``）仍判死，
    上限只打印余量、不拦截。``min_pct`` 默认 0 保持原判据下限语义；
    参数化是为了让 D0 能证明「下限真的拦得住」，不是给判据开后门。

    NaN/Inf/非数值/cap≤0 显式拦掉：改成单向后若不显式校验，一个坏读数
    可能既不算「达不到」也不算「达产」，失败原因还读不出来。

    返回 ``(ok, 说明)``；说明仅供打印，不参与判定。
    """
    if cap is not None:
        if not isinstance(cap, (int, float)) or isinstance(cap, bool):
            return False, "理论产能 cap 非数值"
        if cap != cap or abs(cap) == float("inf") or cap <= 0:
            return False, "理论产能 cap ≤ 0 或 NaN/Inf → 达产率无从谈起"
    if not isinstance(rate, (int, float)) or isinstance(rate, bool):
        return False, "达产率非数值（None / 字符串 / 布尔）"
    if rate != rate or abs(rate) == float("inf"):
        return False, "达产率含 NaN/Inf（读数没拿到）"
    if rate <= min_pct:
        return False, f"达产率 {rate:.1f}% ≤ 下限 {min_pct:.1f}%（交不出货）"
    if rate > 100:
        return True, (f"达产（超理论上限 +{rate - 100:.1f}%，"
                      "cap 是保守估算，余量不构成缺陷）")
    return True, "达产"


def selftest() -> None:
    """D0 判据自证：没有负向用例 = 没有闸。

    12 条「预期 FAIL」是本节的价值所在：谁把 ``attainment_ok`` 改成恒真，
    它们会集体翻绿，下面立刻报红 —— 判据自身也被闸住了。
    """
    print("\nD0 达产率判据自证（负向用例）")
    cases = [
        # name,                         rate,            cap,            min_pct, 期望
        ("正常达产 95%",                 95.0,           798,            0.0,   True),
        ("刚好 100% 不判死",             100.0,          798,            0.0,   True),
        ("★ staging 实测 100.1% 必须 PASS", 100.1,       798,            0.0,   True),
        ("大幅超上限 150% 也不判死",     150.0,          798,            0.0,   True),
        ("贴近零的正值仍算有产出",       0.001,          798,            0.0,   True),
        ("零产出",                       0.0,            798,            0.0,   False),
        ("负产出",                       -1.0,           798,            0.0,   False),
        ("cap=0 分母无效",               0.0,            0,              0.0,   False),
        ("cap 为负",                     95.0,           -798,           0.0,   False),
        ("cap 是字符串",                 95.0,           "798",          0.0,   False),
        ("cap 是 NaN",                   95.0,           float("nan"),   0.0,   False),
        ("rate 是 None",                 None,           798,            0.0,   False),
        ("rate 是字符串",                "95",           798,            0.0,   False),
        ("rate 是布尔",                  True,           798,            0.0,   False),
        ("rate 是 NaN",                  float("nan"),   798,            0.0,   False),
        ("rate 是 Inf",                  float("inf"),   798,            0.0,   False),
        ("下限调到 85% 后 80% 判死",     80.0,           798,            85.0,  False),
        ("下限调到 85% 后 90% 通过",     90.0,           798,            85.0,  True),
    ]
    for name, rate, cap, min_pct, expect in cases:
        got, why = attainment_ok(rate, cap=cap, min_pct=min_pct)
        (ok if got == expect else bad)(f"D0 {name}", f"期望 {expect} 实得 {got}（{why}）")


def login() -> dict:
    with httpx.Client(timeout=30) as c:
        r = c.post(f"{API}/auth/login",
                   json={"username": USER, "password": PWD, "tenant_id": TENANT})
        r.raise_for_status()
        tok = r.json()["access_token"]
    return {"Authorization": f"Bearer {tok}"}


def get(h: dict, path: str, **params):
    with httpx.Client(timeout=60) as c:
        r = c.get(f"{API}{path}", params=params, headers=h)
        r.raise_for_status()
        body = r.json()
    return body.get("data", body)


def main() -> int:
    selftest()  # ★ 先自证判据，再联网抓数；判据坏了后面全是假绿
    print(f"\n租户 {TENANT} · 区间 {START} → {END} · API {API}\n")
    h = login()
    ok("登录", USER)

    days = list(daterange(START, END))
    months = sorted({(d.year, d.month) for d in days})

    # ── 抓数：逐日 ──
    daily: dict[str, dict] = {}
    for d in days:
        daily[d.isoformat()] = get(h, "/reports/daily", report_date=d.isoformat())
    ok("拉取日报", f"{len(daily)} 天")

    # ── 抓数：逐月 ──
    monthly: dict[str, dict] = {}
    for y, m in months:
        monthly[f"{y}-{m:02d}"] = get(h, "/reports/monthly", year=y, month=m)
    ok("拉取月报", f"{len(monthly)} 个月")

    # ── R1 日报层级自洽 ──
    print("\nR1 日报：明细合计 == 顶层汇总")
    for iso, rep in daily.items():
        rows = rep.get("rows") or []
        s = {k: sum(float(r.get(ROW_KEY.get(k, k)) or 0) for r in rows) for k in FIELDS}
        for k in FIELDS:
            if not near(rep.get(k), s[k]):
                bad(f"R1 {iso} {k}", f"顶层 {rep.get(k)} ≠ 明细和 {round(s[k], 2)}")
    if not any(f.startswith("R1 ") for f in FAILS):
        maxout = max((daily[i].get("total_output") or 0 for i in daily), default=0)
        maxwip = max((daily[i].get("total_wip_output") or 0 for i in daily), default=0)
        ok("R1 逐日五项全自洽", f"{len(daily)} 天 · 单日完工峰值 {maxout} · 流转峰值 {maxwip}")

    # ── R2 月报层级自洽 ──
    print("\nR2 月报：明细合计 == 顶层汇总")
    for mk, rep in monthly.items():
        rows = rep.get("rows") or []
        s = {k: sum(float(r.get(ROW_KEY.get(k, k)) or 0) for r in rows) for k in FIELDS}
        for k in FIELDS:
            if not near(rep.get(k), s[k]):
                bad(f"R2 {mk} {k}", f"顶层 {rep.get(k)} ≠ 明细和 {round(s[k], 2)}")
        if rep.get("orders") != len(rows):
            bad(f"R2 {mk} orders", f"{rep.get('orders')} ≠ 明细行数 {len(rows)}")
    if not any(f.startswith("R2 ") for f in FAILS):
        ok("R2 逐月五项 + 工单数全自洽", f"{len(monthly)} 个月")

    # ── R3 月报 == 该月日报之和 ──
    print("\nR3 月报 == 该月日报之和")
    for mk, rep in monthly.items():
        sub = [r for i, r in daily.items() if i[:7] == mk]
        for k in FIELDS:
            want = sum(float(r.get(k) or 0) for r in sub)
            if not near(rep.get(k), want):
                bad(f"R3 {mk} {k}", f"月报 {rep.get(k)} ≠ 日报和 {round(want, 2)}")
        ok(f"R3 {mk}", f"完工 {rep.get('total_output')} · 流转 {rep.get('total_wip_output')}"
                       f" · 报废 {rep.get('total_scrap')} · 工单 {rep.get('orders')}")

    # ── R4 半年合计 == 月之和 == 日之和 ──
    print("\nR4 半年合计三路对齐（月之和 / 日之和）")
    half_day = {k: sum(float(r.get(k) or 0) for r in daily.values()) for k in FIELDS}
    half_mon = {k: sum(float(r.get(k) or 0) for r in monthly.values()) for k in FIELDS}
    for k in FIELDS:
        if not near(half_day[k], half_mon[k]):
            bad(f"R4 {k}", f"日之和 {round(half_day[k], 2)} ≠ 月之和 {round(half_mon[k], 2)}")
    if not any(f.startswith("R4 ") for f in FAILS):
        ok("R4 半年三路对齐", f"完工 {round(half_day['total_output'])}"
                              f" · 流转 {round(half_day['total_wip_output'])}"
                              f" · 报废 {round(half_day['total_scrap'])}")

    # ── R5 休息日零产出 ──
    print("\nR5 休息日零产出")
    viol = [i for i, r in daily.items()
            if r.get("total_output") and not fc.is_work(fc.expected_type(date.fromisoformat(i)))]
    zero_days = [i for i, r in daily.items() if not r.get("total_output")]
    (ok if not viol else bad)(
        "R5 休息日无产出",
        f"{len(zero_days)} 个零产出日（含休息日）" if not viol
        else f"{len(viol)} 天有产出: {viol[:5]}")

    # ── R6 完工 ≤ 流转 ──
    print("\nR6 完工口径 ≤ 工序流转口径")
    over = [i for i, r in daily.items()
            if (r.get("total_output") or 0) > (r.get("total_wip_output") or 0)]
    (ok if not over else bad)(
        "R6 完工不超流转",
        f"峰值 完工 {round(half_day['total_output'])} ≤ 流转 {round(half_day['total_wip_output'])}"
        if not over else f"{len(over)} 天完工 > 流转: {over[:5]}")

    # ── R7 派生指标 ──
    print("\nR7 派生指标（达产率 / 报废率 / 单台工时）")
    workdays = [d for d in days if fc.is_work(fc.expected_type(d))]
    out = half_day["total_output"]
    scrap = half_day["total_scrap"]
    labor = half_day["total_hours"]
    # 一天 2 台整机；但完工口径含定子 / 转子 / 整机三张单 → 3 × 2
    cap = len(workdays) * 2 * 3
    rate = out / cap * 100 if cap else 0
    scrap_rate = scrap / (out + scrap) * 100 if (out + scrap) else 0
    per_unit = labor / out if out else 0
    att_ok, att_why = attainment_ok(rate, cap=cap)
    (ok if att_ok else bad)(
        "R7a 达产率只判下限",
        f"{rate:.1f}%（{round(out)}/{cap}，{len(workdays)} 工作日）· {att_why}")
    (ok if 0 <= scrap_rate < 10 else bad)(
        "R7b 报废率 < 10%", f"{scrap_rate:.2f}%（{round(scrap)} 件）")
    (ok if 0 < per_unit < 100 else bad)(
        "R7c 单台工时合理", f"{per_unit:.2f} h/件")

    # ── R8 工单数交叉 ──
    print("\nR8 月报工单数 == 该月日报出现过的不同工单数")
    for mk, rep in monthly.items():
        wos = set()
        for i, r in daily.items():
            if i[:7] == mk:
                wos |= {x.get("wo_no") for x in (r.get("rows") or []) if x.get("wo_no")}
        if rep.get("orders") != len(wos):
            bad(f"R8 {mk}", f"月报 {rep.get('orders')} ≠ 日报不同工单 {len(wos)}")
    if not any(f.startswith("R8 ") for f in FAILS):
        ok("R8 工单数全月一致")

    # ── R9 人工工时 vs 设备机时 ──
    # 两个口径物理上不可能恒等：机时是设备被占住的时长，人工还要加换型/装夹。
    # 整月精确相等只能有一个原因 —— 播种时两列写成了同一个表达式（实际发生过：
    # 半年流水全库 labor_hours == machine_hours 逐行相等，页面上两个指标同一数）。
    # 这条**不报错、不掉接口**，只有跨指标对账才发现得了。
    print("\nR9 人工工时 vs 设备机时")
    same_month = [mk for mk, r in monthly.items()
                  if (r.get("total_output") or 0) > 0
                  and near(r.get("total_hours"), r.get("total_machine_hours"), 0.001)]
    (ok if not same_month else bad)(
        "R9 两者非恒等",
        f"人工 {round(half_day['total_hours'], 2)} h · 机时 {round(half_day['total_machine_hours'], 2)} h"
        if not same_month
        else f"{len(same_month)} 个月两者精确相等（{','.join(same_month)}）→ "
             f"播种把人工工时与设备机时写成了同一个数")

    # ── 落盘 ──
    out_doc = {
        "tenant": TENANT, "api": API, "start": str(START), "end": str(END),
        "calendar": {"days": len(days), "workdays": len(workdays)},
        "half_year": {k: round(v, 2) for k, v in half_day.items()},
        "derived": {
            "capacity_basis": {"per_shift": 2, "wo_per_unit": 3, "cap": cap},
            "achievement_rate_pct": round(rate, 2),
            # ★ 单向判据：cap 是保守估算，>100% 是余量不是缺陷，留痕便于复核
            "attainment_verdict": "one_sided_min_only",
            "attainment_ok": att_ok,
            "attainment_headroom_pct": round(max(0.0, rate - 100), 2),
            "attainment_reason": att_why,
            "scrap_rate_pct": round(scrap_rate, 2),
            "labor_hours_per_unit": round(per_unit, 2),
        },
        "months": [{"month": mk, **{k: monthly[mk].get(k) for k in FIELDS},
                    "orders": monthly[mk].get("orders")} for mk in sorted(monthly)],
        "ok": len(OKS), "fail": len(FAILS), "fails": FAILS,
    }
    dest = HERE.parent / "deliverables" / f"report-sim-{TENANT.lower()}.json"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(out_doc, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\n{'=' * 60}\n通过 {len(OKS)} · 失败 {len(FAILS)}")
    for f in FAILS:
        print("  FAIL", f)
    print(f"明细已落盘 {dest}")
    return 0 if not FAILS else 1


if __name__ == "__main__":
    if "--self-test" in sys.argv:
        selftest()  # 离线自证，不联网、不落盘
        raise SystemExit(0 if not FAILS else 1)
    raise SystemExit(main())
