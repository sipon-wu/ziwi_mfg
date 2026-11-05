"""AH-THR 推进器厂 —— 全链路真实业务串跑（分阶段、可重入）。

与 `run_all.py` 里的探针不同：探针每一条都自建自测、跑完就丢；本脚本
按**真实业务的先后依赖**把一条链一次走完，每一步都回读校验（单据状态、
库存数量、报表数字），而不是"接口 200 就算通"。

链路::

    p1  采购收货 → 来料送检(IQC) → 判定 → 上架入库 → 入库单结案
    p2  建生产工单（定子 30 / 转子 30 / 整机 15）
    p3  定子·转子：下达(含 BOM 快照+齐套检查) → 开工 → 领料出库
    p4  定子·转子：逐工序报工 + 过程检验(IPQC) → 完工 → 半成品入库上架
    p5  整机：下达 → 开工 → 领料（含上一步入库的半成品）
    p6  整机：逐工序报工 + 过程检验 + 成品检验(FQC) → 完工 → 成品入库上架
    p7  生产/品质/仓储报表与看板核对、批次正反追溯

跑法::

    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      ./backend/.venv/Scripts/python.exe e2e/_flow_run.py --phase p1

    --phase 可逐个执行，状态落在 e2e/_flow_state.json（重跑同一阶段会跳过已完成的步骤）
    --dry-run 只读盘点，不写任何数据
"""
import argparse
import json
import math
import os
from collections import defaultdict
from datetime import date, datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
HERE = os.path.dirname(os.path.abspath(__file__))
STATE_FILE = os.path.join(HERE, "_flow_state.json")

TODAY = date.today()
YMD = TODAY.strftime("%Y%m%d")
MMDD = TODAY.strftime("%m%d")

# 计划批量：定子 30 件、转子 30 件、整机 15 台
ST_QTY, RT_QTY, UN_QTY = 30, 30, 15
# 定子灌胶报废 1 件（用于打通「报废 → 制程 NCR」闭环），下游按合格数流转
ST_SCRAP, ST_SCRAP_OP = 1, "CW040"

FAILS, OKS = [], []


# ══════════════════════ 基础设施 ══════════════════════
def load_state() -> dict:
    if os.path.isfile(STATE_FILE):
        with open(STATE_FILE, encoding="utf-8") as f:
            return json.load(f)
    return {}


def save_state(st: dict) -> None:
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)


def body(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def msg(r) -> str:
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or d.get("code") or str(d)[:200]
    if isinstance(d, str):
        return d[:200]
    return (r.text or "")[:200]


def payload(r):
    return body(r).get("data")


def ok(name, detail=""):
    OKS.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def bad(name, detail=""):
    FAILS.append(f"{name} · {detail}")
    print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))


def note(text):
    print(f"  [ -- ] {text}")


class C:
    """薄封装：统一错误文案，避免每个调用点各写一遍。"""

    def __init__(self, client: httpx.Client):
        self.c = client

    def get(self, path, **params):
        return self.c.get(f"{API}{path}", params=params)

    def post(self, path, json_=None, **params):
        return self.c.post(f"{API}{path}", json=json_, params=params)

    def put(self, path, json_=None):
        return self.c.put(f"{API}{path}", json=json_)


def paged(c: C, path, **params):
    """把所有分页拉平（上限 100/页）。"""
    out, page = [], 1
    while True:
        r = c.get(path, page=page, page_size=100, **params)
        if r.status_code != 200:
            return out
        d = payload(r)
        if isinstance(d, list):
            return d
        items = (d or {}).get("items") or []
        out.extend(items)
        total = (d or {}).get("total") or 0
        if len(out) >= total or not items:
            return out
        page += 1


# ══════════════════════ 主数据读取 ══════════════════════
def load_master(c: C) -> dict:
    m = {}
    m["products"] = {p["code"]: p for p in paged(c, "/products")}
    m["materials"] = paged(c, "/wms/materials")
    by_code = {x["code"]: x for x in m["materials"]}
    m["mat"] = by_code
    m["locs"] = {x.get("location_code"): x for x in paged(c, "/wms/locations")}
    m["whs"] = {x["code"]: x for x in paged(c, "/wms/warehouses")}
    wcs = paged(c, "/work-centers")
    m["wc"] = {x["code"]: x for x in wcs}
    m["routes"] = {x["code"]: x for x in paged(c, "/routes")}
    m["boms"] = paged(c, "/boms")
    m["suppliers"] = paged(c, "/suppliers")
    m["standards"] = {x["name"]: x for x in paged(c, "/inspection-standards")}
    m["std_items"] = paged(c, "/inspection-items")
    return m


