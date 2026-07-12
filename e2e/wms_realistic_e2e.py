"""WMS 拟真用例 E2E —— 预发布回归验证（保留数据）"""
import asyncio, httpx, os, sys
from datetime import datetime

BASE = os.environ.get("BASE_URL", "http://localhost:8092")
USER = os.environ.get("USERNAME", "test_admin")
PASS = os.environ.get("PASSWORD", "test123456")
TENANT = os.environ.get("TENANT", "mfg_demo")

TS = datetime.now().strftime("%m%d%H%M")


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


async def main():
    client = httpx.AsyncClient(timeout=30)
    token = await login(client)
    client.headers["Authorization"] = f"Bearer {token}"
    client.headers["X-Tenant-Id"] = TENANT

    WID = 45
    MID = 115
    results = []

    def check(name, actual, expected):
        ok = actual == expected
        tag = "PASS" if ok else f"FAIL(got={actual})"
        results.append((tag, name))
        print(f"  [{tag}] {name}: actual={actual} expected={expected}")
        if not ok:
            raise SpecError(f"{name}: got {actual}, expected {expected}")

    print(f"== WMS 拟真用例 E2E (warehouse={WID} material={MID}) ==\n")

    # baseline
    base_stock = await get_inventory(client, MID)
    print(f"[BASELINE] stock={base_stock}\n")

    # ==== S1: Receipt + inspecting cancel (rollback) ====
    print("--- S1: 收货->inspecting->取消(回滚) ---")
    ro1_id, item1_id, _ = await create_receipt(client, f"PO-RCV-{TS}-001", WID, MID, 200)
    await client.post(
        f"{BASE}/api/v1/wms/receipt-order-items/{item1_id}/receive",
        json={"received_qty": 200},
    )
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
    await client.post(
        f"{BASE}/api/v1/wms/receipt-order-items/{item2_id}/receive",
        json={"received_qty": 150},
    )
    loc_r = await client.get(f"{BASE}/api/v1/wms/locations?page_size=10")
    locations = loc_r.json().get("data", {}).get("items", [])
    loc_id = locations[0]["id"] if locations else None
    await client.post(
        f"{BASE}/api/v1/wms/receipt-order-items/{item2_id}/store",
        json={"location_id": loc_id, "stored_qty": 150},
    )
    s2_stored = await get_inventory(client, MID)
    check("S2-stored+150", s2_stored - base_stock, 150.0)

    await client.post(
        f"{BASE}/api/v1/wms/receipt-orders/{ro2_id}/cancel",
        json={"reason": "采购订单取消-协议终止"},
    )
    check("S2-stored-rollback", await get_inventory(client, MID), base_stock)

    # ==== S3: Receipt + store + issue + cancel (issued rollback) ====
    print("\n--- S3: 收货->上架->出库->取消(issued回滚) ---")
    ro3_id, item3_id, _ = await create_receipt(client, f"PO-RCV-{TS}-003", WID, MID, 100)
    await client.post(
        f"{BASE}/api/v1/wms/receipt-order-items/{item3_id}/receive",
        json={"received_qty": 100},
    )
    await client.post(
        f"{BASE}/api/v1/wms/receipt-order-items/{item3_id}/store",
        json={"location_id": loc_id, "stored_qty": 100},
    )
    s3_pre = await get_inventory(client, MID)

    # create issue order
    ir = await client.post(
        f"{BASE}/api/v1/wms/issue-orders",
        json={
            "issue_no": f"ISO-{TS}-001",
            "issue_type": "production",
            "warehouse_id": WID,
            "order_id": 34,
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

    await client.post(
        f"{BASE}/api/v1/wms/issue-order-items/{io_item_id}/issue",
        json={"issued_qty": 50},
    )
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
    await client.post(
        f"{BASE}/api/v1/wms/receipt-orders/{ro4_id}/cancel",
        json={"reason": "单据建错-作废"},
    )
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
