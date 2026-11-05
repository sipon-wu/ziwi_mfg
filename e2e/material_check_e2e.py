"""M07 齐套性检查端到端**探测**脚本（真实 HTTP，场景 X4 / 清单 P1-4）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/material_check_e2e.py

覆盖两件事：

1. **取数对不对**（台账 C-44）：BOM 必须按产品隔离、库存必须读 WMS 台账；
2. **拦不拦得住**（场景清单 P1-4「缺料也能开工」）：缺料必须 400 拦回去，
   显式 ``force_release`` 才放行并留痕。

改造前的实测证据（同一台机器、同一条链路）::

    [实测] 目标产品 PRO-E2E-1031105802 真实BOM行数= 2
    建工单 id=112 → release 200 齐套状态=failed
      总物料= 23  齐套率= 0.0          ← 23 行里只有 2 行是这个产品的
      明细前5= ['M-001', 'M-002', 'M-001', 'M-002', 'M-001']

断的地方打 ``[GAP]``，不判 FAIL（探测脚本退出码恒 0）。
"""
import os
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

OK, GAP = [], []


def ok(name, detail=""):
    OK.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def gap(name, detail=""):
    GAP.append(name)
    print(f"  [GAP] {name}" + (f" · {detail}" if detail else ""))


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


def new_id(resp):
    d = body(resp).get("data")
    if isinstance(d, dict):
        return d.get("id")
    return d


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
    print(f"\n{'=' * 62}\nX4 齐套检查：取数是否正确 + 缺料是否真拦\n{'=' * 62}")

    # ══════════════ M0 造数（独立产品/物料/批次，不碰历史数据） ══════════════
    print("\n── M0 造数 ──")
    code_a, code_b = f"MC-A-{tag}", f"MC-B-{tag}"
    mats = {}
    for code, name in ((code_a, "齐套料A"), (code_b, "齐套料B")):
        r = c.post(f"{API}/wms/materials", json={
            "code": code, "name": name, "unit": "个", "material_type": "raw",
            "pick_strategy": "fifo"})
        mid = new_id(r)
        if not mid:
            print(f"[FATAL] 建物料失败 {code} {r.status_code} {detail_msg(r)}")
            return 1
        mats[code] = mid
    ok("M0-1 建 2 个专用物料", f"{code_a}={mats[code_a]} {code_b}={mats[code_b]}")

    prod_code = f"PRO-MC-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"齐套验证件{tag}", "unit": "件",
        "product_type": "finished", "spec": "E2E-MC"})
    product_id = new_id(r)
    if not product_id:
        print(f"[FATAL] 建产品失败 {r.status_code} {detail_msg(r)}")
        return 1
    ok("M0-2 建专用产品", f"{prod_code} id={product_id}")

    # A：单件用量 2；B：单件用量 1
    bom_plan = [(code_a, 2), (code_b, 1)]
    for code, qty in bom_plan:
        r = c.post(f"{API}/boms", json={
            "product_id": product_id, "material_code": code,
            "material_name": code, "qty_per_unit": qty, "unit": "个",
            "material_type": "raw", "version": 1})
        if r.status_code != 200:
            print(f"[FATAL] 建 BOM 行失败 {code} {r.status_code} {detail_msg(r)}")
            return 1
    ok("M0-3 建 BOM 2 行", f"@{code_a}x2 @{code_b}x1")

    # 收货入账：A=100（不够大工单）、B=1000（够）
    stock_plan = [(code_a, 100.0), (code_b, 1000.0)]
    for code, qty in stock_plan:
        r = c.post(f"{API}/wms/receipt-orders", json={
            "receipt_no": f"RC-MC-{code}-{tag}", "receipt_type": "purchase",
            "source_type": "purchase", "warehouse_id": 1,
            "items": [{"line_no": 1, "material_id": mats[code],
                       "expected_qty": qty, "unit": "个",
                       "batch_no": f"B-{code}-{tag}"}]})
        ro_id = new_id(r)
        if not ro_id:
            print(f"[FATAL] 建入库单失败 {code} {r.status_code} {detail_msg(r)}")
            return 1
        items = (body(c.get(f"{API}/wms/receipt-orders/{ro_id}"))
                 .get("data") or {}).get("items") or []
        if not items:
            print(f"[FATAL] 入库单无明细 ro_id={ro_id}")
            return 1
        r = c.post(f"{API}/wms/receipt-order-items/{items[0]['id']}/receive",
                   json={"received_qty": qty, "batch_no": f"B-{code}-{tag}"})
        if r.status_code != 200:
            print(f"[FATAL] 收货登记失败 {code} {r.status_code} {detail_msg(r)}")
            return 1
    ok("M0-4 收货入账", f"{code_a}=100 {code_b}=1000")

    # ══════════════ M1 取数正确性（BOM 按产品隔离 + 库存读台账） ══════════════
    print("\n── M1 取数正确性 ──")
    wo_no_small = f"WO-MC-S-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no_small, "product_code": prod_code,
        "product_name": f"齐套验证件{tag}", "planned_qty": 20,
        "wo_type": "production", "remark": "E2E 齐套-小单"})
    wo_small = new_id(r)
    if not wo_small:
        print(f"[FATAL] 建小工单失败 {r.status_code} {detail_msg(r)}")
        return 1

    r = c.post(f"{API}/work-orders/{wo_small}/material-check")
    check_small = (body(r).get("data") or {}).get("material_check_result") or {}
    report("M1-1 手动齐套检查可调用", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    codes = [d.get("material_code") for d in check_small.get("details") or []]
    report("M1-2 只算本产品的 BOM（不再全租户通吃）",
           sorted(codes) == sorted([code_a, code_b]) and len(codes) == 2,
           f"明细={codes} 期望={[code_a, code_b]}")

    avail = {d.get("material_code"): d.get("available_qty")
             for d in check_small.get("details") or []}
    report("M1-3 可用量来自 WMS 库存台账（不是 0 行的 inventory_items）",
           avail.get(code_a) == 100.0 and avail.get(code_b) == 1000.0,
           f"实测 {code_a}={avail.get(code_a)} {code_b}={avail.get(code_b)}")

    report("M1-4 20 件需求算对（A 40 / B 20）",
           check_small.get("check_status") == "passed"
           and check_small.get("kitting_rate") == 100.0,
           f"status={check_small.get('check_status')} "
           f"rate={check_small.get('kitting_rate')}")

    # ══════════════ M2 缺料识别 ══════════════
    print("\n── M2 缺料识别 ──")
    wo_no_big = f"WO-MC-B-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no_big, "product_code": prod_code,
        "product_name": f"齐套验证件{tag}", "planned_qty": 200,
        "wo_type": "production", "remark": "E2E 齐套-大单"})
    wo_big = new_id(r)
    if not wo_big:
        print(f"[FATAL] 建大工单失败 {r.status_code} {detail_msg(r)}")
        return 1

    r = c.post(f"{API}/work-orders/{wo_big}/material-check")
    check_big = (body(r).get("data") or {}).get("material_check_result") or {}
    # 200 件：A 需 400（有 100）缺 300；B 需 200（有 1000）齐
    detail_big = {d.get("material_code"): d for d in check_big.get("details") or []}
    report("M2-1 缺料被识别为 failed",
           check_big.get("check_status") == "failed",
           f"status={check_big.get('check_status')}")
    report("M2-2 缺料数量算对（A 缺 300）",
           (detail_big.get(code_a) or {}).get("short_qty") == 300.0,
           f"short={{{code_a}: {(detail_big.get(code_a) or {}).get('short_qty')}}}")
    report("M2-3 齐套率 1/2 = 50%",
           check_big.get("kitting_rate") == 50.0,
           f"rate={check_big.get('kitting_rate')}")

    # ══════════════ M3 缺料拦截（清单 P1-4） ══════════════
    print("\n── M3 缺料拦截 ──")
    r = c.post(f"{API}/work-orders/{wo_big}/release", json={})
    d = body(r).get("detail") or {}
    report("M3-1 缺料工单下达被拦（400）",
           r.status_code == 400 and d.get("code") == "400-0409",
           f"HTTP {r.status_code} code={d.get('code')} {detail_msg(r)}")
    report("M3-2 拦截响应带缺料明细（前端列得出缺什么）",
           bool((d.get("material_check") or {}).get("details")),
           f"short_materials={(d.get('material_check') or {}).get('short_materials')}")

    r = c.get(f"{API}/work-orders/{wo_big}")
    wo = body(r).get("data") or {}
    report("M3-3 被拦后工单仍是草稿（没有偷偷下达）",
           wo.get("wo_status") == "draft",
           f"wo_status={wo.get('wo_status')} 齐套={wo.get('material_check_status')}")

    # ══════════════ M4 强制下发留痕 ══════════════
    print("\n── M4 强制下发 ──")
    r = c.post(f"{API}/work-orders/{wo_big}/release",
               json={"force_release": True, "force_reason": "E2E 缺料拦截验证：先投产"})
    dc = body(r).get("data") or {}
    mc = dc.get("material_check") or {}
    report("M4-1 force_release 放行",
           r.status_code == 200, f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")
    report("M4-2 状态记成 force_passed（留痕）",
           mc.get("material_check_status") == "force_passed",
           f"status={mc.get('material_check_status')}")
    report("M4-3 工单确实变成已下达",
           (dc.get("status_change") or {}).get("to") == "released",
           f"transition={dc.get('status_change')}")

    r = c.get(f"{API}/work-orders/{wo_big}/material-check")
    back = body(r).get("data") or {}
    report("M4-4 齐套结论可回读",
           back.get("material_check_status") == "force_passed"
           and bool((back.get("material_check_result") or {}).get("details")),
           f"status={back.get('material_check_status')}")

    # ══════════════ M5 无 BOM 不许谎报齐套，也不许拦 ══════════════
    print("\n── M5 无 BOM 分支 ──")
    bare_code = f"PRO-MC-BARE-{tag}"
    r = c.post(f"{API}/products", json={
        "code": bare_code, "name": f"无BOM验证件{tag}", "unit": "件",
        "product_type": "finished", "spec": "E2E-MC"})
    bare_id = new_id(r)
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-MC-N-{tag}", "product_code": bare_code,
        "product_name": f"无BOM验证件{tag}", "planned_qty": 5,
        "wo_type": "production", "remark": "E2E 齐套-无BOM"})
    wo_bare = new_id(r)
    if not bare_id or not wo_bare:
        gap("M5-0 建无 BOM 产品/工单", f"bare_id={bare_id} wo_bare={wo_bare}")
    else:
        r = c.post(f"{API}/work-orders/{wo_bare}/material-check")
        ck = (body(r).get("data") or {}).get("material_check_result") or {}
        report("M5-1 无 BOM 返回 no_bom", ck.get("check_status") == "no_bom",
               f"status={ck.get('check_status')}")
        report("M5-2 无 BOM 时齐套率是 null 不是 100",
               ck.get("kitting_rate") is None,
               f"kitting_rate={ck.get('kitting_rate')}")
        r = c.post(f"{API}/work-orders/{wo_bare}/release", json={})
        report("M5-3 无 BOM 不拦下达（否则新租户一单都下不去）",
               r.status_code == 200, f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    # ══════════════ 汇总 ══════════════
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