def route_steps(c: C, route_id: int):
    r = c.get(f"/routes/{route_id}/steps")
    return payload(r) or []


def bom_need(m: dict) -> dict:
    """按 BOM 算原材料净需求（含 BOM 上配的损耗率），不含自制半成品。"""
    plan = {1: ST_QTY, 2: RT_QTY, 3: UN_QTY}  # product_id → 计划数
    self_made = {"SP-AH-STATOR", "SP-AH-ROTOR", "PRO-AH-120"}
    need = defaultdict(float)
    for b in m["boms"]:
        pid = b.get("product_id")
        if pid not in plan:
            continue
        if b["material_code"] in self_made:
            continue
        need[b["material_code"]] += (b.get("qty_per_unit") or 0) * plan[pid] * (
            1 + (b.get("scrap_rate") or 0))
    return dict(need)


# ══════════════════════ p1 采购入库 ══════════════════════
def ensure_iqc_standard(c: C, m: dict) -> int:
    """来料通用检验标准：库里 9 条标准全是过程/成品口径，来料检验没标准可挂。

    ★ ``POST /inspection-standards`` 只回 ``{"code":0,"message":"创建成功"}``，
      **不回 id**（其余创建接口都回 ``data.id``）→ 建完必须回查列表拿 id。
    """
    name = "来料通用检验标准（IQC）"
    found = [s for s in paged(c, "/inspection-standards") if s.get("name") == name]
    if found:
        sid = min(s["id"] for s in found)
        note(f"来料检验标准已存在 id={sid}（同名 {len(found)} 条）")
    else:
        r = c.post("/inspection-standards",
                   {"name": name, "standard_type": "enterprise", "version": "1.0",
                    "remark": "推进器厂来料通用：外观 / 关键尺寸 / 材质证明"})
        if r.status_code != 200:
            raise RuntimeError(f"建来料检验标准失败 {r.status_code} {msg(r)}")
        found = [s for s in paged(c, "/inspection-standards") if s.get("name") == name]
        if not found:
            raise RuntimeError("建来料检验标准后回查不到")
        sid = min(s["id"] for s in found)
        ok("建来料检验标准", f"id={sid}")

    have = {i["item_name"] for i in paged(c, "/inspection-items") if i["standard_id"] == sid}
    added = 0
    for it in ({"item_name": "外观", "unit": "", "sort_order": 1},
               {"item_name": "关键尺寸", "spec_lower_limit": 9.95,
                "spec_upper_limit": 10.05, "unit": "mm", "sort_order": 2},
               {"item_name": "材质证明书", "unit": "", "sort_order": 3}):
        if it["item_name"] in have:
            continue
        c.post("/inspection-items", {**it, "standard_id": sid})
        added += 1
    if added:
        ok("补齐来料检验项", f"+{added} 项")
    # 检验项可能刚建，原地刷新，别让调用方拿着启动时的旧快照
    m["std_items"] = paged(c, "/inspection-items")
    return sid


