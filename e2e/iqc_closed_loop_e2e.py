"""IQC 来料检验闭环端到端场景验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/iqc_closed_loop_e2e.py

覆盖场景（``docs/scenario-verification-2026-10-29.md`` §二 P0-1）：

    I1  建入库单（3 行：A 待检判合格 / B 待检判不合格 / C 不送检）
    I2  逐行收货登记 → 进入待检区
    I3  已送检未判定 → 上架被拒（★ 改造前的默认放行口子）
    I4  判定 ACC → 上架成功
    I5  判定 REJ → 上架被拒 + 自动开 NCR + 明细状态回写 disqualified
    I6  未送检的明细仍可上架（存量兼容路径）
    I7  重复送检幂等（不重复建单）
"""
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
WAREHOUSE_ID = int(os.environ.get("E2E_WH", "1"))
LOCATION_ID = int(os.environ.get("E2E_LOC", "1"))

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def err_code(r):
    if r.status_code < 400:
        return None
    d = r.json().get("detail")
    return d.get("code") if isinstance(d, dict) else None


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT} warehouse={WAREHOUSE_ID} location={LOCATION_ID}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    receipt_no = f"RC-IQC-{tag}"

    # ── I1 建入库单（3 行） ──
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": receipt_no, "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": WAREHOUSE_ID,
        "items": [
            {"line_no": 1, "material_id": 1, "expected_qty": 10, "unit": "根"},
            {"line_no": 2, "material_id": 2, "expected_qty": 20, "unit": "件"},
            {"line_no": 3, "material_id": 3, "expected_qty": 30, "unit": "件"},
        ]})
    check("I1 建入库单", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    if r.status_code != 200:
        return 1
    ro_id = r.json()["data"]["id"]

    det = c.get(f"{API}/wms/receipt-orders/{ro_id}").json()["data"]
    items = det.get("items") or []
    if len(items) < 3:
        print(f"[FATAL] 明细数量异常: {len(items)}")
        return 1
    items.sort(key=lambda x: x["line_no"])
    it_a, it_b, it_c = items[0], items[1], items[2]
    print(f"  入库单 {ro_id} 明细: {[i['id'] for i in items]}")

    # ── I2 收货登记 ──
    for it in (it_a, it_b, it_c):
        r = c.post(f"{API}/wms/receipt-order-items/{it['id']}/receive",
                   json={"received_qty": it["expected_qty"]})
        check(f"I2 收货登记 行{it['line_no']}", r.status_code == 200,
              f"HTTP {r.status_code} {r.text[:100]}")

    # ── I3 送检 A / B（C 不送检） ──
    insp = {}
    for key, it in (("A", it_a), ("B", it_b)):
        r = c.post(f"{API}/wms/receipt-order-items/{it['id']}/submit-inspection")
        d = r.json().get("data") if r.status_code == 200 else {}
        insp[key] = d
        check(f"I3 送检 {key}", r.status_code == 200 and bool(d.get("inspection_id")),
              f"HTTP {r.status_code} {r.text[:140]}")

    # ── I3b 已送检未判定 → 上架被拒（★ 核心闭环） ──
    r = c.post(f"{API}/wms/receipt-order-items/{it_a['id']}/store",
               json={"stored_qty": it_a["expected_qty"], "location_id": LOCATION_ID})
    check("I3b 已送检未判定 → 上架被拒 (WMS_409_INSPECTION)",
          r.status_code == 409 and err_code(r) == "WMS_409_INSPECTION",
          f"HTTP {r.status_code} code={err_code(r)}")

    # ── I4 判定 ACC → 上架成功 ──
    r = c.put(f"{API}/inspection-orders/{insp['A']['inspection_id']}/judge",
              json={"result": "ACC"})
    check("I4 判定 ACC", r.status_code == 200, f"HTTP {r.status_code} {r.text[:140]}")
    d = r.json().get("data") or {}
    check("I4 判定回写明细状态=qualified",
          d.get("receipt_inspection_status") == "qualified",
          str(d.get("receipt_inspection_status")))

    r = c.post(f"{API}/wms/receipt-order-items/{it_a['id']}/store",
               json={"stored_qty": it_a["expected_qty"], "location_id": LOCATION_ID})
    check("I4 判合格后上架成功", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:140]}")

    # ── I5 判定 REJ → 上架被拒 + NCR ──
    r = c.put(f"{API}/inspection-orders/{insp['B']['inspection_id']}/judge",
              json={"result": "REJ", "remark": "E2E 判定不合格"})
    d = r.json().get("data") if r.status_code == 200 else {}
    check("I5 判定 REJ", r.status_code == 200, f"HTTP {r.status_code} {r.text[:140]}")
    check("I5 判定回写明细状态=disqualified",
          d.get("receipt_inspection_status") == "disqualified",
          str(d.get("receipt_inspection_status")))
    check("I5 自动开 NCR", bool(d.get("ncr_id")), f"ncr_id={d.get('ncr_id')}")

    r = c.post(f"{API}/wms/receipt-order-items/{it_b['id']}/store",
               json={"stored_qty": it_b["expected_qty"], "location_id": LOCATION_ID})
    check("I5 判不合格后上架被拒", r.status_code == 409, f"HTTP {r.status_code}")
    check("I5 拒绝码为 WMS_409_INSPECTION", err_code(r) == "WMS_409_INSPECTION",
          str(err_code(r)))

    # ── I6 未送检明细仍可上架（存量兼容） ──
    r = c.post(f"{API}/wms/receipt-order-items/{it_c['id']}/store",
               json={"stored_qty": it_c["expected_qty"], "location_id": LOCATION_ID})
    check("I6 未送检明细仍可上架（兼容路径）", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:140]}")

    # ── I7 重复送检幂等 ──
    r = c.post(f"{API}/wms/receipt-order-items/{it_a['id']}/submit-inspection")
    d = r.json().get("data") if r.status_code == 200 else {}
    check("I7 重复送检返回既有检验单", d.get("created") is False
          and d.get("inspection_id") == insp["A"]["inspection_id"],
          f"created={d.get('created')} id={d.get('inspection_id')}")

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
