"""工厂日历（M06）—— 大小周 + 2026 年法定节假日（含调休补班）单一真源。

用途有三：
1. 把日历**播种进系统**（`POST /calendars/{year}/init` + `/calendars/batch`），
   让 `factory_calendars` 有真数据；
2. 供造数脚本**读回系统日历**取工作日（不在脚本里另算一套，否则又成双源）；
3. 供产能核查**核对工作日基准**（大小周扣节假日 ≈ 22.9 天/月）。

放假日期来源：国务院办公厅《关于 2026 年部分节假日安排的通知》
（2025-11-04 发布，gov.cn）。

大小周规则（本厂口径，可改）：
    **ISO 周序号为单数的周 = 大周（周一~周六上班）**，双周 = 小周（周一~周五）。
    官方调休上班日额外覆盖为 `adjust_work`。
    优先级：法定假日 > 调休上班日 > 大小周周六 > 默认(周一~五上班/周末休息)。

跑法::

    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      ./backend/.venv/Scripts/python.exe e2e/_factory_calendar.py --seed
    ... --check        # 校验播种结果
    ... --show         # 打印指定周期的工作日
"""
import argparse
import calendar as pycal
import json
import os
from collections import defaultdict
from datetime import date, timedelta

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
YEAR = int(os.environ.get("CAL_YEAR", "2026"))

# ── 国务院办公厅《关于 2026 年部分节假日安排的通知》 ──────────────
# (首日, 末日, 名称) —— 含调休形成的连续假期
HOLIDAYS = [
    ("2026-01-01", "2026-01-03", "元旦"),
    ("2026-02-15", "2026-02-23", "春节"),
    ("2026-04-04", "2026-04-06", "清明节"),
    ("2026-05-01", "2026-05-05", "劳动节"),
    ("2026-06-19", "2026-06-21", "端午节"),
    ("2026-09-25", "2026-09-27", "中秋节"),
    ("2026-10-01", "2026-10-07", "国庆节"),
]
# 官方调休上班日（周末补班）
ADJUST_WORK = ["2026-01-04", "2026-02-14", "2026-02-28",
               "2026-05-09", "2026-09-20", "2026-10-10"]

DAY_WORKDAY = "workday"
DAY_REST = "rest"
DAY_HOLIDAY = "holiday"
DAY_ADJ_WORK = "adjust_work"
DAY_ADJ_REST = "adjust_rest"


def _d(s: str) -> date:
    return date.fromisoformat(s)


def holiday_map() -> dict:
    """{date: 名称} —— 全部放假日期。"""
    out = {}
    for a, b, name in HOLIDAYS:
        cur, end = _d(a), _d(b)
        while cur <= end:
            out[cur] = name
            cur += timedelta(days=1)
    return out


def is_big_week(d: date) -> bool:
    """大小周：ISO 周序号为单数 = 大周。"""
    return d.isocalendar()[1] % 2 == 1


def expected_type(d: date) -> str:
    """本厂口径下某天应为什么类型（不读系统，用于播种与校验的对照）。"""
    name = holiday_map().get(d)
    if name:
        return DAY_HOLIDAY
    if d.isoformat() in ADJUST_WORK:
        return DAY_ADJ_WORK
    wd = d.isoweekday()
    if wd == 7:
        return DAY_REST
    if wd == 6:                       # 周六：大周上班、小周休息
        return DAY_ADJ_WORK if is_big_week(d) else DAY_REST
    return DAY_WORKDAY


def is_work(t: str) -> bool:
    return t in (DAY_WORKDAY, DAY_ADJ_WORK)


# ────────────────────────── 播种 ──────────────────────────
def build_init_payload() -> dict:
    """整年默认按"周一~周五上班"生成，假期与调休上班日一并覆盖。

    周六的大小周差异 `init` 表达不了（它只有 work_weekends 布尔），
    走第二步 `/calendars/batch` 单独覆盖。
    """
    hol = [{"date": d.isoformat(), "day_type": DAY_HOLIDAY, "name": name}
           for d, name in sorted(holiday_map().items())]
    hol += [{"date": x, "day_type": DAY_ADJ_WORK, "name": "调休上班"}
            for x in ADJUST_WORK]
    return {"work_weekends": False, "holidays": hol}


def build_big_week_overrides() -> list:
    """大周周六 → adjust_work。跳过法定假日与官方调休日（它们优先级更高）。"""
    hol = holiday_map()
    out = []
    for month in range(1, 13):
        _, ndays = pycal.monthrange(YEAR, month)
        for day in range(1, ndays + 1):
            d = date(YEAR, month, day)
            if d.isoweekday() != 6:
                continue
            if d in hol or d.isoformat() in ADJUST_WORK:
                continue
            if is_big_week(d):
                out.append({"year": YEAR, "cal_date": d.isoformat(),
                            "day_type": DAY_ADJ_WORK,
                            "name": "大小周·大周周六"})
    return out