def phase_p1(c: C, m: dict, st: dict):
    print("\n═══ p1 采购收货 → 来料检验 → 上架入库 ═══")
    need = bom_need(m)
    note(f"BOM 净需求 {len(need)} 种原材料：")
    for code, q in sorted(need.items()):
        note(f"     {code:<14} {round(q, 3)}")

    sid = ensure_iqc_standard(c, m)
    items_std = [i for i in m["std_items"] if i["standard_id"] == sid]

    sup = next((s for s in m["suppliers"]
                if (s.get("category") or "") in ("raw", "standard")), None) or m["suppliers"][0]
    wh_rm = m["whs"]["WH-AH-RM"]
    loc_ok = m["locs"]["WH-AH-RM-A-01"]

    # 采购量 = 净需求 ×1.15 向上取整（留余量，避免齐套检查因四舍五入判缺料）
    qty = {code: max(1, math.ceil(q * 1.15)) for code, q in need.items()}
    batch = f"PUR-AH-{MMDD}"

    if st.get("receipt_id"):
        receipt_id = st["receipt_id"]
        note(f"入库单已存在 id={receipt_id}，跳过建单")
    else:
        r = c.post("/wms/receipt-orders", {
            "receipt_no": f"RCV-AH-{YMD}-01",
            "receipt_type": "purchase",
            "source_type": "purchase",
            "source_doc_no": f"PO-AH-{YMD}-01",
            "warehouse_id": wh_rm["id"],
            "supplier_id": sup["id"],
            "items": [{"line_no": i, "material_id": m["mat"][code]["id"],
                       "expected_qty": q, "received_qty": 0,
                       "unit": m["mat"][code]["unit"],
                       "batch_no": f"{batch}-{i:02d}"}
                      for i, (code, q) in enumerate(sorted(qty.items()), 1)],
        })
        if r.status_code != 200:
            return bad("建采购入库单", f"{r.status_code} {msg(r)}")
        receipt_id = payload(r)["id"]
        st["receipt_id"] = receipt_id
        st["qty"] = qty
        save_state(st)
        ok("建采购入库单", f"RCV-AH-{YMD}-01 id={receipt_id}，"
                           f"{len(qty)} 行，供应商={sup['short_name']}")

    ro = payload(c.get(f"/wms/receipt-orders/{receipt_id}")) or {}
    ro_items = ro.get("items") or []
    if not ro_items:
        return bad("入库单明细读取", "GET /wms/receipt-orders/{id} 未返回 items")
    note(f"入库单 {ro.get('receipt_no')} 状态={ro.get('status')} 明细 {len(ro_items)} 行")

    # ── ① 收货登记（自动进待检区） ──
    for it in ro_items:
        if (it.get("received_qty") or 0) > 0:
            continue
        q = qty_by_mat(st, it["material_id"])
        r = c.post(f"/wms/receipt-order-items/{it['id']}/receive",
                   {"received_qty": q, "batch_no": it.get("batch_no")})
        if r.status_code != 200:
            return bad(f"收货登记 material={it['material_id']}", f"{r.status_code} {msg(r)}")
    ok("收货登记入待检区", f"{len(ro_items)} 行")

    # ── ② 来料送检（开 IQC 单） ──
    insp = st.setdefault("iqc", {})
    for it in ro_items:
        key = str(it["id"])
        if key in insp:
            continue
        r = c.post(f"/wms/receipt-order-items/{it['id']}/submit-inspection")
        if r.status_code != 200:
            return bad(f"来料送检 item={it['id']}", f"{r.status_code} {msg(r)}")
        d = payload(r)
        insp[key] = {"inspection_id": d["inspection_id"], "no": d.get("inspection_no")}
        # 送检自动开的单没挂标准 → 补挂，检验员手机上才看得到"本单该测的这几项"
        c.put(f"/inspection-orders/{d['inspection_id']}", {"standard_id": sid})
    save_state(st)
    ok("来料送检（IQC）", f"{len(insp)} 张单，单号首个 {next(iter(insp.values()))['no']}")

    # ── ③ 录入检验结果 + 判定合格 ──
    for key, info in insp.items():
        oid = info["inspection_id"]
        if info.get("judged"):
            continue
        rec = []
        for it in items_std:
            measured = None
            if it.get("spec_lower_limit") is not None:
                measured = round((it["spec_lower_limit"] + it["spec_upper_limit"]) / 2, 3)
            rec.append({"item_id": it["id"], "measured_value": measured,
                        "unit": it.get("unit"),
                        "result": None if measured is not None else "PASS"})
        r = c.post(f"/inspection-orders/{oid}/results/batch",
                   {"results": rec, "source": "web"})
        if r.status_code != 200:
            return bad(f"IQC 录入 order={oid}", f"{r.status_code} {msg(r)}")
        r = c.put(f"/inspection-orders/{oid}/judge", {"result": "ACC", "remark": "来料合格"})
        if r.status_code != 200:
            return bad(f"IQC 判定 order={oid}", f"{r.status_code} {msg(r)}")
        info["judged"] = "ACC"
    save_state(st)
    ok("IQC 录入与判定", f"{len(insp)} 张单全部 ACC")

    # ── ④ 上架确认（待检区 → A-01） ──
    for it in ro_items:
        if (it.get("stored_qty") or 0) > 0:
            continue
        r = c.post(f"/wms/receipt-order-items/{it['id']}/store",
                   {"stored_qty": it.get("received_qty"),
                    "location_id": loc_ok["id"],
                    "batch_no": it.get("batch_no")})
        if r.status_code != 200:
            return bad(f"上架 item={it['id']}", f"{r.status_code} {msg(r)}")
    r = c.post(f"/wms/receipt-orders/{receipt_id}/complete")
    if r.status_code != 200:
        return bad("入库单结案", f"{r.status_code} {msg(r)}")
    ok("上架确认 + 入库单结案", f"{len(ro_items)} 行 → A-01")

    # ── ⑤ 回读校验：现存数量必须 ≥ 净需求 ──
    stock = paged(c, "/wms/reports/stock-summary", warehouse_id=wh_rm["id"])
    have = {}
    for s in stock:
        have[s["material_code"]] = have.get(s["material_code"], 0) + (s.get("total_qty") or 0)
    short = [(code, round(q, 3), round(have.get(code, 0), 3))
             for code, q in need.items() if have.get(code, 0) < q]
    if short:
        bad("原材料现存 ≥ 净需求", f"缺 {short[:5]}")
    else:
        ok("原材料现存 ≥ 净需求", f"{len(need)} 种全齐")
    st["p1_done"] = True
    save_state(st)


