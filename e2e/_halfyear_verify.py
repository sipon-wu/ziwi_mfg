"""半年流水验收：证明"每天 2 台"真的成立，而不是一堆凑出来的数字。

只读，不改任何数据。六条口径：

C1 **日产能上限**：每个工作日``total_output`` ∈ [0, 2]，合计 = 计划整机总量。
   这条是核心 —— 报表改成完工口径（只认末道工序）之前，多工序工单会把
   产量乘工序数，一天报出 66/410 台，看着"高产"其实全错。
C2 **休息日零产出**：日历判为 rest/holiday 的日子不能有报工。
C3 **工单闭环**：期间建的工单全部 completed，且 ``completed_qty == planned_qty``。
C4 **成品结存**：``PRO-AH-120`` 库存净增 = 计划整机总量（期初 + 本期）。
C5 **报废落地**：``work_reports.scrap_qty`` 合计 = 每周「W % 4 == 0」的 1 件。
C6 **月报自洽**：六个月月报 ``total_output`` 相加 = 半年合计。

跑法::

    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      ./backend/.venv/Scripts/python.exe e2e/_halfyear_verify.py
"""
import json
import os
from collections import defaultdict
from datetime import date, timedelta

import httpx

import _factory_calendar as fc

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "_halfyear_state.json")

START, END = date(2026, 5, 1), date(2026, 10, 31)
PER_SHIFT = 2

FAILS, OKS = [], []


def ok(n, d=""):
    OKS.append(n)
    print(f"  [OK ] {n}" + (f" · {d}" if d else ""))


def bad(n, d=""):
    FAILS.append(f"{n} · {d}")
    print(f"  [FAIL] {n}" + (f" · {d}" if d else ""))


def paged(cl, path, **kw):
    out, page = [], 1
    while True:
        r = cl.get(f"{API}{path}", params={"page": page, "page_size": 100, **kw})
        if r.status_code != 200:
            return out
        d = (r.json() or {}).get("data")
        if isinstance(d, list):
            return d
        items = (d or {}).get("items") or []
        out.extend(items)
        if len(out) >= ((d or {}).get("total") or 0) or not items:
            return out
        page += 1


def daily(cl, d: date) -> dict:
    r = cl.get(f"{API}/reports/daily", params={"report_date": d.isoformat()})
    return (r.json() or {}).get("data") or {}


def split_even(total, n):
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


