"""WMS 拟真用例 E2E —— 预发布回归验证（保留数据）"""
import asyncio, httpx, os, sys
from datetime import datetime

# ★默认端口必须是 8000（本目录其余探针的约定）。原先写 8092 是某个早期
# 本地 alpha 实例的端口，那个实例早没了 —— 于是不传 BASE_URL 时这条探针
# 直接 ConnectError，在 run_all 里表现为"断 1 条"，看着像回归失败。
BASE = os.environ.get("BASE_URL", "http://127.0.0.1:8000")
# ★不要 fallback 到 os.environ["USERNAME"]：Windows 上 USERNAME 是系统环境变量
# （当前登录用户名，如 Kane.liu），永远有值 —— 拿它当 API 账号必然 401，
# 且报错只显示"用户名或密码错误"，看不出是拿错了变量。
USER = os.environ.get("E2E_USER", "mfg_admin")
PASS = os.environ.get("E2E_PWD", "admin123")
TENANT = os.environ.get("TENANT", "AH-THR")

# 精确到秒：单号形如 PO-RCV-<TS>-001，只到分钟时同一分钟内重跑会撞唯一约束
TS = datetime.now().strftime("%m%d%H%M%S")


class SpecError(Exception):
    pass


async def login(client):
    r = await client.post(
        f"{BASE}/api/v1/auth/login",
        json={"username": USER, "password": PASS},
    )
    if r.status_code != 200:
        raise SpecError(f"Login failed {r.status_code}: {r.text[:200]}")
    return r.json()["access_token"]


async def get_receipt_order(client, ro_id):
    r = await client.get(f"{BASE}/api/v1/wms/receipt-orders/{ro_id}")
    if r.status_code != 200:
        raise SpecError(f"Get receipt order failed {r.status_code}")
    return r.json()["data"]


async def get_issue_order(client, io_id):
    r = await client.get(f"{BASE}/api/v1/wms/issue-orders/{io_id}")
    if r.status_code != 200:
        raise SpecError(f"Get issue order failed {r.status_code}")
    return r.json()["data"]


async def get_inventory(client, material_id):
    r = await client.get(
        f"{BASE}/api/v1/wms/inventory?material_id={material_id}&page_size=100"
    )
    if r.status_code != 200:
        raise SpecError(f"Inventory query failed {r.status_code}")
    return sum(
        i["quantity"]
        for i in r.json().get("data", {}).get("items", [])
    )


async def act(client, url, body, label):
    """必须成功的状态流转：非 200 立刻带后端原话失败。

    原脚本对这些调用**不看状态码** —— 后端拒绝时（例如出库缺批次、库位不匹配）
    脚本会继续往下跑，最后卡在库存断言上，看起来像"库存算错了"，实际是
    上一个动作压根没生效。这类"静默失败"是最难查的一类。
    """
    r = await client.post(url, json=body)
    if r.status_code != 200:
        raise SpecError(f"{label} 失败 {r.status_code}: {r.text[:300]}")
    return r


async def create_receipt(client, receipt_no, warehouse_id, material_id, qty):
    r = await client.post(
        f"{BASE}/api/v1/wms/receipt-orders",
        json={
            "receipt_no": receipt_no,
            "receipt_type": "purchase",
            "warehouse_id": warehouse_id,
            "items": [
                {"line_no": 1, "material_id": material_id, "expected_qty": qty, "unit": "PCS"}
            ],
        },
    )
    if r.status_code != 200:
        raise SpecError(f"Create receipt failed {r.status_code}: {r.text[:200]}")
    ro_id = r.json()["data"]["id"]
    order = await get_receipt_order(client, ro_id)
    item_id = order["items"][0]["id"]
    return ro_id, item_id, order