def qty_by_mat(st: dict, material_id: int) -> float:
    code = st.get("_code_by_mat", {}).get(str(material_id))
    return st["qty"][code]


# ══════════════════════ p2 建工单 ══════════════════════
WO_DEF = {
    "ST": {"product": "SP-AH-STATOR", "qty": ST_QTY, "route": "RTE-AH-STATOR"},
    "RT": {"product": "SP-AH-ROTOR", "qty": RT_QTY, "route": "RTE-AH-ROTOR"},
    "UN": {"product": "PRO-AH-120", "qty": UN_QTY, "route": "RTE-AH-UNIT"},
}


def phase_p2(c: C, m: dict, st: dict):
    print("\n═══ p2 建生产工单 ═══")
    wos = st.setdefault("wo", {})
    for key, d in WO_DEF.items():
        if key in wos:
            note(f"工单 {key} 已存在 id={wos[key]['id']}，跳过")
            continue
        prod = m["products"][d["product"]]
        r = c.post("/work-orders", {
            "wo_no": f"WO-AH-{YMD}-{key}1",
            "product_code": prod["code"],
            "product_name": prod["name"],
            "planned_qty": d["qty"],
            "wo_type": "production",
            "priority": 5 if key == "UN" else 3,
            "route_id": m["routes"][d["route"]]["id"],
            "remark": f"{YMD} 推进器厂全流程批次",
        })
        if r.status_code != 200:
            return bad(f"建工单 {key}", f"{r.status_code} {msg(r)}")
        pd = payload(r)
        wos[key] = {"id": pd["id"], "wo_no": pd["wo_no"],
                    "route_id": m["routes"][d["route"]]["id"],
                    "product": prod, "planned": d["qty"]}
        warn = pd.get("warnings") or []
        ok(f"建工单 {pd['wo_no']}", f"id={pd['id']} 计划 {d['qty']} {prod['unit']}"
           + (f"，警告 {warn}" if warn else ""))
    save_state(st)


