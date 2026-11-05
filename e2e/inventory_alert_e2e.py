"""X3 库存告急端到端**探测**脚本（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/inventory_alert_e2e.py

覆盖 ``docs/scenario-inventory-2026-10-29.md`` §X 的 X3：

    库存 < 安全线 → 预警 → 采购建议

现状标记是「⚠️ 仅预警」。本脚本逐段自证：预警这段到底通不通、
有没有副作用，以及"采购建议"这个载体到底存不存在。

断的地方打 ``[GAP]``，不判 FAIL（探测脚本退出码恒 0）。
"""
import os
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

OK, GAP, BOUNDARY = [], [], []


def ok(name, detail=""):
    OK.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def gap(name, detail=""):
    GAP.append(name)
    print(f"  [GAP] {name}" + (f" · {detail}" if detail else ""))


def boundary(name, detail=""):
    """边界外：按产品边界**不做**，不是缺陷（不计入断点）。"""
    BOUNDARY.append(name)
    print(f"  [OUT] {name}" + (f" · {detail}" if detail else ""))


def report(name, is_ok, detail=""):
    (ok if is_ok else gap)(name, detail)
    return is_ok


def body(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def detail_msg(r):
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or d.get("code") or str(d)[:160]
    if isinstance(d, str):
        return d[:160]
    return (r.text or "")[:160]


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print(f"\n{'=' * 62}\nX3 库存告急：安全线 → 预警 → 采购建议\n{'=' * 62}")

    # ══════════════ M0 造数：一个明显低于安全库存的物料 ══════════════
    print("\n── M0 造数 ──")
    code = f"AL-{tag}"
    r = c.post(f"{API}/wms/materials", json={
        "code": code, "name": f"告急物料{tag}", "unit": "个",
        "material_type": "raw", "pick_strategy": "fifo",
        "safety_stock_qty": 50, "min_stock_qty": 20, "reorder_point": 60})
    mat_id = (body(r).get("data") or {}).get("id") if r.status_code == 200 else None
    if not mat_id:
        print(f"[FATAL] 建物料失败 {r.status_code} {detail_msg(r)}")
        return 1
    # 只入 10 个（远低于安全库存 50）
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-AL-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": mat_id, "expected_qty": 10,
                   "unit": "个", "batch_no": f"B-{code}"}]})
    ro_id = (body(r).get("data") or {}).get("id")
    items = (body(c.get(f"{API}/wms/receipt-orders/{ro_id}"))
             .get("data") or {}).get("items") or []
    r = c.post(f"{API}/wms/receipt-order-items/{items[0]['id']}/receive",
               json={"received_qty": 10, "batch_no": f"B-{code}"})
    report("M0 造数：物料安全库存 50 / 只入 10",
           mat_id is not None and r.status_code == 200,
           f"mat_id={mat_id} 收货 HTTP {r.status_code}")

    def mine(alerts):
        return [a for a in (alerts or []) if a.get("material_id") == mat_id]

    # ══════════════ M1 扫描生成预警 ══════════════
    print("\n── M1 扫描生成预警 ──")
    r = c.post(f"{API}/wms/inventory-alerts/check")
    created1 = mine(body(r).get("data") or [])
    report("M1-1 扫描接口可调用", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")
    report("M1-2 低安全库存物料被识别", bool(created1), f"本物料生成 {len(created1)} 条")
    a1 = created1[0] if created1 else {}
    report("M1-3 预警带齐数量与阈值（不是一句空话）",
           a1.get("current_qty") == 10 and a1.get("threshold_qty") == 50,
           f"current={a1.get('current_qty')} threshold={a1.get('threshold_qty')}")
    report("M1-4 预警给出建议采购量（点得出下一步）",
           "建议采购" in (a1.get("alert_message") or ""),
           a1.get("alert_message") or "")

    # ══════════════ M2 幂等：重复扫描不该重复告警 ══════════════
    print("\n── M2 重复扫描（幂等） ──")
    r2 = c.post(f"{API}/wms/inventory-alerts/check")
    # 扫描仍会**列出**该物料（刷新后的告警），但带 deduplicated 标记 ——
    # 真正新建的是不带这个标记的那些。把两者混为一谈会误报"又生成了"。
    created2 = [a for a in mine(body(r2).get("data") or [])
                if not a.get("deduplicated")]
    report("M2-1 同一物料重复扫描不产生新告警", len(created2) == 0,
           f"第二次新建 {len(created2)} 条（告警列表会被刷屏）")

    r = c.get(f"{API}/wms/inventory-alerts", params={"status": "open", "page_size": 100})
    rows = (body(r).get("data") or {}).get("items") or []
    dup = [x for x in rows if x.get("material_id") == mat_id]
    report("M2-2 该物料未处理的预警只有 1 条", len(dup) <= 1,
           f"open 条数={len(dup)}")

    # ══════════════ M3 预警可闭环（确认 / 解决） ══════════════
    print("\n── M3 预警闭环 ──")
    alert_id = a1.get("id")
    if not alert_id:
        gap("M3 无预警 id，闭环段无法验证")
    else:
        r = c.post(f"{API}/wms/inventory-alerts/{alert_id}/acknowledge")
        report("M3-1 预警可确认", r.status_code == 200,
               f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")
        r = c.post(f"{API}/wms/inventory-alerts/{alert_id}/resolve")
        report("M3-2 预警可关闭", r.status_code == 200,
               f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")
        rows = (body(c.get(f"{API}/wms/inventory-alerts",
                           params={"status": "open", "page_size": 100}))
                .get("data") or {}).get("items") or []
        left = [x for x in rows if x.get("material_id") == mat_id]
        report("M3-3 关闭后不再出现在未处理列表", not left, f"残留={len(left)}")

    # ══════════════ M4 库存变化后是否自动复检 ══════════════
    print("\n── M4 触发时机 ──")
    # 补货到高于安全线（再收货 100）
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-AL2-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": mat_id, "expected_qty": 100,
                   "unit": "个", "batch_no": f"B2-{code}"}]})
    ro2 = (body(r).get("data") or {}).get("id")
    it2 = (body(c.get(f"{API}/wms/receipt-orders/{ro2}"))
           .get("data") or {}).get("items") or []
    r = c.post(f"{API}/wms/receipt-order-items/{it2[0]['id']}/receive",
               json={"received_qty": 100, "batch_no": f"B2-{code}"})
    report("M4-1 补货到 110（高于安全线 50）", r.status_code == 200,
           f"HTTP {r.status_code}")
    r = c.post(f"{API}/wms/inventory-alerts/check")
    still = mine(body(r).get("data") or [])
    report("M4-2 补货后不再被判为告急", not still,
           f"仍然告警 {len(still)} 条（阈值判断用的库存口径错了？）")

    # ══════════════ M5 采购建议（载体是否存在） ══════════════
    print("\n── M5 采购建议 ──")
    # 注意：/wms/material-requests 是**领料申请**（车间向仓库要料），不是采购申请，
    # 不能拿它冒充"采购建议"这一环。这里只找采购侧的载体。
    found = None
    for path in ("/wms/purchase-suggestions", "/wms/purchase-requests",
                 "/purchase-suggestions", "/purchase-requests",
                 "/wms/purchase-orders"):
        rr = c.get(f"{API}{path}", params={"page_size": 1})
        if rr.status_code == 200:
            found = path
            break
    if found:
        ok("M5-1 存在采购建议/申请载体", found)
    else:
        boundary("M5-1 无采购申请单据（预警能算出买多少，但点不出采购单）",
                 "供应商主数据与采购归 ERP（B-11），轻量 MES 边界外；"
                 "已退一步把建议采购量与建议到货日写进预警消息")

    print(f"\n{'=' * 62}")
    print(f"通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点：")
        for g in GAP:
            print(f"  - {g}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