# ── 靶场自举 ────────────────────────────────────────────────────────────
# 本脚本原先硬编码 staging 上的 WID=45 / MID=115 / order_id=34。指向其它库
# （尤其本地 SQLite —— 它默认不校验外键）跑时，单据照样能建成功，只是
# material_id / warehouse_id 全指向不存在的记录 —— 静默造孤儿单，然后卡在
# 库存断言上，"看起来是库存算错了"，实际是靶场根本不存在。
#
# 现在改为按**编码**自举：查不到就建，查得到就复用。同一套脚本既能跑本地
# 也能跑 staging / 生产预发，且重复跑不产生新的脏数据。
WH_CODE = "E2E-WH"
MAT_CODE = "E2E-MAT"


async def _first(client, url, params):
    r = await client.get(url, params=params)
    if r.status_code != 200:
        raise SpecError(f"GET {url} failed {r.status_code}: {r.text[:200]}")
    return (r.json().get("data") or {}).get("items") or []


async def ensure_warehouse(client, code, name):
    for w in await _first(client, f"{BASE}/api/v1/wms/warehouses",
                          {"keyword": code, "page_size": 100}):
        if w.get("code") == code:
            print(f"  [REUSE] 仓库 {code} id={w['id']}")
            return w["id"]
    r = await client.post(f"{BASE}/api/v1/wms/warehouses", json={
        "code": code, "name": name, "type": "raw_material",
    })
    if r.status_code != 200:
        raise SpecError(f"Create warehouse failed {r.status_code}: {r.text[:200]}")
    wid = r.json()["data"]["id"]
    print(f"  [CREATE] 仓库 {code} id={wid}")
    return wid


async def ensure_material(client, code, name, unit="PCS"):
    for m in await _first(client, f"{BASE}/api/v1/wms/materials",
                          {"keyword": code, "page_size": 100}):
        if m.get("code") == code:
            print(f"  [REUSE] 物料 {code} id={m['id']}")
            return m["id"]
    r = await client.post(f"{BASE}/api/v1/wms/materials", json={
        "code": code, "name": name, "unit": unit, "material_type": "raw",
    })
    if r.status_code != 200:
        raise SpecError(f"Create material failed {r.status_code}: {r.text[:200]}")
    mid = r.json()["data"]["id"]
    print(f"  [CREATE] 物料 {code} id={mid}")
    return mid


async def ensure_location(client, warehouse_id):
    """上架必须有库位；仓库是新建的就顺手建一个，已有就复用第一个。"""
    r = await client.get(f"{BASE}/api/v1/wms/warehouses/{warehouse_id}/locations",
                         params={"page_size": 100})
    if r.status_code == 200:
        payload = r.json().get("data")
        # 这个子资源直接返回数组，不是 {items: [...]}（与仓库/物料列表不同）
        items = payload if isinstance(payload, list) else (payload or {}).get("items") or []
        if items:
            print(f"  [REUSE] 库位 id={items[0]['id']}")
            return items[0]["id"]
    r = await client.post(f"{BASE}/api/v1/wms/locations", json={
        "warehouse_id": warehouse_id, "location_code": "E2E-L01", "location_type": "shelf",
    })
    if r.status_code != 200:
        raise SpecError(f"Create location failed {r.status_code}: {r.text[:200]}")
    lid = r.json()["data"]["id"]
    print(f"  [CREATE] 库位 E2E-L01 id={lid}")
    return lid


async def ensure_work_order(client, wo_no):
    """出库单的 order_id 必须指向真实工单，否则又是孤儿引用。"""
    rows = await _first(client, f"{BASE}/api/v1/work-orders",
                        {"keyword": wo_no, "page_size": 100})
    for w in rows:
        if w.get("wo_no") == wo_no:
            print(f"  [REUSE] 工单 {wo_no} id={w['id']}")
            return w["id"]
    r = await client.post(f"{BASE}/api/v1/work-orders", json={
        "wo_no": wo_no,
        "product_code": MAT_CODE,
        "product_name": "E2E 拟真用例成品",
        "planned_qty": 100,
        "wo_type": "production",
    })
    if r.status_code != 200:
        raise SpecError(f"Create work order failed {r.status_code}: {r.text[:200]}")
    oid = r.json()["data"]["id"]
    print(f"  [CREATE] 工单 {wo_no} id={oid}")
    return oid


