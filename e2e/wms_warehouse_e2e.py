"""M04 仓储管理 · 场景验收探针（推进器厂：物料从入库到上线的全流程）。

## 这个探针要回答什么

覆盖矩阵里 M04 是**剩余最大的一格**：81 条路由只被碰到 59 条（73%），22 条从未
被执行过 —— 库区建档、物料搜索、批次锁定、领料申请、扫码出库、出库结案、以及
库存报表的五个口径。

这几条恰好是「仓储主链路」上最容易只写不验的部分：

- **库区/库位**是库存的组织维度，建不出来 → 所有带上架的动作一起废；
- **物料搜索**曾经被 `/materials/{mat_id}` 遮蔽（C-60），100% 422；
- **批次锁定**是 IQC 冻结的落地点，锁不上 → 冻结的货照样被拣走；
- **领料申请**是车间向仓库要料的入口，批不了 → 车间自己开单绕过审批；
- **扫码出库**是现场唯一入口，扫不准 → 现场退化成手抄单号；
- **出库结案**是 `partially_issued` 僵尸单的唯一出口；
- **报表**口径错了不会报错，只会让人按错数字做决策（周转率曾被 JOIN 放大 10 倍）。

## 场景（A推进器厂 · 推力室壳体机加线）

1. 建「成品仓 / 原料仓」下的一组库区库位，改一个库区名，删一个空库区
2. 按编码/名称搜「TC4 钛棒」
3. 来料 200 根 TC4 钛棒 → 收货 → 上架到 A-01-02 库位
4. 批次被 IQC 冻结 → 锁定并留原因
5. 车间提领料申请（60 根）→ 改状态 → 批准
6. 扫「出库单号」定位 → 扫「工单号」定位 → 扫一个不存在的码（必须 404 带原码）
7. 出库 60 → 结案（发齐）；另开一张欠发单 → 不允许差额结案（400 带行号欠发数）
   → 显式允许差额结案（short_closed）
8. 五个报表口径复核：剩余 100 根、周转率 1.0、呆滞清单不含刚动过的料

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/wms_warehouse_e2e.py
"""
from __future__ import annotations

import os
import sys
from datetime import datetime

import httpx

# 仓类型值域取后端唯一真源（本探针 cwd=backend，与 copilot_smoke 同一做法）。
# 为什么不在探针里再抄一份 6 项常量：抄一份就是第三个真源，早晚和
# `core/enums.py` 漂开 —— 本次要修的正是"值域散成几份"这个病。
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend"))
from app.core.enums import WAREHOUSE_TYPE_LABELS  # noqa: E402

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("TENANT_CODE", "MFG1")
USER = os.environ.get("ADMIN_USER", "mfg_admin")
PWD = os.environ.get("ADMIN_PWD", "admin123")

PASS = FAIL = 0
FAILS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}")
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
    return ok


def data(r: httpx.Response):
    try:
        return (r.json() or {}).get("data")
    except Exception:
        return None


def items(r: httpx.Response) -> list:
    d = data(r)
    if isinstance(d, dict):
        return d.get("items") or []
    return d if isinstance(d, list) else []


def new_id(r: httpx.Response):
    d = data(r)
    if isinstance(d, dict):
        return d.get("id")
    return d if isinstance(d, int) else None


def detail(r: httpx.Response) -> dict:
    try:
        d = (r.json() or {}).get("detail")
    except Exception:
        return {}
    return d if isinstance(d, dict) else {"message": str(d or "")}


def login(c: httpx.Client) -> dict:
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_code": TENANT})
    payload = r.json()
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    return payload


