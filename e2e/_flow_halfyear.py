"""AH-THR 推进器厂 —— 半年（2026-05-01 ~ 10-31）连续生产流水。

**日历是真源**：工作日一律读系统 `factory_calendars`（大小周 + 国务院 2026
放假安排），不在本脚本里另算一套。要改排班改日历，不改这里。

## 节拍模型（与产能口径对齐）

- 单班，整机线 **2 台/班**（`unit_time+setup_time` 按工位聚合后 250min/件）。
- 所以 **每天 2 台**，一周产量 = **该周工作日数 × 2**（大周 6 天 → 12 台，
  小周 5 天 → 10 台，遇法定假日的周更少）。
- 工单按**自然周**一张，报工**逐工作日**：每道工序每天各报当天的 2 台。
  逐日报工是关键 —— 只有这样，日报的"完工数 2 台/天"才真的等于产能，
  而不是"一周的量堆在某一天报完"。

## 半成品必须提前一周（这是真实约束，不是偷懒）

一张工单**完工入库后**半成品才进库存，整机才领得到。所以：

- 第 W 周：定子/转子工单生产 **第 W+1 周** 需要的量；
- 第 W 周：整机工单生产 **第 W 周** 的量，领用第 W-1 周入库的半成品；
- 第 1 周只产半成品（期初备料），第 26 周多产的一批半成品留在库里。

这不是建模缺陷：任何"两级 BOM + 完工才入库"的工厂都必须有在途/备料，
否则第一台整机永远造不出来。

## 跑法

    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      ./backend/.venv/Scripts/python.exe e2e/_flow_halfyear.py --plan
    ... --month 2026-05      # 逐月执行（可重入：状态落 _halfyear_state.json）
"""
import argparse
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime, time, timedelta

import httpx

import _factory_calendar as fc

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(HERE, "_halfyear_state.json")

START, END = date(2026, 5, 1), date(2026, 10, 31)
PER_SHIFT = 2          # 整机线 2 台/班（单班）
SCRAP_EVERY = 4        # 每 4 周在某道工序报 1 件报废，走通「报废 → 制程 NCR」

FAILS, OKS = [], []


# ══════════════════ 基础设施 ══════════════════
def load_state() -> dict:
    if os.path.isfile(STATE):
        with open(STATE, encoding="utf-8") as f:
            return json.load(f)
    return {"weeks": {}, "months": {}, "prev_qty": 0, "prev_week": None}