async def main():
    client = httpx.AsyncClient(timeout=30)
    token = await login(client)
    client.headers["Authorization"] = f"Bearer {token}"
    client.headers["X-Tenant-Id"] = TENANT

    results = []

    def check(name, actual, expected):
        ok = actual == expected
        tag = "PASS" if ok else f"FAIL(got={actual})"
        results.append((tag, name))
        print(f"  [{tag}] {name}: actual={actual} expected={expected}")
        if not ok:
            raise SpecError(f"{name}: got {actual}, expected {expected}")

    # ── 靶场自举：不假设任何既有 id ──
    print("== 靶场自举 ==")
    WID = await ensure_warehouse(client, WH_CODE, "E2E 拟真仓")
    MID = await ensure_material(client, MAT_CODE, "E2E 拟真物料")
    loc_id = await ensure_location(client, WID)
    order_id = await ensure_work_order(client, f"WO-E2E-{TS}")
    print()

    print(f"== WMS 拟真用例 E2E (warehouse={WID} material={MID}) ==\n")

    # baseline
    base_stock = await get_inventory(client, MID)
    print(f"[BASELINE] stock={base_stock}\n")

    # ==== S1: Receipt + inspecting cancel (rollback) ====
    print("--- S1: 收货->inspecting->取消(回滚) ---")
    ro1_id, item1_id, _ = await create_receipt(client, f"PO-RCV-{TS}-001", WID, MID, 200)
    await act(client, f"{BASE}/api/v1/wms/receipt-order-items/{item1_id}/receive",
              {"received_qty": 200}, "S1 收货")
    s1_insp = await get_inventory(client, MID)
    check("S1-insp-stock+200", s1_insp - base_stock, 200.0)

    cr1 = await client.post(
        f"{BASE}/api/v1/wms/receipt-orders/{ro1_id}/cancel",
        json={"reason": "来料检验不合格-退供应商"},
    )
    if cr1.status_code != 200:
        raise SpecError(f"S1 cancel failed {cr1.status_code}: {cr1.text[:200]}")
    ro1_chk = await get_receipt_order(client, ro1_id)
    check("S1-status=cancelled", ro1_chk["status"], "cancelled")
    check("S1-stock-rollback", await get_inventory(client, MID), base_stock)

    cr1b = await client.post(
        f"{BASE}/api/v1/wms/receipt-orders/{ro1_id}/cancel",
        json={"reason": "重复"},
    )
    check("S1-dup-409", cr1b.status_code, 409)

    # ==== S2: Receipt + store + cancel (stored rollback) ====
    print("\n--- S2: 收货->上架->取消(stored回滚) ---")
    ro2_id, item2_id, _ = await create_receipt(client, f"PO-RCV-{TS}-002", WID, MID, 150)
    await act(client, f"{BASE}/api/v1/wms/receipt-order-items/{item2_id}/receive",
              {"received_qty": 150}, "S2 收货")
    # 库位在自举阶段已确保存在（loc_id），不再就地取"列表第一条"
    await act(client, f"{BASE}/api/v1/wms/receipt-order-items/{item2_id}/store",
              {"location_id": loc_id, "stored_qty": 150}, "S2 上架")
    s2_stored = await get_inventory(client, MID)
    check("S2-stored+150", s2_stored - base_stock, 150.0)

    await act(client, f"{BASE}/api/v1/wms/receipt-orders/{ro2_id}/cancel",
              {"reason": "采购订单取消-协议终止"}, "S2 取消")
    check("S2-stored-rollback", await get_inventory(client, MID), base_stock)

    # ==== S3: Receipt + store + issue + cancel (issued rollback) ====
    print("\n--- S3: 收货->上架->出库->取消(issued回滚) ---")
    ro3_id, item3_id, _ = await create_receipt(client, f"PO-RCV-{TS}-003", WID, MID, 100)
    await act(client, f"{BASE}/api/v1/wms/receipt-order-items/{item3_id}/receive",
              {"received_qty": 100}, "S3 收货")
    await act(client, f"{BASE}/api/v1/wms/receipt-order-items/{item3_id}/store",
              {"location_id": loc_id, "stored_qty": 100}, "S3 上架")
    s3_pre = await get_inventory(client, MID)

    # create issue order
    ir = await client.post(
        f"{BASE}/api/v1/wms/issue-orders",
        json={
            "issue_no": f"ISO-{TS}-001",
            "issue_type": "production",
            "warehouse_id": WID,
            "order_id": order_id,
            "items": [
                {"line_no": 1, "material_id": MID, "demanded_qty": 100, "unit": "PCS"}
            ],
        },
    )
    if ir.status_code != 200:
        raise SpecError(f"Create issue failed {ir.status_code}: {ir.text[:200]}")
    io_id = ir.json()["data"]["id"]
    io = await get_issue_order(client, io_id)
    io_item_id = io["items"][0]["id"]

    await act(client, f"{BASE}/api/v1/wms/issue-order-items/{io_item_id}/issue",
              {"issued_qty": 50}, "S3 出库")
    s3_post = await get_inventory(client, MID)
    check("S3-issued-50", s3_pre - s3_post, 50.0)

    ci = await client.post(
        f"{BASE}/api/v1/wms/issue-orders/{io_id}/cancel",
        json={"reason": "发料数量错误-退回库位"},
    )
    if ci.status_code != 200:
        raise SpecError(f"S3 cancel failed {ci.status_code}: {ci.text[:200]}")
    check("S3-issued-rollback", await get_inventory(client, MID), s3_pre)

    # ==== S4: pending cancel (zero impact) ====
    print("\n--- S4: pending取消(零影响) ---")
    ro4_id, _, _ = await create_receipt(client, f"PO-RCV-{TS}-004", WID, MID, 50)
    s4_before = await get_inventory(client, MID)
    await act(client, f"{BASE}/api/v1/wms/receipt-orders/{ro4_id}/cancel",
              {"reason": "单据建错-作废"}, "S4 取消")
    check("S4-pending-zero", await get_inventory(client, MID), s4_before)

    # ==== S5: audit trail ====
    print("\n--- S5: 审计留痕 ---")
    tx_r = await client.get(
        f"{BASE}/api/v1/wms/inventory-transactions?material_id={MID}"
        f"&transaction_type=cancel&page_size=100"
    )
    cancel_txs = (
        tx_r.json().get("data", {}).get("items", [])
        if tx_r.status_code == 200
        else []
    )
    print(f"  [INFO] cancel 流水数: {len(cancel_txs)}")
    for tx in cancel_txs:
        print(f"    tx#{tx.get('id','?')}: qty={tx.get('quantity')} remark={tx.get('remark','')[:60]}")
    check("S5-audit-cancel-tx>=3", len(cancel_txs) >= 3, True)
    remarks = [tx.get("remark", "") for tx in cancel_txs]
    has_reason = any(
        "不合格" in r or "取消" in r or "错误" in r or "作废" in r
        for r in remarks
    )
    check("S5-audit-reason-preserved", has_reason, True)

    # summary
    passed = sum(1 for t, _ in results if t == "PASS")
    failed = sum(1 for t, _ in results if t != "PASS")
    print(f"\n{'='*50}")
    print(f"== 拟真用例: {passed} PASS / {failed} FAIL ==")
    print(f"== 测试数据已保留 (PO-RCV-{TS}-*) ==")
    print(f"{'='*50}")

    await client.aclose()
    sys.exit(0 if failed == 0 else 1)


if __name__ == "__main__":
    asyncio.run(main())