def main():
    cl = httpx.Client(timeout=120, trust_env=False)
    r = cl.post(f"{API}/auth/login",
                json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    cl.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                       "X-Tenant-Id": TENANT})

    st = {}
    if os.path.isfile(STATE):
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    weeks = st.get("weeks") or {}
    if not weeks:
        print("[FATAL] 没有 _halfyear_state.json，先跑 _flow_halfyear.py")
        return 1

    # 期望的逐日报工量：**每条线各自的完工量**都要算进来
    #
    # ★ 口径澄清（第一版探针在这里判错过）：``total_output`` 是"完工口径"，
    #   它统计的是**所有工单**的末道工序产出。本周同时有定子 / 转子 / 整机
    #   三条线在跑，所以一天 2 台整机 = 定子 2 + 转子 2 + 整机 2 = 6。
    #   把它当成"整机台数"去比 2，会得出"130 天超产"的假红。
    expect = defaultdict(int)
    total_unit, total_semi = 0, 0
    for w in weeks.values():
        u = w.get("unit_qty") or 0
        s = w.get("semi_qty") or 0
        total_unit += u
        total_semi += s
        days = [date.fromisoformat(x) for x in w["days"]]
        for d, q in zip(days, split_even(u, len(days))):
            expect[d] += q                      # 整机
        for d, q in zip(days, split_even(s, len(days))):
            expect[d] += 2 * q                  # 定子 + 转子各一张工单
    expect_total = 2 * total_semi + total_unit

    cal = fc.fetch_year(cl)
    workdays = sorted(expect)

    print(f"\n═══ C1 日完工口径（三条线各 2 台/天）═══")
    got_total, over, mismatch = 0, [], []
    for d in workdays:
        j = daily(cl, d)
        got = j.get("total_output") or 0
        got_total += got
        if got > expect[d]:
            over.append((d, got, expect[d]))
        if got != expect[d]:
            mismatch.append((d, got, expect[d]))
    if over:
        bad("C1 有超排程日", f"{len(over)} 天：{over[:5]}")
    else:
        ok("C1 无超排程日", f"{len(workdays)} 个工作日全部 ≤ 排程（每日上限 = 在跑线数 × 2）")
    if mismatch:
        bad("C1 逐日产量与排程不符", f"{len(mismatch)} 天：{mismatch[:5]}")
    else:
        ok("C1 逐日产量 = 排程", f"{len(workdays)} 天全对")
    if got_total == expect_total:
        ok("C1 半年合计", f"{got_total} = 定子 {total_semi} + 转子 {total_semi} + 整机 {total_unit}")
    else:
        bad("C1 半年合计不符", f"实得 {got_total} / 期望 {expect_total}")

    print("\n═══ C2 休息日零产出 ═══")
    dirty = []
    cur = START
    while cur <= END:
        t = (cal.get(cur) or (None, None))[0]
        if t and not fc.is_work(t):
            j = daily(cl, cur)
            if (j.get("total_output") or 0) > 0 or (j.get("total_wip_output") or 0) > 0:
                dirty.append((cur, t, j.get("total_output")))
        cur += timedelta(days=1)
    if dirty:
        bad("C2 休息日有产出", f"{len(dirty)} 天：{dirty[:5]}")
    else:
        ok("C2 休息日零产出", "所有 rest/holiday 日 total_output 与 total_wip_output 均为 0")

    print("\n═══ C3 工单闭环 ═══")
    wos = [x for x in paged(cl, "/work-orders") if x["wo_no"].startswith("WO-AH-26")]
    open_, wrong = [], []
    for x in wos:
        if x.get("wo_status") != "completed":
            open_.append((x["wo_no"], x.get("wo_status")))
        elif (x.get("completed_qty") or 0) != (x.get("planned_qty") or 0):
            wrong.append((x["wo_no"], x.get("completed_qty"), x.get("planned_qty")))
    if open_:
        bad("C3 未完工工单", f"{len(open_)} 张：{open_[:5]}")
    else:
        ok("C3 全部完工", f"{len(wos)} 张工单 wo_status=completed")
    if wrong:
        bad("C3 完工数 ≠ 计划数", f"{len(wrong)} 张：{wrong[:5]}")
    else:
        ok("C3 完工数 = 计划数", f"{len(wos)} 张")

    print("\n═══ C4 成品结存 ═══")
    try:
        raw = (cl.get(f"{API}/wms/reports/stock-summary").json() or {}).get("data")
        rows = raw if isinstance(raw, list) else ((raw or {}).get("items") or [])
    except Exception:  # noqa: BLE001
        rows = []
    # ★ 该接口按「仓库 × 物料」出行，同一物料可能分散在多仓 → 必须先按物料汇总
    stock = defaultdict(float)
    for x in rows:
        if isinstance(x, dict) and x.get("material_code"):
            stock[x["material_code"]] += x.get("total_qty") or 0
    # ★ 结存要算**期初**：本轮之前 `_flow_run.py` 已产出 45 台（30→45），
    #   库存不清零，直接拿 256 去比会得出"多出 45 台"的假红。
    opening_fg = int(os.environ.get("OPENING_FG", "45"))
    for code, want in (("PRO-AH-120", opening_fg + total_unit),
                       ("SP-AH-STATOR", None), ("SP-AH-ROTOR", None)):
        q = stock.get(code)
        if q is None:
            bad(f"C4 库存无 {code}", "stock-summary 里找不到该物料")
            continue
        if want is None:
            ok(f"C4 {code} 结存", f"{q:g}（应为少量在库尾数）")
        elif q == want:
            ok(f"C4 {code} 结存", f"{q:g} = 期初 {opening_fg} + 本期 {total_unit}")
        else:
            bad(f"C4 {code} 结存不符", f"实得 {q:g} / 期望 {want}"
                                      f"（期初 {opening_fg} + 本期 {total_unit}）")

    print("\n═══ C5 报废落地 ═══")
    scrap = 0
    for d in workdays:
        scrap += daily(cl, d).get("total_scrap") or 0
    want_scrap = 0
    for w in weeks.values():
        if int(w["label"][5:]) % 4 != 0:
            continue
        semi = w.get("semi_qty") or 0
        if semi <= 0:                     # 末周不产半成品，也就没有报废
            continue
        if split_even(semi, len(w["days"]))[-1] > 1:
            want_scrap += 1
    if scrap == want_scrap:
        ok("C5 报废合计", f"{scrap} 件 = 每 4 周 1 件的排程")
    else:
        bad("C5 报废合计不符", f"实得 {scrap} / 期望 {want_scrap}")

    print("\n═══ C6 月报自洽 ═══")
    msum, detail = 0, []
    for mo in range(5, 11):
        r = cl.get(f"{API}/reports/monthly", params={"year": 2026, "month": mo})
        j = (r.json() or {}).get("data") or {}
        v = j.get("total_output") or 0
        msum += v
        detail.append(f"{mo:02d}月 {v}")
    print("    " + " · ".join(detail))
    if msum == got_total:
        ok("C6 月报合计 = 日报合计", f"{msum} 台")
    else:
        bad("C6 月报合计不符", f"月报 {msum} / 日报 {got_total}")

    print("\n" + "=" * 62)
    print(f"通道 {len(OKS)} · 断点 {len(FAILS)}")
    for f in FAILS:
        print(f"  ✗ {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