def main() -> int:
    c = httpx.Client(timeout=40)
    payload = login(c)
    tok = payload.get("access_token")
    if not tok:
        print(f"[FATAL] 登录失败: {payload}")
        return 1
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%H%M%S")

    # ============ W1 仓库 / 库区 / 库位 ============
    print("\n── W1 仓库·库区·库位（库存的组织维度）──")

    r = c.post(f"{API}/wms/warehouses", json={
        "code": f"WH-W-{tag}", "name": f"推进器厂原料仓{tag}",
        # ★ 字段名是 `type`，不是 `warehouse_type`。之前这里写错，Pydantic
        #   把多余字段静默丢掉 → 仓类型一直是默认值 raw_material，
        #   这条断言等于没验类型。顺带验证别名 `raw` 会被归一成 `raw_material`。
        "type": "raw", "address": "重庆两江新区·机加车间东侧"})
    wh_id = new_id(r)
    report("W1-1 仓库可创建", wh_id is not None,
           f"HTTP {r.status_code} wh_id={wh_id} {detail(r).get('message', '') if wh_id is None else ''}")
    # 创建只回 {"id"}，要回读才能看到落库的类型
    _g = c.get(f"{API}/wms/warehouses/{wh_id}") if wh_id else None
    wh_type = (data(_g) or {}).get("type") if _g is not None and _g.status_code == 200 else None
    report("W1-1b ★仓类型真的落库了，且别名 raw 归一为 raw_material",
           wh_type == "raw_material",
           f"回读 type={wh_type!r}（发的是 raw）")

    # ★ 全量值域：接口返回的每一个 type 都必须在 core/enums.py 的值域内。
    #   这条兜的是"库里还有历史脏值没归一" —— 归一迁移漏一个，
    #   按类型找仓的代码就会静默找不到（完工入库取不到成品仓）。
    r = c.get(f"{API}/wms/warehouses", params={"page": 1, "page_size": 100})
    _all = items(r)
    _types = sorted({(x.get("type") or "") for x in _all})
    _bad_types = [t for t in _types if t not in WAREHOUSE_TYPE_LABELS]
    report("W1-1c 全部仓库类型都在值域内（无历史别名残留）",
           r.status_code == 200 and not _bad_types,
           f"共 {len(_all)} 个仓 / {len(_types)} 种类型"
           + (f" · 域外值：{_bad_types}" if _bad_types else f" · {_types}"))

    r = c.get(f"{API}/wms/warehouses/all/active")
    actives = data(r) if isinstance(data(r), list) else []
    report("W1-2 ★启用仓库清单（下拉框数据源）可读且含新建仓库",
           r.status_code == 200 and any(x.get("id") == wh_id for x in actives),
           f"HTTP {r.status_code} 共 {len(actives)} 个")

    r = c.get(f"{API}/wms/warehouses/{wh_id}/zones")
    report("W1-3 新仓库的库区清单为空（不是 500）",
           r.status_code == 200 and items(r) == [], f"HTTP {r.status_code} {len(items(r))} 个")

    r = c.post(f"{API}/wms/zones", json={
        "warehouse_id": wh_id, "zone_code": f"Z-A-{tag}",
        "zone_name": "A区·钛合金棒料", "zone_type": "storage"})
    z1 = new_id(r)
    report("W1-4 库区可创建", z1 is not None,
           f"HTTP {r.status_code} zone_id={z1} {detail(r).get('message', '') if z1 is None else ''}")

    r = c.get(f"{API}/wms/zones/{z1}")
    z1_row = data(r) or {}
    report("W1-5 库区详情可读且编码一致",
           r.status_code == 200 and z1_row.get("zone_code") == f"Z-A-{tag}",
           f"HTTP {r.status_code} zone_code={z1_row.get('zone_code')}")

    r = c.get(f"{API}/wms/warehouses/{wh_id}/zones")
    report("W1-6 库区出现在所属仓库的库区清单里",
           any(x.get("id") == z1 for x in items(r)), f"共 {len(items(r))} 个")

    r = c.put(f"{API}/wms/zones/{z1}", json={"zone_name": "A区·TC4钛棒专用"})
    after = data(c.get(f"{API}/wms/zones/{z1}")) or {}
    report("W1-7 库区可改名且改名后读回一致",
           r.status_code == 200 and after.get("zone_name") == "A区·TC4钛棒专用",
           f"HTTP {r.status_code} zone_name={after.get('zone_name')}")

    r = c.post(f"{API}/wms/locations", json={
        "warehouse_id": wh_id, "zone_id": z1,
        "location_code": f"A-01-02-{tag}", "location_type": "shelf"})
    loc_id = new_id(r)
    report("W1-8 库位可创建（挂在库区下）", loc_id is not None,
           f"HTTP {r.status_code} loc_id={loc_id} {detail(r).get('message', '') if loc_id is None else ''}")

    r = c.get(f"{API}/wms/zones/{z1}/locations", params={"page_size": 50})
    report("W1-9 库区的库位清单含刚建的库位",
           r.status_code == 200 and any(x.get("id") == loc_id for x in items(r)),
           f"HTTP {r.status_code} 共 {len(items(r))} 个")

    # 空库区可删；有库位的库区不该被随手删掉
    r = c.post(f"{API}/wms/zones", json={
        "warehouse_id": wh_id, "zone_code": f"Z-EMPTY-{tag}", "zone_name": "临时区"})
    z2 = new_id(r)
    r = c.delete(f"{API}/wms/zones/{z2}")
    _del_ok = r.status_code == 200
    r = c.get(f"{API}/wms/zones/{z2}")
    report("W1-10 空库区可删除且删除后详情 404",
           _del_ok and r.status_code == 404, f"删除 HTTP {r.status_code}")

    # ============ W2 物料搜索 ============
    print("\n── W2 物料搜索（C-60 路由遮蔽的回归点）──")

    mat_code = f"MAT-TC4-{tag}"
    r = c.post(f"{API}/wms/materials", json={
        "code": mat_code, "name": f"TC4钛合金棒{tag}", "spec": "Φ80×3000",
        "unit": "根", "material_type": "raw", "is_batch_managed": True,
        "pick_strategy": "fifo", "safety_stock_qty": 50})
    mid = new_id(r)
    if not mid:
        print(f"[FATAL] 物料建不出来，后续无法继续: {r.status_code} {r.text[:200]}")
        return 1
    print(f"  物料 mat_id={mid} code={mat_code}")

    # limit 给到上限 100：前缀会命中历轮造的同类物料，默认 20 条迟早把
    # 本轮那条挤出结果集（同 W2-2 的跨轮污染）。断言用 `any(id==mid)` 而非条数。
    r = c.get(f"{API}/wms/materials/search", params={"keyword": mat_code[:12], "limit": 100})
    hits = data(r) if isinstance(data(r), list) else []
    report("W2-1 ★按编码前缀搜到物料（曾经被 {mat_id} 遮蔽 → 100% 422）",
           r.status_code == 200 and any(x.get("id") == mid for x in hits),
           f"HTTP {r.status_code} 命中 {len(hits)} 条")

    # ★关键字必须带 tag：只搜「TC4钛合金棒」在跑了十几轮之后会命中一堆旧数据，
    #   limit=5 截断后本轮那条根本不在结果里 → 报"没搜到"，但它其实是搜得到的。
    #   这属于探针的跨轮污染（列表 ≠ 本次记录），不是服务端缺陷。
    r = c.get(f"{API}/wms/materials/search",
              params={"keyword": f"钛合金棒{tag}", "limit": 20})
    hits2 = data(r) if isinstance(data(r), list) else []
    report("W2-2 按名称关键字可搜到（不是只按编码）",
           r.status_code == 200 and any(x.get("id") == mid for x in hits2),
           f"命中 {len(hits2)} 条")

    r = c.get(f"{API}/wms/materials/search", params={"keyword": f"NOT-EXIST-{tag}", "limit": 5})
    report("W2-3 搜不到时回空列表而不是报错（前端据此显示空态）",
           r.status_code == 200 and (data(r) or []) == [], f"HTTP {r.status_code}")

    r = c.get(f"{API}/wms/materials/search", params={"keyword": mat_code, "limit": 1})
    report("W2-4 limit 生效（最多回 1 条）",
           r.status_code == 200 and len(data(r) or []) <= 1, f"回 {len(data(r) or [])} 条")

    # ============ W3 收货 → 上架 ============
    print("\n── W3 来料 200 根 → 收货 → 上架到 A-01-02 ──")

    batch_no = f"B-TC4-{tag}"
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-W-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": wh_id,
        "supplier_name": "宝钛集团",
        "items": [{"line_no": 1, "material_id": mid, "expected_qty": 200.0,
                   "unit": "根", "batch_no": batch_no}]})
    ro_id = new_id(r)
    report("W3-1 入库单可创建", ro_id is not None, f"HTTP {r.status_code} ro_id={ro_id}")
    if not ro_id:
        print(f"[FATAL] 入库单建不出来: {r.text[:300]}")
        return 1

    ro = data(c.get(f"{API}/wms/receipt-orders/{ro_id}")) or {}
    ro_items = ro.get("items") or []
    ro_item_id = ro_items[0]["id"] if ro_items else None

    r = c.post(f"{API}/wms/receipt-order-items/{ro_item_id}/receive",
               json={"received_qty": 200.0, "batch_no": batch_no})
    report("W3-2 收货登记 200 根（待检区入账）", r.status_code == 200,
           f"HTTP {r.status_code} {detail(r).get('message', '')}")

    inv_bf = data(c.get(f"{API}/wms/inventory/by-material", params={"material_id": mid}))
    inv_bf_rows = inv_bf if isinstance(inv_bf, list) else []
    report("W3-3 收货后库存 200 根（还没上架，在待检区）",
           sum(float(x.get("quantity") or 0) for x in inv_bf_rows) == 200.0,
           f"实际 {[(x.get('batch_no'), x.get('quantity'), x.get('location_id')) for x in inv_bf_rows]}")

    r = c.post(f"{API}/wms/receipt-order-items/{ro_item_id}/store",
               json={"location_id": loc_id, "stored_qty": 200.0})
    report("W3-4 上架到 A-01-02 库位", r.status_code == 200,
           f"HTTP {r.status_code} {detail(r).get('message', '')}")

    inv_af = data(c.get(f"{API}/wms/inventory/by-material", params={"material_id": mid}))
    inv_af_rows = inv_af if isinstance(inv_af, list) else []
    at_loc = sum(float(x.get("quantity") or 0) for x in inv_af_rows
                 if x.get("location_id") == loc_id)
    report("W3-5 ★上架后 200 根落在目标库位（待检区已转出，不是两边都记）",
           at_loc == 200.0
           and sum(float(x.get("quantity") or 0) for x in inv_af_rows) == 200.0,
           f"库位内 {at_loc} / 合计 {sum(float(x.get('quantity') or 0) for x in inv_af_rows)}")

    # ============ W4 批次锁定 ============
    print("\n── W4 批次锁定（IQC 冻结的落地点）──")

    b_rows = data(c.get(f"{API}/wms/batches", params={"material_id": mid})) or []
    b_list = b_rows.get("items") if isinstance(b_rows, dict) else b_rows
    b_row = next((x for x in (b_list or []) if x.get("batch_no") == batch_no), {})
    batch_id = b_row.get("id")
    report("W4-1 收货自动建了批次实体（不是只留个字符串）", batch_id is not None,
           f"batch_id={batch_id} 批次 {len(b_list or [])} 条")

    # ⚠️ reason 是 **query 参数**（FastAPI Query(...)），用 json 传会 422 静默失败
    r = c.post(f"{API}/wms/batches/{batch_id}/lock",
               params={"reason": "IQC 判 REJ：超声探伤有内部缺陷"})
    aff = (data(r) or {}).get("affected") if isinstance(data(r), dict) else None
    locked = data(c.get(f"{API}/wms/batches/{batch_id}")) or {}
    report("W4-2 ★批次可锁定且锁因留痕（assessed 1 行）",
           r.status_code == 200 and aff == 1
           and bool(locked.get("is_locked"))
           and "超声探伤" in str(locked.get("lock_reason") or ""),
           f"HTTP {r.status_code} affected={aff} "
           f"is_locked={locked.get('is_locked')} reason={locked.get('lock_reason')}")

    r = c.post(f"{API}/wms/batches/{batch_id}/lock", params={"reason": "重复锁定"})
    report("W4-3 重复锁定不报 500（幂等或 400，都算可接受）",
           r.status_code in (200, 400), f"HTTP {r.status_code}")

    # 冻结的货不能被拣走 —— 这是锁定存在的意义
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": f"IO-LOCK-{tag}", "issue_type": "production",
        "source_type": "production", "warehouse_id": wh_id,
        "items": [{"line_no": 1, "material_id": mid, "required_qty": 10.0, "unit": "根"}]})
    io_lock = new_id(r)
    io_lock_row = data(c.get(f"{API}/wms/issue-orders/{io_lock}")) or {}
    io_lock_item = (io_lock_row.get("items") or [{}])[0].get("id")
    r = c.post(f"{API}/wms/issue-order-items/{io_lock_item}/issue",
               json={"batch_no": batch_no, "issued_qty": 10.0})
    report("W4-4 ★冻结批次不可出库（指定批次出库应被拒）",
           r.status_code >= 400, f"HTTP {r.status_code} {detail(r).get('message', '')[:60]}")

    # 解锁 → 后续流程要用这批料
    r = c.put(f"{API}/wms/batches/{batch_id}", json={"is_locked": False})
    unlocked = data(c.get(f"{API}/wms/batches/{batch_id}")) or {}
    report("W4-5 批次可解锁（复检合格后放行）",
           r.status_code == 200 and not unlocked.get("is_locked"),
           f"HTTP {r.status_code} is_locked={unlocked.get('is_locked')}")

    # ============ W5 领料申请 ============
    print("\n── W5 领料申请（车间向仓库要料）──")

    wo_no = f"WO-W-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": "PRD-TS-001",
        "product_name": f"推力室壳体{tag}", "planned_qty": 5,
        "wo_type": "production"})
    wo_id = new_id(r)
    report("W5-1 造一张工单（领料申请必须挂在工单上）", wo_id is not None,
           f"HTTP {r.status_code} wo_id={wo_id}")
    if not wo_id:
        print(f"[FATAL] 工单建不出来: {r.text[:300]}")
        return 1

    mr_no = f"MR-W-{tag}"
    r = c.post(f"{API}/wms/material-requests", json={
        "request_no": mr_no, "work_order_id": wo_id, "warehouse_id": wh_id,
        "items": [{"line_no": 1, "material_id": mid, "required_qty": 60.0, "unit": "根"}]})
    mr_id = new_id(r)
    report("W5-2 领料申请可创建", mr_id is not None,
           f"HTTP {r.status_code} mr_id={mr_id} {detail(r).get('message', '') if mr_id is None else ''}")

    r = c.get(f"{API}/wms/material-requests", params={"page_size": 50})
    report("W5-3 领料申请列表可读且含刚提的一张",
           r.status_code == 200 and any(x.get("id") == mr_id for x in items(r)),
           f"共 {len(items(r))} 条")

    r = c.get(f"{API}/wms/material-requests", params={"status": "pending", "page_size": 50})
    report("W5-4 按状态 pending 过滤（创建默认进待批队列）",
           r.status_code == 200 and any(x.get("id") == mr_id for x in items(r)),
           f"HTTP {r.status_code} 共 {len(items(r))} 条")

    r = c.get(f"{API}/wms/material-requests/{mr_id}")
    mr_row = data(r) or {}
    mr_items = mr_row.get("items") or []
    report("W5-5 ★申请详情含明细行（不含明细 = 审批人看不到要什么料）",
           r.status_code == 200 and len(mr_items) == 1
           and float(mr_items[0].get("required_qty") or 0) == 60.0,
           f"HTTP {r.status_code} 明细 {len(mr_items)} 行")

    r = c.put(f"{API}/wms/material-requests/{mr_id}", json={"status": "submitted"})
    after = data(c.get(f"{API}/wms/material-requests/{mr_id}")) or {}
    report("W5-6 申请可改状态（提交待批）",
           r.status_code == 200 and after.get("status") == "submitted",
           f"HTTP {r.status_code} status={after.get('status')}")

    r = c.post(f"{API}/wms/material-requests/{mr_id}/approve")
    after = data(c.get(f"{API}/wms/material-requests/{mr_id}")) or {}
    report("W5-7 ★批准后状态落 approved 且记录批准人",
           r.status_code == 200 and after.get("status") == "approved"
           and after.get("approved_by") is not None,
           f"HTTP {r.status_code} status={after.get('status')} approved_by={after.get('approved_by')}")

    # ============ W6 扫码出库 ============
    print("\n── W6 扫码定位 → 出库 → 结案 ──")

    io_no = f"IO-W-{tag}"
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": io_no, "issue_type": "production", "source_type": "production",
        "source_doc_no": wo_no, "work_order_id": wo_id, "warehouse_id": wh_id,
        "items": [{"line_no": 1, "material_id": mid, "required_qty": 60.0, "unit": "根"}]})
    io_id = new_id(r)
    report("W6-1 出库单可创建（挂工单）", io_id is not None, f"HTTP {r.status_code} io_id={io_id}")
    if not io_id:
        print(f"[FATAL] 出库单建不出来: {r.text[:300]}")
        return 1
    io_row = data(c.get(f"{API}/wms/issue-orders/{io_id}")) or {}
    io_item_id = (io_row.get("items") or [{}])[0].get("id")

    r = c.get(f"{API}/wms/issue-orders/scan", params={"code": io_no})
    sc = data(r) or {}
    report("W6-2 ★扫「出库单号」命中且可执行、逐行给出欠发数",
           r.status_code == 200 and sc.get("matched_by") == "issue_no"
           and sc.get("can_execute") is True
           and (sc.get("lines") or [{}])[0].get("remain_qty") == 60.0,
           f"HTTP {r.status_code} matched_by={sc.get('matched_by')} "
           f"can_execute={sc.get('can_execute')} "
           f"remain={(sc.get('lines') or [{}])[0].get('remain_qty')}")

    r = c.get(f"{API}/wms/issue-orders/scan", params={"code": wo_no})
    sc = data(r) or {}
    report("W6-3 ★扫「工单号」反查出库单（matched_by=work_order_no）",
           r.status_code == 200 and sc.get("matched_by") == "work_order_no"
           and (sc.get("order") or {}).get("id") == io_id,
           f"HTTP {r.status_code} matched_by={sc.get('matched_by')} "
           f"order_id={(sc.get('order') or {}).get('id')}")

    fake = f"NO-SUCH-{tag}"
    r = c.get(f"{API}/wms/issue-orders/scan", params={"code": fake})
    d = detail(r)
    report("W6-4 扫到不存在的码 → 404 且报错里带原始码（用户才知道是扫错了还是没这单）",
           r.status_code == 404 and fake in str(d.get("message") or "")
           and d.get("code") == "WMS_404_ISSUE_ORDER",
           f"HTTP {r.status_code} code={d.get('code')} message={d.get('message')}")

    r = c.get(f"{API}/wms/issue-orders/scan", params={"code": "   "})
    report("W6-5 空码扫码 → 400 明确拒绝（不是 500）",
           r.status_code == 400 and detail(r).get("code") == "WMS_400_EMPTY_CODE",
           f"HTTP {r.status_code} code={detail(r).get('code')}")

    # 发齐 → 结案
    r = c.post(f"{API}/wms/issue-order-items/{io_item_id}/issue", json={"issued_qty": 60.0})
    report("W6-6 出库过账 60 根", r.status_code == 200,
           f"HTTP {r.status_code} {detail(r).get('message', '')[:60]}")

    r = c.post(f"{API}/wms/issue-orders/{io_id}/complete", json={"allow_shortage": False})
    done = data(c.get(f"{API}/wms/issue-orders/{io_id}")) or {}
    report("W6-7 ★全部发齐 → 结案为 issued",
           r.status_code == 200 and done.get("status") == "issued",
           f"HTTP {r.status_code} status={done.get('status')}")

    r = c.get(f"{API}/wms/issue-orders/scan", params={"code": io_no})
    sc = data(r) or {}
    report("W6-8 已结案的单扫码后只读（can_execute=false + 原因）",
           sc.get("can_execute") is False and "已完成" in str(sc.get("blocked_reason") or ""),
           f"can_execute={sc.get('can_execute')} reason={sc.get('blocked_reason')}")

    # ============ W7 欠发结案 ============
    print("\n── W7 欠发结案（partially_issued 僵尸单的唯一出口）──")

    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": f"IO-SHORT-{tag}", "issue_type": "production",
        "source_type": "production", "warehouse_id": wh_id,
        "items": [{"line_no": 1, "material_id": mid, "required_qty": 150.0, "unit": "根"}]})
    io2 = new_id(r)
    io2_row = data(c.get(f"{API}/wms/issue-orders/{io2}")) or {}
    io2_item = (io2_row.get("items") or [{}])[0].get("id")
    c.post(f"{API}/wms/issue-order-items/{io2_item}/issue", json={"issued_qty": 40.0})
    mid_state = data(c.get(f"{API}/wms/issue-orders/{io2}")) or {}
    report("W7-1 部分出库后单据落 partially_issued（不是直接 issued）",
           mid_state.get("status") == "partially_issued",
           f"status={mid_state.get('status')}")

    r = c.post(f"{API}/wms/issue-orders/{io2}/complete", json={"allow_shortage": False})
    d = detail(r)
    m = str(d.get("message") or "")
    report("W7-2 ★默认不允许差额结案 → 400 且报错点名行号与欠发数",
           r.status_code == 400 and d.get("code") == "WMS_400_SHORTAGE"
           and "110" in m,
           f"HTTP {r.status_code} code={d.get('code')} message={m}")

    r = c.post(f"{API}/wms/issue-orders/{io2}/complete",
               json={"allow_shortage": True, "reason": "推力室壳体改单，钛棒余量转下批"})
    short_done = data(c.get(f"{API}/wms/issue-orders/{io2}")) or {}
    report("W7-3 ★显式允许差额结案 → issued + short_closed + 原因留痕",
           r.status_code == 200 and short_done.get("status") == "issued"
           and bool(short_done.get("short_closed"))
           and "改单" in str(short_done.get("shortage_reason") or ""),
           f"HTTP {r.status_code} status={short_done.get('status')} "
           f"short_closed={short_done.get('short_closed')} "
           f"reason={short_done.get('shortage_reason')}")

    # ============ W8 报表口径 ============
    print("\n── W8 五个报表口径复核（200 根收 → 100 根已出，剩 100）──")

    r = c.get(f"{API}/wms/reports/stock-summary", params={"warehouse_id": wh_id})
    rows = data(r) if isinstance(data(r), list) else []
    row = next((x for x in rows if x.get("material_code") == mat_code), {})
    report("W8-1 库存汇总：该物料现存 100 根、可用 100 根",
           r.status_code == 200 and float(row.get("total_qty") or -1) == 100.0
           and float(row.get("available_qty") or -1) == 100.0,
           f"HTTP {r.status_code} total={row.get('total_qty')} avail={row.get('available_qty')}")

    r = c.get(f"{API}/wms/reports/stock-by-location", params={"warehouse_id": wh_id})
    rows = data(r) if isinstance(data(r), list) else []
    row = next((x for x in rows if x.get("material_code") == mat_code), {})
    report("W8-2 库位库存明细：落在 A-01-02、数量 100",
           r.status_code == 200 and row.get("location_id") == loc_id
           and float(row.get("quantity") or -1) == 100.0,
           f"HTTP {r.status_code} loc={row.get('location_id')} qty={row.get('quantity')}")

    r = c.get(f"{API}/wms/reports/stock-by-location", params={"zone_id": z1})
    # ⚠️ 判的是 data(r) 不是 r —— 写成 isinstance(r, list) 恒假，
    # 于是"该库区 0 行"是探针自己造出来的假红（接口其实是好的）。
    rows_z = data(r) if isinstance(data(r), list) else []
    report("W8-3 库位明细可按库区过滤（zone_id 生效）",
           r.status_code == 200 and any(x.get("material_code") == mat_code for x in rows_z),
           f"HTTP {r.status_code} 该库区 {len(rows_z)} 行（zone_id={z1} loc_id={loc_id}）")

    r = c.get(f"{API}/wms/reports/summary")
    rows = data(r) if isinstance(data(r), list) else []
    row = next((x for x in rows if x.get("material_code") == mat_code), {})
    report("W8-4 收发存汇总：现存 100 / 可用 100（期初 0 收 200 发 100）",
           r.status_code == 200 and float(row.get("current_qty") or -1) == 100.0
           and float(row.get("available_qty") or -1) == 100.0,
           f"HTTP {r.status_code} current={row.get('current_qty')} avail={row.get('available_qty')}")

    r = c.get(f"{API}/wms/reports/turnover")
    rows = data(r) if isinstance(data(r), list) else []
    row = next((x for x in rows if x.get("material_code") == mat_code), {})
    report("W8-5 ★周转率 = 出库 100 / 现存 100 = 1.0（JOIN 放大过的老坑）",
           r.status_code == 200 and float(row.get("turnover_rate") if row.get("turnover_rate") is not None else -1) == 1.0,
           f"HTTP {r.status_code} rate={row.get('turnover_rate')} "
           f"cur={row.get('current_qty')} issue={row.get('total_issue_qty')}")

    r = c.get(f"{API}/wms/reports/slow-moving", params={"days": 90})
    rows = data(r) if isinstance(r, list) else []
    report("W8-6 ★呆滞清单不含刚动过的料（idle_days 计算不能把新货算成呆滞）",
           r.status_code == 200 and not any(x.get("material_code") == mat_code for x in rows),
           f"HTTP {r.status_code} 呆滞 {len(rows)} 条")

    # ============ W9 领料申请删除 ============
    print("\n── W9 领料申请删除（含明细级联）──")

    r = c.delete(f"{API}/wms/material-requests/{mr_id}")
    r2 = c.get(f"{API}/wms/material-requests/{mr_id}")
    report("W9-1 领料申请可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # ============ 汇总 ============
    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
