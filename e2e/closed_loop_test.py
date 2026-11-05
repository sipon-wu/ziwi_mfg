import os, json, datetime, uuid, traceback

# 用 httpx 而不是 requests：backend/.venv 里没有 requests（项目依赖的是 httpx），
# 之前这一行让探针直接 ModuleNotFoundError，全量回归里永远是一条 💥。
# 本脚本只用到 post / request / raise_for_status / json / status_code，
# httpx 的模块级 API 与之完全一致，改一行别名即可。
import httpx as requests

BASE = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1").rstrip("/")
TENANT = "AH-THR"
# 账号口令走环境变量：原写死的是演示租户 `test_admin`，2026-11-05
# 单租户收敛删掉演示租户后该账号不存在，登录直接 401。
USER = os.environ.get("E2E_USER", "mfg_admin")
PW = os.environ.get("E2E_PWD", "admin123")
TS = datetime.datetime.now().strftime("%Y%m%d%H%M%S")
RND = uuid.uuid4().hex[:6]
TAG = f"E2E_LOOP_{TS}_{RND}"

print(f"TAG={TAG}  BASE={BASE}")

# ---------- transport ----------
tok = None
def login():
    global tok
    r = requests.post(f"{BASE}/auth/login",
                      json={"username": USER, "password": PW, "tenant_id": TENANT}, timeout=20)
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

# ★仓库 id 一律**运行时从接口解析**，不写死。
# 原先写死 WH_RAW=41 / WH_FG=43：staging 上这两个 id 恰好存在，本地库没有 ——
# 而入库单照样 200（服务端不校验 warehouse_id 是否存在），于是库存挂到了
# "不存在的仓"上：`/wms/reports/stock-summary?warehouse_id=43` 因 JOIN 不到
# 仓库返回 0 条，探针把自己判红（INFO）。假红比真红更贵 —— 它会让人习惯性忽略红。
WH_RAW = None
WH_FG = None


def resolve_warehouses():
    """按编码解析（缺失则创建）原料仓 / 成品仓，返回 (raw_id, fg_id)。

    编码是业务主键、跨环境稳定；自增 id 不是。
    """
    wanted = {"WH-RAW": ("原料库", "raw_material"),
              "WH-FG": ("成品库", "finished_goods")}
    got = {}
    s, b = call("GET", "/wms/warehouses", params={"page": 1, "page_size": 100})
    for w in (items_of(b) if s == 200 else []):
        c = w.get("code")
        if c in wanted and c not in got:
            got[c] = w.get("id")
    for code, (name, typ) in wanted.items():
        if got.get(code):
            continue
        s, b = call("POST", "/wms/warehouses",
                    json={"code": code, "name": name, "type": typ})
        if s == 200 and first_id(b):
            got[code] = first_id(b)
        else:
            bug("BLOCKER", "setup", "POST /wms/warehouses", 200, s,
                f"{code} 解析/创建失败: {json.dumps(b, ensure_ascii=False)[:150]}")
    step(f"仓库解析 WH-RAW={got.get('WH-RAW')} WH-FG={got.get('WH-FG')}")
    return got.get("WH-RAW"), got.get("WH-FG")

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
    """按流水类型汇总数量（**带符号**原样求和）。

    ★出库流水 quantity 是负值（存量变动口径）：`issue` 行记 -30 而不是 30。
    服务端 `/wms/reports/turnover` 也是 `ABS(SUM(issue.quantity))` 这么用的，
    所以断言出库量要取绝对值，否则"出库 30"会被自己的探针判成 -30 的缺陷。
    """
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

_LOC_CACHE = {}


def loc_of(wh_id):
    """取该仓第一个库位（上架确认必须指定目标库位，否则 404 WMS_404_LOCATION）。"""
    if wh_id in _LOC_CACHE:
        return _LOC_CACHE[wh_id]
    _, b = call("GET", "/wms/locations", params={"warehouse_id": wh_id, "page_size": 5})
    items = items_of(b)
    lid = items[0]["id"] if items else None
    _LOC_CACHE[wh_id] = lid
    return lid