# ══════════════════════ p3/p5 下达 + 开工 + 领料 ══════════════════════
def issue_for(c: C, m: dict, st: dict, key: str):
    """按 BOM 生成领料单。

    ★ 一张领料单只能挂**一个仓库**，而整机 BOM 横跨两个库：半成品（转子/定子）
      在成品仓、其余原材料在原料仓 → 必须拆成两张单。写成一张会有一半行报
      「物料 N 无可用的库存记录」——不是缺料，是发错了仓。
    """
    wo = st["wo"][key]
    prod_id = wo["product"]["id"]
    plan = wo["planned"]
    groups = {"RM": [], "FG": []}
    for b in m["boms"]:
        if b.get("product_id") != prod_id:
            continue
        q = (b.get("qty_per_unit") or 0) * plan * (1 + (b.get("scrap_rate") or 0))
        code = b["material_code"]
        groups["FG" if code.startswith("SP-") else "RM"].append({
            "code": code, "qty": round(q, 3),
            "unit": b.get("unit") or m["mat"][code]["unit"]})

    ids = st["wo"][key].setdefault("issue_ids", {})
    for tag, rows in groups.items():
        if not rows:
            continue
        if tag in ids:
            note(f"领料单 {key}/{tag} 已存在 id={ids[tag]}，跳过建单")
            issue_id = ids[tag]
        else:
            wh = m["whs"]["WH-AH-RM"] if tag == "RM" else m["whs"]["WH-AH-FG"]
            r = c.post("/wms/issue-orders", {
                "issue_no": f"ISS-AH-{YMD}-{key}-{tag}",
                "issue_type": "production",
                "source_type": "production",
                "source_doc_no": wo["wo_no"],
                "work_order_id": wo["id"],
                "warehouse_id": wh["id"],
                "recipient": "推进器总装线",
                "items": [{"line_no": i, "material_id": m["mat"][x["code"]]["id"],
                           "required_qty": x["qty"], "issued_qty": 0, "unit": x["unit"]}
                          for i, x in enumerate(rows, 1)],
            })
            if r.status_code != 200:
                bad(f"建领料单 {key}/{tag}", f"{r.status_code} {msg(r)}")
                continue
            issue_id = payload(r)["id"]
            ids[tag] = issue_id
            save_state(st)
            ok(f"建领料单 ISS-AH-{YMD}-{key}-{tag}",
               f"id={issue_id}，{len(rows)} 行，来自 {wh['code']}")

        d = payload(c.get(f"/wms/issue-orders/{issue_id}")) or {}
        items = d.get("items") or []
        if not items:
            bad(f"领料单明细读取 {key}/{tag}", "GET 未返回 items")
            continue
        fails = 0
        for it in items:
            if (it.get("issued_qty") or 0) > 0:
                continue
            r = c.post(f"/wms/issue-order-items/{it['id']}/issue",
                       {"issued_qty": it.get("required_qty") or 0,
                        "pick_status": "picked"})
            if r.status_code != 200:
                fails += 1
                bad(f"领料出库 item={it['id']} material={it['material_id']}",
                    f"{r.status_code} {msg(r)}")
        if not fails:
            ok(f"领料出库过账 {key}/{tag}", f"{len(items)} 行")


def phase_release(c: C, m: dict, st: dict, keys):
    """下达 + 开工。可重入：已下达/已开工/已完工的单子跳过，不硬撞状态机。"""
    for key in keys:
        wo = st["wo"][key]
        cur = (payload(c.get(f"/work-orders/{wo['id']}")) or {}).get("wo_status")
        if cur not in ("draft", None):
            note(f"{wo['wo_no']} 当前状态={cur}，跳过下达")
        else:
            r = c.post(f"/work-orders/{wo['id']}/release", {"force_release": False})
            if r.status_code != 200:
                bad(f"下达 {wo['wo_no']}", f"{r.status_code} {msg(r)}")
                continue
            ok(f"下达 {wo['wo_no']}", "BOM 快照 + 齐套检查完成")
            cur = (payload(c.get(f"/work-orders/{wo['id']}")) or {}).get("wo_status")

        chk = c.get(f"/work-orders/{wo['id']}/material-check")
        if chk.status_code == 200:
            cd = payload(chk) or {}
            short = cd.get("shortage_items") or cd.get("shortages") or []
            if short:
                bad(f"齐套检查 {wo['wo_no']}", f"{len(short)} 项缺料：{short[:3]}")
            else:
                ok(f"齐套检查 {wo['wo_no']}", "不缺料")

        if cur == "released":
            r = c.post(f"/work-orders/{wo['id']}/start")
            if r.status_code != 200:
                bad(f"开工 {wo['wo_no']}", f"{r.status_code} {msg(r)}")
            else:
                ok(f"开工 {wo['wo_no']}")
        else:
            note(f"{wo['wo_no']} 当前状态={cur}，跳过开工")


