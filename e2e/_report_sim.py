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
R8 工单数：月报工单数 == 该月日报出现过的不同工单数

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
    (ok if 0 < rate <= 100 else bad)(
        "R7a 达产率 (0,100]", f"{rate:.1f}%（{round(out)}/{cap}，{len(workdays)} 工作日）")
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

    # ── 落盘 ──
    out_doc = {
        "tenant": TENANT, "api": API, "start": str(START), "end": str(END),
        "calendar": {"days": len(days), "workdays": len(workdays)},
        "half_year": {k: round(v, 2) for k, v in half_day.items()},
        "derived": {
            "capacity_basis": {"per_shift": 2, "wo_per_unit": 3, "cap": cap},
            "achievement_rate_pct": round(rate, 2),
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
    raise SystemExit(main())