def save_state(st):
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def body(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def data_of(r):
    return body(r).get("data")


def msg(r):
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or d.get("code") or str(d)[:200]
    return (d if isinstance(d, str) else (r.text or ""))[:200]


def ok(name, detail=""):
    OKS.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def bad(name, detail=""):
    FAILS.append(f"{name} · {detail}")
    print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def note(t):
    print(f"  [ -- ] {t}")


class C:
    def __init__(self, cl):
        self.c = cl

    def get(self, p, **kw):
        return self.c.get(f"{API}{p}", params=kw)

    def post(self, p, j=None, **kw):
        return self.c.post(f"{API}{p}", json=j, params=kw)

    def put(self, p, j=None):
        return self.c.put(f"{API}{p}", json=j)


def paged(c, path, **kw):
    out, page = [], 1
    while True:
        r = c.get(path, page=page, page_size=100, **kw)
        if r.status_code != 200:
            return out
        d = data_of(r)
        if isinstance(d, list):
            return d
        items = (d or {}).get("items") or []
        out.extend(items)
        if len(out) >= ((d or {}).get("total") or 0) or not items:
            return out
        page += 1


def find_one(c, path, key, value, **extra):
    """按字段**精确值**查一条记录：``keyword`` 只做粗筛，本地再比一次。

    半年流水要建 ~78 张工单 / ~104 张领料单，中途断掉必须能接着跑 —— 所以
    建单之前一律先查。只信 ``keyword`` 会踩"子串命中"的坑（``2026W1`` 会
    命中 ``2026W19``），所以拿到结果集后还要逐条比 ``key == value``。
    """
    items = paged(c, path, keyword=value, **extra)
    for x in items:
        if x.get(key) == value:
            return x
    return None


# ══════════════════ 主数据 ══════════════════
def load_master(c):
    m = {"products": {p["code"]: p for p in paged(c, "/products")}}
    mats = paged(c, "/wms/materials")
    m["mat"] = {x["code"]: x for x in mats}
    m["locs"] = {x.get("location_code"): x for x in paged(c, "/wms/locations")}
    m["whs"] = {x["code"]: x for x in paged(c, "/wms/warehouses")}
    m["routes"] = {x["code"]: x for x in paged(c, "/routes")}
    m["boms"] = paged(c, "/boms")
    m["suppliers"] = paged(c, "/suppliers")
    m["standards"] = {x["name"]: x for x in paged(c, "/inspection-standards")}
    m["items"] = paged(c, "/inspection-items")
    m["steps"] = {code: data_of(c.get(f"/routes/{r['id']}/steps")) or []
                  for code, r in m["routes"].items()}
    return m


def bom_rows(m, product_id):
    return [b for b in m["boms"] if b.get("product_id") == product_id]


def need_for(m, product_code, qty):
    pid = m["products"][product_code]["id"]
    out = defaultdict(float)
    for b in bom_rows(m, pid):
        out[b["material_code"]] += (b.get("qty_per_unit") or 0) * qty * (
            1 + (b.get("scrap_rate") or 0))
    return out


def self_made():
    return {"SP-AH-STATOR", "SP-AH-ROTOR", "PRO-AH-120"}


# ══════════════════ 排程 ══════════════════
def build_plan(c):
    """按 ISO 自然周切分半年工作日 → [(year, week, [days])]。"""
    days = fc.workdays(c.c, START, END)
    weeks = defaultdict(list)
    for d in days:
        y, w, _ = d.isocalendar()
        weeks[(y, w)].append(d)
    plan = []
    for key in sorted(weeks):
        ds = sorted(weeks[key])
        plan.append({"year": key[0], "week": key[1], "days": ds,
                     "qty": len(ds) * PER_SHIFT})
    return plan


def plan_month(plan):
    bym = defaultdict(list)
    for w in plan:
        bym[(w["days"][0].year, w["days"][0].month)].append(w)
    return dict(bym)


# ══════════════════ 采购 / IQC ══════════════════
def ensure_purchase(c, m, st, year, month, semi_qty, unit_qty, first_day):
    """按本月**实际消耗**开一张采购单。

    ``semi_qty`` / ``unit_qty`` 分别对应本月半成品与整机产量（由排程算好传入）。
    两个数分开传，是因为半成品和整机的物料清单不同 —— 用一个总数会把
    整机独有的物料按半成品量多买一遍。
    """
    key = f"{year}-{month:02d}"
    if key in st["months"]:
        note(f"{key} 采购已存在 id={st['months'][key]['receipt_id']}")
        return
    need = defaultdict(float)
    for code, n in (("SP-AH-STATOR", semi_qty), ("SP-AH-ROTOR", semi_qty),
                    ("PRO-AH-120", unit_qty)):
        if n <= 0:
            continue
        for k, v in need_for(m, code, n).items():
            if k in self_made():
                continue
            need[k] += v
    qty = {k: max(1, math.ceil(v * 1.15)) for k, v in need.items()}
    sup = next((s for s in m["suppliers"] if s.get("category") == "raw"), m["suppliers"][0])
    tag = f"{year}{month:02d}"
    rno = f"RCV-AH-{tag}-01"
    hit = find_one(c, "/wms/receipt-orders", "receipt_no", rno)
    if hit:
        st["months"][key] = {"receipt_id": hit["id"], "qty": {}, "day": first_day.isoformat()}
        save_state(st)
        note(f"{key} 采购单 {rno} 已存在 id={hit['id']}，沿用")
        return
    rows = sorted(qty.items())
    r = c.post("/wms/receipt-orders", {
        "receipt_no": rno, "receipt_type": "purchase",
        "source_type": "purchase", "source_doc_no": f"PO-AH-{tag}-01",
        "warehouse_id": m["whs"]["WH-AH-RM"]["id"], "supplier_id": sup["id"],
        "items": [{"line_no": i, "material_id": m["mat"][code]["id"],
                   "expected_qty": q, "received_qty": 0,
                   "unit": m["mat"][code]["unit"],
                   "batch_no": f"PUR-{tag}-{i:02d}"}
                  for i, (code, q) in enumerate(rows, 1)]})
    if r.status_code != 200:
        return bad(f"{key} 建采购单", f"{r.status_code} {msg(r)}")
    rid = data_of(r)["id"]
    ro = data_of(c.get(f"/wms/receipt-orders/{rid}")) or {}
    items = ro.get("items") or []
    for it in items:
        q = qty[st["_code"][str(it["material_id"])]]
        c.post(f"/wms/receipt-order-items/{it['id']}/receive",
               {"received_qty": q, "batch_no": it.get("batch_no")})
        sr = c.post(f"/wms/receipt-order-items/{it['id']}/submit-inspection")
        if sr.status_code != 200:
            bad(f"{key} 送检 item={it['id']}", f"{sr.status_code} {msg(sr)}")
            continue
        iid = data_of(sr)["inspection_id"]
        rec = []
        for x in [x for x in m["items"] if x["standard_id"] == st["iqc_std"]]:
            if x.get("spec_lower_limit") is not None:
                rec.append({"item_id": x["id"], "measured_value": round(
                    (x["spec_lower_limit"] + x["spec_upper_limit"]) / 2, 3),
                    "unit": x.get("unit")})
            else:
                rec.append({"item_id": x["id"], "result": "PASS"})
        c.post(f"/inspection-orders/{iid}/results/batch",
               {"results": rec, "source": "web"})
        c.put(f"/inspection-orders/{iid}/judge", {"result": "ACC"})
        c.post(f"/wms/receipt-order-items/{it['id']}/store",
               {"stored_qty": q, "location_id": m["locs"]["WH-AH-RM-A-01"]["id"],
                "batch_no": it.get("batch_no")})
    c.post(f"/wms/receipt-orders/{rid}/complete")

    # 回写业务日：采购发生在当月第一个工作日
    st["months"][key] = {"receipt_id": rid, "qty": qty, "day": first_day.isoformat()}
    save_state(st)
    ok(f"{key} 采购入库 + IQC", f"{len(items)} 行，{sum(qty.values()):.0f} 单位，"
                                f"业务日 {first_day}")


# ══════════════════ 生产 ══════════════════
WO_SEQ = {"ST": "SP-AH-STATOR", "RT": "SP-AH-ROTOR", "UN": "PRO-AH-120"}
ROUTE = {"ST": "RTE-AH-STATOR", "RT": "RTE-AH-ROTOR", "UN": "RTE-AH-UNIT"}


def ensure_wo(c, m, wo_no, key, qty, start_day, route_code):
    """建工单；已存在则复用。返回 ``(wo_id, wo_status)``。

    半年流水要建 78 张工单，中途断一次就清库重来是不可接受的 → 建前先查。
    """
    hit = find_one(c, "/work-orders", "wo_no", wo_no)
    if hit:
        note(f"工单 {wo_no} 已存在 id={hit['id']} 状态={hit.get('wo_status')}，复用")
        return hit["id"], hit.get("wo_status")
    prod = m["products"][WO_SEQ[key]]
    r = c.post("/work-orders", {
        "wo_no": wo_no, "product_code": prod["code"], "product_name": prod["name"],
        "planned_qty": qty, "wo_type": "production", "priority": 5,
        "route_id": m["routes"][route_code]["id"],
        "scheduled_start_at": f"{start_day.isoformat()}T08:00:00",
        "scheduled_end_at": f"{start_day.isoformat()}T17:00:00",
        "remark": f"半年流水 {wo_no}",
    })
    if r.status_code != 200:
        bad(f"建工单 {wo_no}", f"{r.status_code} {msg(r)}")
        return None, None
    return data_of(r)["id"], "draft"


def advance(c, wo_id, status):
    """draft → released → in_progress。已过的状态不重放（重放会 400）。"""
    if status == "draft" or status is None:
        c.post(f"/work-orders/{wo_id}/release",
               {"force_release": True, "force_reason": "半年流水·批量下达"})
    if status in (None, "draft", "released"):
        c.post(f"/work-orders/{wo_id}/start")


def issue(c, m, wo_id, wo_no, tag, product_code, qty, day):
    """按 BOM 领料。跨仓 BOM 拆单：半成品在成品仓、其余在原料仓。"""
    need = need_for(m, product_code, qty)
    groups = {"RM": [], "FG": []}
    for code, q in sorted(need.items()):
        groups["FG" if code.startswith("SP-") else "RM"].append((code, q))
    detail = {}
    for g, rows in groups.items():
        if not rows:
            continue
        wh = m["whs"]["WH-AH-RM"] if g == "RM" else m["whs"]["WH-AH-FG"]
        iss_no = f"ISS-{day:%y%m%d}-{tag}-{g}"
        hit = find_one(c, "/wms/issue-orders", "issue_no", iss_no)
        if hit:
            iid = hit["id"]
        else:
            r = c.post("/wms/issue-orders", {
                "issue_no": iss_no, "issue_type": "production",
                "source_type": "production", "source_doc_no": wo_no,
                "work_order_id": wo_id, "warehouse_id": wh["id"],
                "recipient": "推进器总装线",
                "items": [{"line_no": i, "material_id": m["mat"][code]["id"],
                           "required_qty": round(q, 3), "issued_qty": 0,
                           "unit": m["mat"][code]["unit"]}
                          for i, (code, q) in enumerate(rows, 1)]})
            if r.status_code != 200:
                bad(f"领料 {wo_no}/{g}", f"{r.status_code} {msg(r)}")
                continue
            iid = data_of(r)["id"]
        d = data_of(c.get(f"/wms/issue-orders/{iid}")) or {}
        for it in d.get("items") or []:
            if (it.get("issued_qty") or 0) > 0:
                continue
            rr = c.post(f"/wms/issue-order-items/{it['id']}/issue",
                        {"issued_qty": it.get("required_qty") or 0,
                         "pick_status": "picked"})
            if rr.status_code != 200:
                bad(f"领料过账 {wo_no}/{g} mat={it['material_id']}",
                    f"{rr.status_code} {msg(rr)}")
        detail[g] = iid
    return detail


def report_day(c, wo_id, wo_no, steps, day, qty, tag, scrap_ops=None):
    """某一天把路线上所有工序各报一次（流水线并行：每天每道工序各出 qty 台）。

    ★ **只传 ``report_date``，不传 ``reported_at``**。这是历史补录的官方口径：
      显式传 ``reported_at`` 且早于工单 ``actual_start_at`` 会 400（`create_report`
      里 C-B2 的时序校验，有意为之）；只填 ``report_date`` 则仅告警。
      补录半年的历史产量时开工时刻只能是"现在"，传时刻就必然撞这个校验。

    ★ 报废记在**投入侧**：``input = qty + scrap``、``output = qty``。
      若写成 ``output = qty - scrap``，末道工序的累计产出就少 1 件 →
      ``completed_qty`` 少 1 → 完工入库少 1 → 下周整机领料直接缺料。
      真实车间也是"多投 1 件料来保证交足数"，这样报才对得上。
    """
    scrap_ops = scrap_ops or {}
    for seg in steps:
        op = seg["op_code"]
        scrap = scrap_ops.get(op, 0)
        r = c.post("/work-reports", {
            "work_order_id": wo_id,
            "report_date": day.isoformat(),
            "operation_code": op,
            "operation_name": seg["op_name"],
            "input_qty": qty + scrap,
            "output_qty": qty,
            "scrap_qty": scrap,
            "labor_hours": round((seg.get("unit_time") or 1) * qty / 60, 2) or 0.1,
            "machine_hours": round((seg.get("unit_time") or 1) * qty / 60, 2) or 0.1,
        })
        if r.status_code != 200:
            bad(f"报工 {wo_no} {day} {op}", f"{r.status_code} {msg(r)}")
            return False
    return True


def inspect(c, m, order_type, wo_id, material_id, process_id, std_name, qty, day, remark):
    std = m["standards"].get(std_name)
    r = c.post("/inspection-orders", {
        "order_type": order_type, "work_order_id": wo_id,
        "process_id": process_id, "material_id": material_id,
        "standard_id": std["id"] if std else None,
        "lot_qty": qty, "remark": f"{day} {remark}",
    })
    if r.status_code != 200:
        bad(f"开检验单 {remark}", f"{r.status_code} {msg(r)}")
        return None
    oid = data_of(r)["id"]
    items = [x for x in m["items"] if std and x["standard_id"] == std["id"]]
    if items:
        rec = []
        for x in items:
            if x.get("spec_lower_limit") is not None:
                rec.append({"item_id": x["id"], "measured_value": round(
                    (x["spec_lower_limit"] + x["spec_upper_limit"]) / 2, 3),
                    "unit": x.get("unit")})
            else:
                rec.append({"item_id": x["id"], "result": "PASS"})
    else:
        rec = [{"item_name": "外观", "result": "PASS"},
               {"item_name": "功能", "result": "PASS"}]
    c.post(f"/inspection-orders/{oid}/results/batch", {"results": rec, "source": "web"})
    c.put(f"/inspection-orders/{oid}/judge", {"result": "ACC"})
    return oid


def finish(c, m, wo_id, wo_no, qty, loc_code, status=None):
    if status == "completed":
        note(f"{wo_no} 已完工，跳过入库")
        return None
    r = c.post(f"/work-orders/{wo_id}/complete")
    if r.status_code != 200:
        bad(f"完工 {wo_no}", f"{r.status_code} {msg(r)}")
        return
    pr = (data_of(r) or {}).get("production_receipt") or {}
    rid = pr.get("receipt_id")
    if not rid:
        bad(f"完工未生成入库单 {wo_no}", str(pr))
        return
    ro = data_of(c.get(f"/wms/receipt-orders/{rid}")) or {}
    for it in ro.get("items") or []:
        exp = it.get("expected_qty") or qty
        c.post(f"/wms/receipt-order-items/{it['id']}/receive", {"received_qty": exp})
        c.post(f"/wms/receipt-order-items/{it['id']}/store",
               {"stored_qty": exp, "location_id": m["locs"][loc_code]["id"]})
    c.post(f"/wms/receipt-orders/{rid}/complete")
    return rid


def run_week(c, m, st, wk, semi_qty, unit_qty):
    """生产一周。

    ``semi_qty``：本周定子/转子要产的量 = **下一周**整机需要的量（提前一周备料）。
    ``unit_qty``：本周整机要产的量 = **上一周**产出的半成品量。
    两个数由调用方按排程算好传进来 —— 周长度不等（大周 6 天 / 小周 5 天 /
    遇节假日更短）时，绝不能默认"上周产多少本周就产多少"。
    """
    days = wk["days"]
    label = f"{wk['year']}W{wk['week']:02d}"
    if not days:
        return None

    # ── 定子 / 转子：产下周的量 ──
    if semi_qty > 0:
        st_ids = {}
        for key in ("ST", "RT"):
            wo_no = f"WO-AH-{days[0]:%y%m%d}-{key}"
            wo_id, status = ensure_wo(c, m, wo_no, key, semi_qty, days[0], ROUTE[key])
            if not wo_id:
                continue
            st_ids[key] = (wo_id, wo_no)
            advance(c, wo_id, status)
            issue(c, m, wo_id, wo_no, key, WO_SEQ[key], semi_qty, days[0])
            per = split_even(semi_qty, len(days))
            scrap_day = days[len(days) // 2]
            scrap = {}
            if key == "ST" and wk["week"] % SCRAP_EVERY == 0 and per[-1] > 1:
                scrap = {"CW040": 1}
            for d, q in zip(days, per):
                report_day(c, wo_id, wo_no, m["steps"][ROUTE[key]], d, q, key,
                           scrap if d == scrap_day else None)
            finish(c, m, wo_id, wo_no, semi_qty,
                   "WH-AH-FG-FG-01" if key == "ST" else "WH-AH-FG-FG-02", status)

        # 过程检验抽检：定子电检 / 转子动平衡
        if "ST" in st_ids and len(m["steps"][ROUTE["ST"]]) > 3:
            seg = m["steps"][ROUTE["ST"]][3]
            inspect(c, m, "ipqc", st_ids["ST"][0],
                    m["products"]["SP-AH-STATOR"]["id"], seg["operation_id"],
                    "定子电检标准", semi_qty, days[-1], "定子电检抽检")
        if "RT" in st_ids:
            seg = next((s for s in m["steps"][ROUTE["RT"]]
                        if s.get("step_type") == "inspect"), None)
            if seg:
                inspect(c, m, "ipqc", st_ids["RT"][0],
                        m["products"]["SP-AH-ROTOR"]["id"], seg["operation_id"],
                        "动平衡标准", semi_qty, days[-1], "转子动平衡抽检")

    # ── 整机：用上周备的半成品 ──
    if unit_qty > 0:
        wo_no = f"WO-AH-{days[0]:%y%m%d}-UN"
        wo_id, status = ensure_wo(c, m, wo_no, "UN", unit_qty, days[0], ROUTE["UN"])
        if wo_id:
            advance(c, wo_id, status)
            issue(c, m, wo_id, wo_no, "UN", WO_SEQ["UN"], unit_qty, days[0])
            per = split_even(unit_qty, len(days))
            for d, q in zip(days, per):
                report_day(c, wo_id, wo_no, m["steps"][ROUTE["UN"]], d, q, "UN")
            pid = m["products"]["PRO-AH-120"]["id"]
            for seg in m["steps"][ROUTE["UN"]]:
                if seg.get("step_type") != "inspect" or seg["op_code"] not in (
                        "EL010", "MA080", "CW190"):
                    continue
                std = {"EL010": "EOL 电性能标准",
                       "MA080": "气密标准（壳体/冷却回路）"}.get(seg["op_code"])
                inspect(c, m, "ipqc", wo_id, pid, seg["operation_id"], std,
                        unit_qty, days[-1], seg["op_name"])
            inspect(c, m, "fqc", wo_id, pid, None, "EOL 电性能标准",
                    unit_qty, days[-1], "整机成品检验")
            finish(c, m, wo_id, wo_no, unit_qty, "WH-AH-FG-FG-01", status)

    ok(f"{label} 生产", f"{len(days)} 工作日 · 半成品 {semi_qty}（备下周）· "
                        f"整机 {unit_qty}（用上周料）")
    return {"label": label, "days": [d.isoformat() for d in days],
            "semi_qty": semi_qty, "unit_qty": unit_qty}


def split_even(total: int, n: int):
    if n <= 0:
        return []
    base, rem = divmod(total, n)
    return [base + (1 if i < rem else 0) for i in range(n)]


# ══════════════════ 主流程 ══════════════════
def ensure_iqc_std(c, m):
    name = "来料通用检验标准（IQC）"
    found = [s for s in paged(c, "/inspection-standards") if s.get("name") == name]
    sid = min(s["id"] for s in found) if found else None
    if sid is None:
        c.post("/inspection-standards", {"name": name, "standard_type": "enterprise",
                                         "version": "1.0", "remark": "来料通用"})
        found = [s for s in paged(c, "/inspection-standards") if s.get("name") == name]
        sid = min(s["id"] for s in found)
    have = {i["item_name"] for i in paged(c, "/inspection-items") if i["standard_id"] == sid}
    for it in ({"item_name": "外观", "unit": "", "sort_order": 1},
               {"item_name": "关键尺寸", "spec_lower_limit": 9.95,
                "spec_upper_limit": 10.05, "unit": "mm", "sort_order": 2},
               {"item_name": "材质证明书", "unit": "", "sort_order": 3}):
        if it["item_name"] not in have:
            c.post("/inspection-items", {**it, "standard_id": sid})
    return sid


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plan", action="store_true", help="只打印排程，不写数据")
    ap.add_argument("--month", action="append", default=[], help="2026-05 … 只跑某月")
    ap.add_argument("--week", action="append", default=[], help="2026W19 … 只跑某周（冒烟用）")
    ap.add_argument("--reset", action="store_true")
    a = ap.parse_args()

    if a.reset and os.path.isfile(STATE):
        os.remove(STATE)
    st = load_state()

    cl = httpx.Client(timeout=90)
    r = cl.post(f"{API}/auth/login",
                json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    cl.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                       "X-Tenant-Id": TENANT})
    c = C(cl)
    m = load_master(c)
    st["_code"] = {str(v["id"]): k for k, v in m["mat"].items()}
    st["iqc_std"] = ensure_iqc_std(c, m)
    save_state(st)

    plan = build_plan(c)
    bym = plan_month(plan)
    idx = {f"{w['year']}W{w['week']:02d}": i for i, w in enumerate(plan)}

    def sched(wk):
        """本周该产多少半成品 / 多少整机，全部从**全局排程**取。

        半成品 = 下一周整机量（提前一周备料）；整机 = 上一周半成品量。
        必须用全局下标而不是"上回跑了多少"，因为周长度不等（大周 6 天、
        小周 5 天、遇假期更短），跨月的周也不连续。
        """
        i = idx[f"{wk['year']}W{wk['week']:02d}"]
        semi = plan[i + 1]["qty"] if i + 1 < len(plan) else 0
        unit = plan[i - 1]["qty"] if i > 0 else 0
        return semi, unit

    print(f"半年排程：{len(plan)} 个自然周 / {sum(len(w['days']) for w in plan)} 个工作日 / "
          f"计划总产 {sum(w['qty'] for w in plan)} 台")
    for (y, mo), ws in sorted(bym.items()):
        pairs = [sched(w) for w in ws]
        print(f"  {y}-{mo:02d}  {len(ws)} 周  {sum(len(w['days']) for w in ws)} 工作日  "
              f"整机 {sum(p[1] for p in pairs):>3} 台  半成品 {sum(p[0] for p in pairs):>3} 套")
    if a.plan:
        print("\n逐周排程（半成品备下周 / 整机用上周）：")
        for wk in plan:
            semi, unit = sched(wk)
            print(f"  {wk['year']}W{wk['week']:02d}  {len(wk['days'])} 天  "
                  f"({wk['days'][0]} ~ {wk['days'][-1]})  半成品 {semi:>2}  整机 {unit:>2}")
        return 0

    months = a.month or [f"{y}-{mo:02d}" for (y, mo) in sorted(bym)]
    for key in months:
        y, mo = int(key[:4]), int(key[5:])
        ws = bym.get((y, mo))
        if not ws:
            note(f"{key} 无工作日，跳过")
            continue
        pairs = [sched(w) for w in ws]
        m_semi = sum(p[0] for p in pairs)
        m_unit = sum(p[1] for p in pairs)
        print(f"\n═══ {key} ─── {len(ws)} 周 / "
              f"{sum(len(w['days']) for w in ws)} 工作日 / "
              f"整机 {m_unit} 台 / 半成品 {m_semi} 套 ═══")
        ensure_purchase(c, m, st, y, mo, m_semi, m_unit, ws[0]["days"][0])
        for wk, (semi, unit) in zip(ws, pairs):
            label = f"{wk['year']}W{wk['week']:02d}"
            if a.week and label not in a.week:
                continue
            if label in st["weeks"]:
                note(f"{label} 已完成，跳过")
                continue
            nf0 = len(FAILS)
            res = run_week(c, m, st, wk, semi, unit)
            if len(FAILS) > nf0:
                # ★ 有断点就不记账，否则下周会"看起来做完了"、实际缺一段数据
                bad(f"{label} 未记账", f"本周新增 {len(FAILS) - nf0} 个断点")
                continue
            st["weeks"][label] = res
            save_state(st)

    print("\n" + "=" * 62)
    print(f"通道 {len(OKS)} · 断点 {len(FAILS)}")
    for f in FAILS[:20]:
        print(f"  ✗ {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