def receipt_stock(mat_id, wh_id, qty, unit, batch_no, rtype="purchase"):
    # ★单号不能拿 TAG 直接拼：TAG = E2E_LOOP_{14位时间戳}_{随机} 已经 30 字符，
    # 再拼 "_RCV_{物料}_{批次号}" 会超过 receipt_orders.receipt_no 的 varchar(64)。
    # SQLite 不校验长度，PG 直接 StringDataRightTruncationError -> 500，
    # 表现成"建收货单接口坏了"，实际是探针自己把单号写超了。
    no = f"RCV_{TS}_{mat_id}_{uuid.uuid4().hex[:6]}"
    # ★建单时**不要**预填 received_qty：收货是按「增量」过账的，
    #   预填后再调 /receive 传同样数量，delta = 0，服务端走"减量/持平仅更新数量"
    #   的幂等分支直接返回（posted_qty=0），单据状态停在 pending 不推进到
    #   inspecting —— 接着上架就必然 409「仅 inspecting/partially_stored 可上架」。
    #   现象是"收货 200 成功但上架 409"，很容易误判成上架接口坏了。
    s, b = call("POST", "/wms/receipt-orders", json={
        "receipt_no": no, "receipt_type": rtype, "warehouse_id": wh_id,
        "items": [{"line_no": 1, "material_id": mat_id, "expected_qty": qty,
                   "unit": unit, "batch_no": batch_no}]})
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
                  json={"location_id": loc_of(wh_id), "stored_qty": qty,
                        "batch_no": batch_no})
    if s3 != 200:
        bug("BLOCKER", "setup", "store", 200, s3, json.dumps(b3, ensure_ascii=False)[:200]); return None
    return ro_id

_WO_NO_CACHE = {}

def wo_no_of(product_code):
    """工单号不内嵌 product_code —— TAG 已 30 字符，拼进去就是 67 字符，
    超 issue_orders.source_doc_no 的 varchar(64)（领料单把它当来源单号回填），
    PG 上直接 StringDataRightTruncationError → 后端 500，
    现象是"建领料单接口坏了"，实际是探针把单号写超了。
    SQLite 不校验长度，所以只有 staging 才暴露。"""
    if product_code not in _WO_NO_CACHE:
        _WO_NO_CACHE[product_code] = len(_WO_NO_CACHE) + 1
    return f"WO_{TS}_{RND}_{_WO_NO_CACHE[product_code]}"


def batch_qty(mat_id):
    """按批次号取真实余量。
    ★不能读 /wms/batches 的 quantity —— batches 是**批次主数据**表，本身
    没有 quantity 列，该端点只返回批次档案（batch_no / 效期 / 锁定状态）；
    余量在 inventory 上按 (batch_no, 库位) 分行存放。
    用 batches.quantity 会恒得 0：既让"A 已出空"这种断言**假通过**，
    又让"B 剩 5"**假失败**，把正确的 FIFO 判成缺陷。
    """
    _, b = call("GET", "/wms/inventory",
                params={"material_id": mat_id, "page_size": 100})
    out = {}
    for it in items_of(b):
        no = it.get("batch_no")
        if no:
            out[no] = out.get(no, 0.0) + float(it.get("quantity") or 0)
    return out


def create_wo(product_code, product_name, qty):
    no = wo_no_of(product_code)
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
        "source_doc_no": wo_no_of(f"{TAG}_P1"),
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
    # 流水（出库记负值，取绝对值比较）
    ti = abs(txn_sum(raw, "issue"))
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
    # 查批次余量（走 inventory，见 batch_qty 注释）
    bmap = batch_qty(mf)
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
    bmap = batch_qty(ml)
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
            # ★judge 的返回体里**没有** result —— data 只有 ncr_id /
            #   receipt_inspection_status / batch_locked / batch_unlocked
            #   等副作用回执。判定结果本身要回读检验单，直接读 data.result
            #   恒为 None，会把正确的判定误判成"结果对不拢"。
            dd = b2.get("data") or {}
            _, b3 = call("GET", f"/inspection-orders/{qc_id}")
            res = (b3.get("data") or {}).get("result") if s2 == 200 else None
            step(f"S4 质检REJ status={s2} result={res} "
                 f"ncr_id={dd.get('ncr_id')} batch_locked={dd.get('batch_locked')}")
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
WH_RAW, WH_FG = resolve_warehouses()
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
    f.write(f"- TAG: `{TAG}`\n- 环境: {BASE}\n- 账号: {USER} / {TENANT}\n\n")
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