def phase_p3(c: C, m: dict, st: dict):
    print("\n═══ p3 定子·转子 下达 / 开工 / 领料 ═══")
    phase_release(c, m, st, ["ST", "RT"])
    for key in ("ST", "RT"):
        issue_for(c, m, st, key)


def phase_p5(c: C, m: dict, st: dict):
    print("\n═══ p5 整机 下达 / 开工 / 领料（含半成品） ═══")
    phase_release(c, m, st, ["UN"])
    issue_for(c, m, st, "UN")


# ══════════════════════ p4/p6 报工 + 检验 + 完工 + 入库 ══════════════════════
def std_for_op(m: dict, op_code: str, key: str):
    """工序 → 检验标准。没有对应标准就返回 None（走降级：按名义项录入）。"""
    table = {
        "CW035": "定子电检标准", "CW050-2": "定子电检标准",
        "RT040-1": "动平衡标准",
        "MA080": "气密标准（壳体/冷却回路）",
        "MA090": "气密标准（壳体/冷却回路）",
        "EL010": "EOL 电性能标准",
    }
    return m["standards"].get(table.get(op_code))


def open_ipqc(c: C, m: dict, wo: dict, step: dict, qty: int, standard):
    r = c.post("/inspection-orders", {
        "order_type": "ipqc",
        "work_order_id": wo["id"],
        "process_id": step["operation_id"],
        "material_id": wo["product"]["id"],
        "standard_id": standard["id"] if standard else None,
        "lot_qty": qty,
        "remark": f"{step['op_code']} {step['op_name']} 过程检验",
    })
    if r.status_code != 200:
        bad(f"开 IPQC {step['op_code']}", f"{r.status_code} {msg(r)}")
        return None
    oid = payload(r)["id"]
    record_and_judge(c, m, oid, standard, qty)
    return oid


def record_and_judge(c: C, m: dict, oid: int, standard, qty: int, result="ACC"):
    items = [i for i in m["std_items"] if i["standard_id"] == standard["id"]] if standard else []
    if items:
        rec = []
        for it in items:
            if it.get("spec_lower_limit") is not None:
                rec.append({"item_id": it["id"],
                            "measured_value": round(
                                (it["spec_lower_limit"] + it["spec_upper_limit"]) / 2, 3),
                            "unit": it.get("unit")})
            else:
                rec.append({"item_id": it["id"], "result": "PASS"})
    else:
        rec = [{"item_name": "外观", "result": "PASS"},
               {"item_name": "功能", "result": "PASS"}]
    r = c.post(f"/inspection-orders/{oid}/results/batch", {"results": rec, "source": "web"})
    if r.status_code != 200:
        bad(f"检验录入 order={oid}", f"{r.status_code} {msg(r)}")
        return
    r = c.put(f"/inspection-orders/{oid}/judge", {"result": result})
    if r.status_code != 200:
        bad(f"检验判定 order={oid}", f"{r.status_code} {msg(r)}")


def produce(c: C, m: dict, st: dict, key: str, scrap_n: int = 0, scrap_op: str = ""):
    """逐工序报工（含检验工序），检验工序顺带开 IPQC。"""
    wo = st["wo"][key]
    steps = route_steps(c, wo["route_id"])
    qty = wo["planned"]
    left = qty
    done = st.setdefault("reported", {}).setdefault(key, [])
    for seg in steps:
        op = seg["op_code"]
        if op in done:
            continue
        scrap = scrap_n if op == scrap_op else 0
        out = left - scrap
        payload_ = {
            "work_order_id": wo["id"],
            "report_date": TODAY.isoformat(),
            "operation_code": op,
            "operation_name": seg["op_name"],
            "input_qty": left,
            "output_qty": out,
            "scrap_qty": scrap,
            "labor_hours": round((seg.get("unit_time") or 1) * left / 60, 2) or 0.1,
            "machine_hours": round((seg.get("unit_time") or 1) * left / 60, 2) or 0.1,
        }
        r = c.post("/work-reports", payload_)
        if r.status_code != 200:
            bad(f"报工 {wo['wo_no']} {op}", f"{r.status_code} {msg(r)}")
            return
        done.append(op)
        if scrap:
            left = out
        if seg.get("step_type") == "inspect":
            w = std_for_op(m, op, key)
            oid = open_ipqc(c, m, wo, seg, left, w)
            if oid:
                print(f"  [OK ] 过程检验 {op} {seg['op_name']}"
                      f"（{'标准 ' + w['name'] if w else '无标准·降级录入'}）")
    save_state(st)
    ok(f"逐工序报工 {wo['wo_no']}", f"{len(steps)} 道工序，末道 {steps[-1]['op_code']}")


