import requests, json, datetime, uuid, traceback

BASE = "https://mfg1.ziwi.cn/api/v1"
TENANT = "mfg_demo"
PW = "test123456"
TS = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
RND = uuid.uuid4().hex[:6]
TAG = f"E2E_LOOP_{TS}_{RND}"

print(f"TAG={TAG}  BASE={BASE}")

# ---------- transport ----------
tok = None
def login():
    global tok
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": "test_admin", "password": PW, "tenant_id": TENANT}, timeout=20)
    r.raise_for_status()
    tok = r.json()["access_token"]
login()

def call(method, path, json=None, params=None):
    r = requests.request(method, f"{BASE}{path}", json=json, params=params,
                         headers={"Authorization": f"Bearer {tok}"}, timeout=40)
    try:
        body = r.json()
    except Exception:
        body = r.text
    return r.status_code, body

def items_of(body):
    d = body.get("data") if isinstance(body, dict) else None
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("items", "list", "records"):
            if isinstance(d.get(k), list):
                return d[k]
    return []

def first_id(body):
    d = body.get("data") if isinstance(body, dict) else None
    if isinstance(d, dict):
        return d.get("id")
    return None

# ---------- bug collector ----------
BUGS = []
def bug(sev, scenario, endpoint, expected, actual, note=""):
    BUGS.append({"severity": sev, "scenario": scenario, "endpoint": endpoint,
                 "expected": str(expected), "actual": str(actual), "note": note})
    print(f"  [BUG:{sev}] {scenario} | {endpoint} | exp={expected} | act={actual} | {note}")

def step(msg):
    print(f"\n--- {msg} ---")

WH_RAW = 41
WH_FG = 43

# ---------- helpers ----------
def inv_qty(mat_id, wh_id=None):
    _, b = call("GET", "/wms/inventory/by-material", params={"material_id": mat_id})
    tot = 0.0
    recs = []
    for it in items_of(b):
        if wh_id and it.get("warehouse_id") != wh_id:
            continue
        q = float(it.get("quantity") or it.get("qty") or 0)
        tot += q
        recs.append(it)
    return tot, recs

def txn_sum(mat_id, ttype):
    _, b = call("GET", "/wms/inventory-transactions",
                params={"material_id": mat_id, "transaction_type": ttype})
    s = 0.0
    for t in items_of(b):
        s += float(t.get("quantity") or t.get("qty") or 0)
    return s

def create_material(code, name, unit, strategy, wh_default=None):
    body = {"code": code, "name": name, "unit": unit, "pick_strategy": strategy,
            "is_batch_managed": True, "material_type": "raw"}
    if wh_default:
        body["default_warehouse_id"] = wh_default
    s, b = call("POST", "/wms/materials", json=body)
    if s != 200:
        bug("MAJOR", "setup", "POST /wms/materials", 200, s, json.dumps(b, ensure_ascii=False)[:200])
        return None
    return first_id(b)

def receipt_stock(mat_id, wh_id, qty, unit, batch_no, rtype="purchase"):
    no = f"{TAG}_RCV_{mat_id}_{batch_no}"
    s, b = call("POST", "/wms/receipt-orders", json={
        "receipt_no": no, "receipt_type": rtype, "warehouse_id": wh_id,
        "items": [{"line_no": 1, "material_id": mat_id, "expected_qty": qty,
                   "received_qty": qty, "unit": unit, "batch_no": batch_no}]})
    if s != 200:
        bug("BLOCKER", "setup", "POST /wms/receipt-orders", 200, s, json.dumps(b, ensure_ascii=False)[:200])
        return None
    ro_id = first_id(b)
    ritem_id = None
    d = b.get("data", {})
    if isinstance(d, dict) and d.get("items"):
        ritem_id = d["items"][0]["id"]
    if ritem_id is None:
        _, b2 = call("GET", f"/wms/receipt-orders/{ro_id}")
        for it in items_of(b2):
            ritem_id = it["id"]; break
    # receive + store
    s2, b2 = call("POST", f"/wms/receipt-order-items/{ritem_id}/receive",
                  json={"received_qty": qty, "batch_no": batch_no})
    if s2 != 200:
        bug("BLOCKER", "setup", "receive", 200, s2, json.dumps(b2, ensure_ascii=False)[:200]); return None
    s3, b3 = call("POST", f"/wms/receipt-order-items/{ritem_id}/store",
                  json={"stored_qty": qty, "batch_no": batch_no})
    if s3 != 200:
        bug("BLOCKER", "setup", "store", 200, s3, json.dumps(b3, ensure_ascii=False)[:200]); return None
    return ro_id