def seed(client: httpx.Client) -> dict:
    r = client.post(f"{API}/calendars/{YEAR}/init", json=build_init_payload())
    if r.status_code != 200:
        raise RuntimeError(f"日历初始化失败 {r.status_code} {r.text[:200]}")
    init = r.json().get("data") or {}

    ov = build_big_week_overrides()
    r = client.post(f"{API}/calendars/batch", json={"dates": ov})
    if r.status_code != 200:
        raise RuntimeError(f"大周覆盖失败 {r.status_code} {r.text[:200]}")
    return {"init_days": init.get("affected"), "big_week_days": len(ov)}


# ────────────────────────── 读回 ──────────────────────────
def fetch_year(client: httpx.Client) -> dict:
    """{date: (day_type, name)}"""
    r = client.get(f"{API}/calendars/{YEAR}")
    if r.status_code != 200:
        raise RuntimeError(f"读日历失败 {r.status_code} {r.text[:200]}")
    days = (r.json().get("data") or {}).get("days") or []
    out = {}
    for x in days:
        out[_d(x["cal_date"])] = (x["day_type"], x.get("name"))
    return out


def workdays(client: httpx.Client, start: date, end: date) -> list:
    cal = fetch_year(client)
    out, cur = [], start
    while cur <= end:
        t = (cal.get(cur) or (None, None))[0]
        if t and is_work(t):
            out.append(cur)
        cur += timedelta(days=1)
    return out


def workdays_by_month(client: httpx.Client, start: date, end: date) -> dict:
    out = defaultdict(list)
    for d in workdays(client, start, end):
        out[(d.year, d.month)].append(d)
    return dict(out)


# ────────────────────────── 校验 ──────────────────────────
def check(client: httpx.Client) -> int:
    cal = fetch_year(client)
    bad = []
    if not cal:
        print("[FAIL] 系统里没有 2026 日历")
        return 1
    for d, (t, _name) in sorted(cal.items()):
        want = expected_type(d)
        if t != want:
            bad.append((d, t, want))
    print(f"日历天数 {len(cal)}，与「大小周 + 国务院 2026 放假安排」不一致 {len(bad)} 天")
    for d, got, want in bad[:15]:
        print(f"  ✗ {d} {d.strftime('%a')} 系统={got} 应为={want}")

    # 工作日统计
    half_start, half_end = date(YEAR, 5, 1), date(YEAR, 10, 31)
    bym = workdays_by_month(client, half_start, half_end)
    print("\n半年（2026-05-01 ~ 10-31）各月工作日：")
    total = 0
    for (y, m), ds in sorted(bym.items()):
        total += len(ds)
        print(f"  {y}-{m:02d}  {len(ds):>2} 天   ×2 件/班 = {len(ds) * 2:>3} 台")
    print(f"  合计 {total} 天 / 6 个月 = {total / 6:.2f} 天/月"
          f"  →  ×2 件/班 = {total / 6 * 2:.1f} 台/月")

    # 大周/小周交替抽样
    print("\n大小周抽样（周六）：")
    cur = half_start
    while cur <= half_end:
        if cur.isoweekday() == 6:
            t = (cal.get(cur) or ("?", ""))[0]
            tag = "大周" if is_big_week(cur) else "小周"
            print(f"  {cur} W{cur.isocalendar()[1]:02d} {tag} → {t}")
        cur += timedelta(days=1)

    return 1 if bad else 0


def show(client: httpx.Client, start: date, end: date):
    bym = workdays_by_month(client, start, end)
    for (y, m), ds in sorted(bym.items()):
        print(f"{y}-{m:02d}  {len(ds):>2} 天: "
              + ", ".join(d.strftime('%d') for d in ds))


def login() -> httpx.Client:
    c = httpx.Client(timeout=60)
    r = c.post(f"{API}/auth/login",
               json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        raise SystemExit(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--seed", action="store_true", help="播种到系统（会清空该年日历）")
    ap.add_argument("--check", action="store_true", help="校验播种结果")
    ap.add_argument("--show", action="store_true", help="打印工作日")
    ap.add_argument("--from", dest="frm", default=f"{YEAR}-05-01")
    ap.add_argument("--to", dest="to", default=f"{YEAR}-10-31")
    a = ap.parse_args()

    c = login()
    print(f"登录成功 tenant={TENANT} api={API} 年={YEAR}")
    if a.seed:
        r = seed(c)
        print(f"播种完成：{r['init_days']} 天基础日历 + {r['big_week_days']} 个大周周六")
    if a.show:
        show(c, _d(a.frm), _d(a.to))
    if a.check:
        return check(c)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