def finish_and_store(c: C, m: dict, st: dict, key: str, loc_code: str):
    wo = st["wo"][key]
    r = c.post(f"/work-orders/{wo['id']}/complete")
    if r.status_code != 200:
        return bad(f"完工 {wo['wo_no']}", f"{r.status_code} {msg(r)}")
    d = payload(r) or {}
    pr = d.get("production_receipt") or {}
    ok(f"完工 {wo['wo_no']}", f"入库单 {pr.get('receipt_no')}"
       + (f"，警告 {d.get('warnings')}" if d.get("warnings") else ""))
    if not pr.get("receipt_id"):
        return bad(f"完工自动入库单 {wo['wo_no']}", str(pr))

    rid = pr["receipt_id"]
    ro = payload(c.get(f"/wms/receipt-orders/{rid}")) or {}
    items = ro.get("items") or []
    expected = next((i.get("expected_qty") for i in items), 0) or 0
    for it in items:
        if (it.get("received_qty") or 0) <= 0:
            r = c.post(f"/wms/receipt-order-items/{it['id']}/receive",
                       {"received_qty": expected})
            if r.status_code != 200:
                bad(f"生产入库收货 {rid}", f"{r.status_code} {msg(r)}")
        if (it.get("stored_qty") or 0) <= 0:
            r = c.post(f"/wms/receipt-order-items/{it['id']}/store",
                       {"stored_qty": expected,
                        "location_id": m["locs"][loc_code]["id"]})
            if r.status_code != 200:
                bad(f"生产入库上架 {rid}", f"{r.status_code} {msg(r)}")
    c.post(f"/wms/receipt-orders/{rid}/complete")
    ok(f"生产入库上架 {pr.get('receipt_no')}", f"{expected} → {loc_code}")
    st["wo"][key]["pr_receipt"] = pr
    save_state(st)


def phase_p4(c: C, m: dict, st: dict):
    print("\n═══ p4 定子·转子 报工 / 过程检验 / 完工 / 半成品入库 ═══")
    produce(c, m, st, "ST", scrap_n=ST_SCRAP, scrap_op=ST_SCRAP_OP)
    finish_and_store(c, m, st, "ST", "WH-AH-FG-FG-01")
    produce(c, m, st, "RT")
    finish_and_store(c, m, st, "RT", "WH-AH-FG-FG-02")


def phase_p6(c: C, m: dict, st: dict):
    print("\n═══ p6 整机 报工 / 过程+成品检验 / 完工 / 成品入库 ═══")
    produce(c, m, st, "UN")
    wo = st["wo"]["UN"]
    r = c.post("/inspection-orders", {
        "order_type": "fqc",
        "work_order_id": wo["id"],
        "material_id": wo["product"]["id"],
        "standard_id": m["standards"]["EOL 电性能标准"]["id"],
        "lot_qty": wo["planned"],
        "remark": "整机成品检验（EOL）",
    })
    if r.status_code == 200:
        oid = payload(r)["id"]
        record_and_judge(c, m, oid, m["standards"]["EOL 电性能标准"], wo["planned"])
        ok("成品检验 FQC", f"id={oid}，标准 EOL 电性能标准")
    else:
        bad("成品检验 FQC", f"{r.status_code} {msg(r)}")
    finish_and_store(c, m, st, "UN", "WH-AH-FG-FG-01")