def create_wo(product_code, product_name, qty):
    no = f"{TAG}_WO_{product_code}"
    s, b = call("POST", "/work-orders", json={
        "wo_no": no, "product_code": product_code, "product_name": product_name,
        "planned_qty": qty, "wo_type": "production"})
    if s != 200:
        bug("BLOCKER", "S1", "POST /work-orders", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return None
    # fetch id
    _, bl = call("GET", "/work-orders", params={"keyword": no})
    for it in items_of(bl):
        if it.get("wo_no") == no:
            return it["id"]
    bug("BLOCKER", "S1", "GET /work-orders keyword", "found", "not found"); return None

# ================= S1 核心闭环 =================
def scenario_s1():
    step("S1 核心闭环：工单→领料(自动FIFO)→报工→质检→成品入库")
    raw = create_material(f"{TAG}_RAW", "E2E原料", "KG", "fifo")
    fin = create_material(f"{TAG}_FIN", "E2E成品", "PCS", "fifo")
    if not raw or not fin:
        return
    # 初始入原料库 WH_RAW
    if receipt_stock(raw, WH_RAW, 100.0, "KG", f"{TAG}_B0", "purchase") is None:
        return
    q0, _ = inv_qty(raw, WH_RAW)
    step(f"S1 原料初始库存 q0={q0}")
    if abs(q0 - 100.0) > 0.01:
        bug("MAJOR", "S1", "inventory after receipt", 100.0, q0, "初始入库库存对不拢")
    # 工单
    wo = create_wo(f"{TAG}_P1", "E2E闭环成品", 20)
    if not wo:
        return
    # 下达(强制，避免BOM依赖)
    s, b = call("POST", f"/work-orders/{wo}/release", json={"force_release": True})
    if s != 200:
        bug("BLOCKER", "S1", "release(force)", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return
    # 领料出库
    s, b = call("POST", "/wms/issue-orders", json={
        "issue_no": f"{TAG}_ISS1", "issue_type": "production", "warehouse_id": WH_RAW,
        "source_doc_no": f"{TAG}_WO_{TAG}_P1",
        "items": [{"line_no": 1, "material_id": raw, "required_qty": 30.0, "unit": "KG"}]})
    if s != 200:
        bug("BLOCKER", "S1", "POST /wms/issue-orders", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return
    iitem_id = None
    d = b.get("data", {})
    if isinstance(d, dict) and d.get("items"):
        iitem_id = d["items"][0]["id"]
    if iitem_id is None:
        _, b2 = call("GET", f"/wms/issue-orders/{first_id(b)}")
        for it in items_of(b2):
            iitem_id = it["id"]; break
    # issue 不指定批次 -> 自动 FIFO
    s, b = call("POST", f"/wms/issue-order-items/{iitem_id}/issue", json={"issued_qty": 30.0})
    if s != 200:
        bug("BLOCKER", "S1", "issue(auto fifo)", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return
    q1, _ = inv_qty(raw, WH_RAW)
    step(f"S1 领料后原料库存 q1={q1}")
    if abs(q1 - (q0 - 30.0)) > 0.01:
        bug("MAJOR", "S1", "inventory after issue", q0 - 30.0, q1, "领料后库存对不拢(应扣30)")
    # 流水
    ti = txn_sum(raw, "issue")
    if abs(ti - 30.0) > 0.01:
        bug("MAJOR", "S1", "issue transaction sum", 30.0, ti, "出库流水数量对不拢")
    # 报工
    s, b = call("POST", "/work-reports", json={
        "work_order_id": wo, "report_date": "2026-07-12",
        "operation_name": "OP-0010", "input_qty": 30, "output_qty": 20, "scrap_qty": 0})
    if s != 200:
        bug("BLOCKER", "S1", "POST /work-reports", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return
    _, bw = call("GET", f"/work-orders/{wo}")
    comp = bw.get("data", {}).get("completed_qty")
    step(f"S1 工单 completed_qty={comp}")
    if comp != 20:
        bug("MAJOR", "S1", "work_order.completed_qty", 20, comp, "报工未正确回写工单")
    # 质检
    s, b = call("POST", "/inspection-orders", json={"order_type": "oqc", "work_order_id": wo})
    if s != 200:
        bug("BLOCKER", "S1", "POST /inspection-orders", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return
    qc_id = first_id(b)
    s, b = call("PUT", f"/inspection-orders/{qc_id}/judge", json={"result": "ACC"})
    if s != 200:
        bug("BLOCKER", "S1", "judge ACC", 200, s, json.dumps(b, ensure_ascii=False)[:200]); return
    # 成品入库
    if receipt_stock(fin, WH_FG, 20.0, "PCS", f"{TAG}_FB0", "生产入库") is None:
        return
    qf, _ = inv_qty(fin, WH_FG)
    step(f"S1 成品库存 qf={qf}")
    if abs(qf - 20.0) > 0.01:
        bug("MAJOR", "S1", "finished inventory after store", 20.0, qf, "成品入库库存对不拢")
    tr = txn_sum(fin, "receipt")
    if abs(tr - 20.0) > 0.01:
        bug("MAJOR", "S1", "receipt transaction sum", 20.0, tr, "入库流水数量对不拢")
    print("  S1 DONE OK")

# ================= S2 FIFO vs LIFO =================
def scenario_s2():
    step("S2 物料级 FIFO / LIFO 拣选策略")
    # FIFO 物料：两批 A(先) B(后)
    mf = create_material(f"{TAG}_FIFO", "E2E_FIFO料", "EA", "fifo")
    if mf is None: return
    receipt_stock(mf, WH_RAW, 10.0, "EA", f"{TAG}_FA", "purchase")
    receipt_stock(mf, WH_RAW, 10.0, "EA", f"{TAG}_FB", "purchase")
    # issue 15 不指定批次 -> 应 A 先出
    s, b = call("POST", "/wms/issue-orders", json={
        "issue_no": f"{TAG}_ISSF", "issue_type": "production", "warehouse_id": WH_RAW,
        "items": [{"line_no": 1, "material_id": mf, "required_qty": 15.0, "unit": "EA"}]})
    iid = None
    if s == 200:
        d = b.get("data", {})
        iid = d["items"][0]["id"] if isinstance(d, dict) and d.get("items") else None
        if iid is None:
            _, b2 = call("GET", f"/wms/issue-orders/{first_id(b)}")
            for it in items_of(b2): iid = it["id"]; break
        call("POST", f"/wms/issue-order-items/{iid}/issue", json={"issued_qty": 15.0})
    # 查批次余量
    _, bb = call("GET", "/wms/batches", params={"material_id": mf})
    bmap = {it.get("batch_no"): float(it.get("quantity") or 0) for it in items_of(bb)}
    qa = bmap.get(f"{TAG}_FA"); qb = bmap.get(f"{TAG}_FB")
    step(f"S2 FIFO 批次余量 A={qa} B={qb}")
    # 期望 A=0 B=5
    if qa is None or qa > 0.01:
        bug("MAJOR", "S2", "fifo pick A first", "A depleted(0)", qa, "FIFO未先出最早批次")
    if qb is None or abs(qb - 5.0) > 0.01:
        bug("MAJOR", "S2", "fifo pick B remains", 5.0, qb, "FIFO批次余量对不拢")

    # LIFO 物料：两批 C(先) D(后)
    ml = create_material(f"{TAG}_LIFO", "E2E_LIFO料", "EA", "lifo")
    if ml is None: return
    receipt_stock(ml, WH_RAW, 10.0, "EA", f"{TAG}_LC", "purchase")
    receipt_stock(ml, WH_RAW, 10.0, "EA", f"{TAG}_LD", "purchase")
    s, b = call("POST", "/wms/issue-orders", json={
        "issue_no": f"{TAG}_ISSL", "issue_type": "production", "warehouse_id": WH_RAW,
        "items": [{"line_no": 1, "material_id": ml, "required_qty": 15.0, "unit": "EA"}]})
    iid = None
    if s == 200:
        d = b.get("data", {})
        iid = d["items"][0]["id"] if isinstance(d, dict) and d.get("items") else None
        if iid is None:
            _, b2 = call("GET", f"/wms/issue-orders/{first_id(b)}")
            for it in items_of(b2): iid = it["id"]; break
        call("POST", f"/wms/issue-order-items/{iid}/issue", json={"issued_qty": 15.0})
    _, bb = call("GET", "/wms/batches", params={"material_id": ml})
    bmap = {it.get("batch_no"): float(it.get("quantity") or 0) for it in items_of(bb)}
    qc = bmap.get(f"{TAG}_LC"); qd = bmap.get(f"{TAG}_LD")
    step(f"S2 LIFO 批次余量 C={qc} D={qd}")
    if qd is None or qd > 0.01:
        bug("MAJOR", "S2", "lifo pick D first", "D depleted(0)", qd, "LIFO未先出最新批次")
    if qc is None or abs(qc - 5.0) > 0.01:
        bug("MAJOR", "S2", "lifo pick C remains", 5.0, qc, "LIFO批次余量对不拢")
    print("  S2 DONE")

# ================= S3 BOM 齐套性 =================
def scenario_s3():
    step("S3 BOM 齐套性：下达工单命中 BOM 齐套检查")
    # 用现有 PRO-001 (id=34) 有 BOM
    wo = create_wo("PRO-001", "精密轴承座", 10)
    if not wo: return
    s, b = call("POST", f"/work-orders/{wo}/release", json={"force_release": False})
    step(f"S3 release(non-force) status={s} body={json.dumps(b, ensure_ascii=False)[:400]}")
    if s == 200:
        mc = b.get("data", {}).get("material_check") or b.get("data", {}).get("material_check_status")
        snap = b.get("data", {}).get("bom_snapshot")
        if not snap:
            bug("MAJOR", "S3", "release material_check", "bom_snapshot present", "missing", "齐套检查未生成BOM快照")
        else:
            print(f"  S3 齐套结果={mc}, 快照行数={len(snap) if isinstance(snap,list) else '?'}")
    elif s in (400, 422):
        # 缺料需强制——合理，记录为 INFO/MAJOR视情况
        bug("INFO", "S3", "release(non-force)", "clear material-check result", s, "缺料需强制下达(行为合理)")
        # 强制下达验证可完成
        s2, b2 = call("POST", f"/work-orders/{wo}/release", json={"force_release": True})
        if s2 != 200:
            bug("BLOCKER", "S3", "release(force)", 200, s2, json.dumps(b2, ensure_ascii=False)[:200])
    else:
        bug("BLOCKER", "S3", "release(non-force)", "200 or 4xx", s, json.dumps(b, ensure_ascii=False)[:200])
    print("  S3 DONE")

# ================= S4 异常 + 看板 =================
def scenario_s4():
    step("S4 异常场景 + 异常看板端点")
    # 缺料领料：找一个库存为0的物料，issue 超出
    # 新建一个空物料
    mem = create_material(f"{TAG}_EMPTY", "E2E空料", "EA", "fifo")
    if mem is None: return
    s, b = call("POST", "/wms/issue-orders", json={
        "issue_no": f"{TAG}_ISSE", "issue_type": "production", "warehouse_id": WH_RAW,
        "items": [{"line_no": 1, "material_id": mem, "required_qty": 5.0, "unit": "EA"}]})
    if s == 200:
        d = b.get("data", {})
        iid = d["items"][0]["id"] if isinstance(d, dict) and d.get("items") else None
        if iid is None:
            _, b2 = call("GET", f"/wms/issue-orders/{first_id(b)}")
            for it in items_of(b2): iid = it["id"]; break
        s2, b2 = call("POST", f"/wms/issue-order-items/{iid}/issue", json={"issued_qty": 5.0})
        step(f"S4 缺料领料 issue status={s2} body={json.dumps(b2, ensure_ascii=False)[:300]}")
        if s2 >= 500:
            bug("BLOCKER", "S4", "issue over stock", "<500", s2, "缺料出库返回5xx(应优雅报错)")
        elif s2 == 200:
            bug("MAJOR", "S4", "issue over stock", "4xx refused", s2, "库存不足仍出库成功(数据对不拢)")
        else:
            print(f"  S4 缺料领料被正确拒绝({s2}) OK")
    # 质检 REJ
    wo = create_wo(f"{TAG}_P_REJ", "E2E_REJ成品", 1)
    if wo:
        s, b = call("POST", "/inspection-orders", json={"order_type": "oqc", "work_order_id": wo})
        if s == 200:
            qc_id = first_id(b)
            s2, b2 = call("PUT", f"/inspection-orders/{qc_id}/judge", json={"result": "REJ"})
            res = b2.get("data", {}).get("result") if s2 == 200 else None
            step(f"S4 质检REJ status={s2} result={res}")
            if s2 == 200 and res != "REJ":
                bug("MAJOR", "S4", "qc judge REJ", "REJ", res, "质检判定结果对不拢")
    # 看板端点
    for ep, params in [("/andon/calls", {"status": ""}),
                       ("/wms/inventory-alerts", None),
                       ("/wms/reports/stock-summary", {"warehouse_id": WH_FG})]:
        s, b = call("GET", ep, params=params)
        n = len(items_of(b)) if s == 200 else -1
        step(f"S4 看板 {ep} status={s} items={n}")
        if s != 200:
            bug("MAJOR", "S4", ep, 200, s, "异常看板端点不可用")
        elif n == 0:
            bug("INFO", "S4", ep, "has data", 0, "看板端点返回空(可能无数据)")
    print("  S4 DONE")

# ---------- run ----------
for fn in (scenario_s1, scenario_s2, scenario_s3, scenario_s4):
    try:
        fn()
    except Exception as e:
        bug("BLOCKER", fn.__name__, "exception", "no exception", f"{type(e).__name__}: {e}")
        traceback.print_exc()

# ---------- report ----------
print("\n\n========== BUGLIST ==========")
order = {"BLOCKER": 0, "MAJOR": 1, "MINOR": 2, "INFO": 3}
BUGS.sort(key=lambda x: order.get(x["severity"], 9))
if not BUGS:
    print("0 bugs — 全部闭环与数据联动通过")
else:
    for i, x in enumerate(BUGS, 1):
        print(f"{i}. [{x['severity']}] {x['scenario']} | {x['endpoint']}")
        print(f"     期望: {x['expected']}")
        print(f"     实际: {x['actual']}")
        print(f"     备注: {x['note']}")

# write report
import os
os.makedirs("deliverables", exist_ok=True)
rep = f"deliverables/mfg1-deep-closeloop-test-{TS}.md"
with open(rep, "w", encoding="utf-8") as f:
    f.write(f"# mfg1 深度业务闭环测试报告 ({TS})\n\n")
    f.write(f"- TAG: `{TAG}`\n- 环境: {BASE}\n- 账号: test_admin / {TENANT}\n\n")
    f.write(f"## 结果概览\n\n")
    f.write(f"- 场景数: 4 (S1核心闭环 / S2 FIFO·LIFO / S3 BOM齐套 / S4 异常+看板)\n")
    f.write(f"- BUG 总数: {len(BUGS)}\n")
    sev_count = {}
    for x in BUGS: sev_count[x['severity']] = sev_count.get(x['severity'], 0) + 1
    f.write(f"- 分级: " + ", ".join(f"{k}={v}" for k, v in sev_count.items()) + "\n\n")
    f.write(f"## BUGLIST\n\n")
    if not BUGS:
        f.write("无阻断性/数据对不拢问题，全部闭环通过。\n")
    else:
        for i, x in enumerate(BUGS, 1):
            f.write(f"### {i}. [{x['severity']}] {x['scenario']} / {x['endpoint']}\n")
            f.write(f"- 期望: {x['expected']}\n- 实际: {x['actual']}\n- 备注: {x['note']}\n\n")
print(f"\nREPORT -> {rep}")