# ══════════════════════ p7 报表 / 看板 / 追溯 ══════════════════════
def phase_p7(c: C, m: dict, st: dict):
    print("\n═══ p7 生产/品质/仓储报表 → 看板口径 → 批次追溯 ═══")

    r = c.get("/reports/daily", report_date=TODAY.isoformat())
    if r.status_code == 200:
        d = payload(r) or {}
        rows = d.get("rows") or []
        if rows:
            ok("生产日报", f"{d.get('total_output')} 件产出 / {d.get('total_scrap')} 报废 / "
                           f"{len(rows)} 行")
        else:
            bad("生产日报", "今日无报工行")
    else:
        bad("生产日报", f"{r.status_code} {msg(r)}")

    r = c.get("/reports/monthly", year=TODAY.year, month=TODAY.month)
    if r.status_code == 200:
        d = payload(r) or {}
        ok("生产月报", f"total_output={d.get('total_output')}")
    else:
        bad("生产月报", f"{r.status_code} {msg(r)}")

    for path, label in (("/wms/reports/stock-summary", "库存汇总"),
                        ("/wms/reports/summary", "仓储收发汇总"),
                        ("/wms/reports/turnover", "库存周转")):
        r = c.get(path)
        if r.status_code == 200:
            ok(f"仓储报表 {label}")
        else:
            bad(f"仓储报表 {label}", f"{r.status_code} {msg(r)}")

    r = c.post("/quality-reports/generate",
               {"report_type": "monthly", "period": f"{TODAY.year}-{TODAY.month:02d}"})
    if r.status_code == 200:
        ok("品质月报生成", f"id={payload(r)['id']}")
    else:
        bad("品质月报生成", f"{r.status_code} {msg(r)}")
    r = c.get("/quality-reports", page=1, page_size=5)
    if r.status_code == 200:
        d = payload(r) or {}
        ok("品质报表列表", f"total={d.get('total')}")

    # 批次正反追溯：成品批次 → 原料批次是否连得上
    batch = st.get("fg_batch")
    if batch:
        r = c.get(f"/trace/batch/{batch}")
        if r.status_code == 200:
            d = payload(r) or {}
            ok("批次追溯", f"{batch} 命中 {len(json.dumps(d))} 字节")
        else:
            bad("批次追溯", f"{r.status_code} {msg(r)}")

    # 一眼看总数的核对
    print("\n  ── 收口核对 ──")
    for label, path in (("工单", "/work-orders"), ("领料单", "/wms/issue-orders"),
                        ("入库单", "/wms/receipt-orders"), ("检验单", "/inspection-orders"),
                        ("报工行", "/work-reports")):
        r = c.get(path, page=1, page_size=1)
        if r.status_code == 200:
            d = payload(r) or {}
            print(f"     {label:<6} total={d.get('total')}")


# ══════════════════════ 入口 ══════════════════════
PHASES = {"p1": phase_p1, "p2": phase_p2, "p3": phase_p3,
          "p4": phase_p4, "p5": phase_p5, "p6": phase_p6, "p7": phase_p7}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--phase", action="append", default=[],
                    help="p1..p7，可多次；不填=按顺序全跑")
    ap.add_argument("--reset", action="store_true", help="清掉本地阶段状态（不删远端数据）")
    a = ap.parse_args()

    if a.reset and os.path.isfile(STATE_FILE):
        os.remove(STATE_FILE)
        print(f"已清除 {STATE_FILE}")

    st = load_state()
    c0 = httpx.Client(timeout=60)
    r = c0.post(f"{API}/auth/login",
                json={"username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c0.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                       "X-Tenant-Id": TENANT})
    c = C(c0)
    print(f"登录成功 tenant={TENANT} api={API} 业务日={TODAY}")

    m = load_master(c)
    print(f"主数据：产品 {len(m['products'])} / 物料 {len(m['mat'])} / "
          f"路线 {len(m['routes'])} / 检验标准 {len(m['standards'])}")
    st["_code_by_mat"] = {str(v["id"]): k for k, v in m["mat"].items()}
    save_state(st)

    for ph in (a.phase or list(PHASES)):
        fn = PHASES.get(ph)
        if not fn:
            print(f"[WARN] 未知阶段 {ph}")
            continue
        fn(c, m, st)
        save_state(st)

    print("\n" + "=" * 62)
    print(f"通道 {len(OKS)} · 断点 {len(FAILS)}")
    for f in FAILS:
        print(f"  ✗ {f}")
    return 1 if FAILS else 0


if __name__ == "__main__":
    raise SystemExit(main())
