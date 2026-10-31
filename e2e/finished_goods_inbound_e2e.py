"""X7 完工入库端到端**探测**脚本（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/finished_goods_inbound_e2e.py

覆盖 ``docs/scenario-inventory-2026-10-29.md`` §X 的 X7：

    工单完工 → 成品入库 → 库存可见 → 批次可追溯 → （发货出库）

关于 X7 的现状口径（先跑再下结论，别照抄清单）：

- 清单 P0-2 写"工单完工未联动成品入库"，**这一条已经修过**（``_raise_production_receipt``，
  单测 ``test_production_receipt_link.py``）。所以本脚本不预设"断在入库"，
  而是逐段自证到底哪一段真的不通。
- **发货出库确实没有**：后端没有销售/发运模块，``issue_orders.issue_type`` 只留了
  ``销售出库`` 这个枚举值，没有任何单据入口，也没有客户主数据（B-11 归 ERP）。
  这一段按**边界外**记录，不作为缺陷。
"""
import os
from datetime import date, datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
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
    print(f"\n{'=' * 62}\nX7 完工 → 成品入库 → 库存 → 批次追溯\n{'=' * 62}")

    # ══════════════ M0 造数 ══════════════
    print("\n── M0 造数 ──")
    raw_code = f"FG-RAW-{tag}"
    r = c.post(f"{API}/wms/materials", json={
        "code": raw_code, "name": "成品用原料", "unit": "个",
        "material_type": "raw", "pick_strategy": "fifo"})
    raw_id = new_id(r)
    if not raw_id:
        print(f"[FATAL] 建原料失败 {r.status_code} {detail_msg(r)}")
        return 1

    prod_code = f"PRO-FG-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"成品验证件{tag}", "unit": "件",
        "product_type": "finished", "spec": "E2E-FG"})
    product_id = new_id(r)
    if not product_id:
        print(f"[FATAL] 建产品失败 {r.status_code} {detail_msg(r)}")
        return 1

    r = c.post(f"{API}/boms", json={
        "product_id": product_id, "material_code": raw_code,
        "material_name": raw_code, "qty_per_unit": 1, "unit": "个",
        "material_type": "raw", "version": 1})
    if r.status_code != 200:
        print(f"[FATAL] 建 BOM 失败 {r.status_code} {detail_msg(r)}")
        return 1

    # 原料入库 100（够做 6 件）
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-FG-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": raw_id, "expected_qty": 100,
                   "unit": "个", "batch_no": f"B-{raw_code}-{tag}"}]})
    ro_id = new_id(r)
    items = (body(c.get(f"{API}/wms/receipt-orders/{ro_id}"))
             .get("data") or {}).get("items") or []
    if not items:
        print(f"[FATAL] 原料入库单无明细 ro_id={ro_id}")
        return 1
    r = c.post(f"{API}/wms/receipt-order-items/{items[0]['id']}/receive",
               json={"received_qty": 100, "batch_no": f"B-{raw_code}-{tag}"})
    report("M0 造数：原料 100 / 产品 / BOM 1 行 / 原料已入库",
           r.status_code == 200, f"原料={raw_code} 产品={prod_code}")

    # ══════════════ M1 工单下达 → 开工 → 报工 ══════════════
    print("\n── M1 工单下达 → 开工 → 报工 ──")
    wo_no = f"WO-FG-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": prod_code,
        "product_name": f"成品验证件{tag}", "planned_qty": 6,
        "wo_type": "production", "remark": "E2E 完工入库"})
    wo_id = new_id(r)
    if not wo_id:
        print(f"[FATAL] 建工单失败 {r.status_code} {detail_msg(r)}")
        return 1

    r = c.post(f"{API}/work-orders/{wo_id}/release", json={})
    report("M1-1 齐套通过可下达", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    r = c.post(f"{API}/work-orders/{wo_id}/start", json={})
    report("M1-2 开工", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    # 领料出库：**这一步不能省**。不领料，工单就没"消耗过原料"这个事实，
    # 后续批次追溯里 source_batches 为空是**正确的**——那种情况下测出的
    # "追溯断了"是造数缺陷，不是产品缺陷。
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": f"II-FG-{tag}", "issue_type": "production",
        "warehouse_id": 1, "work_order_id": wo_id,
        "items": [{"line_no": 1, "material_id": raw_id,
                   "required_qty": 6, "unit": "个"}]})
    issue_id = new_id(r)
    issue_ok = False
    if issue_id:
        ii = (body(c.get(f"{API}/wms/issue-orders/{issue_id}"))
              .get("data") or {}).get("items") or []
        if ii:
            r2 = c.post(f"{API}/wms/issue-order-items/{ii[0]['id']}/issue",
                        json={"issued_qty": 6, "batch_no": f"B-{raw_code}-{tag}"})
            issue_ok = r2.status_code == 200
            report("M1-2b 领料出库 6 个（追溯需要「消耗过原料」这个事实）", issue_ok,
                   f"HTTP {r2.status_code} {detail_msg(r2) if not issue_ok else ''}")
    if not issue_ok:
        gap("M1-2b 领料出库未成功，M5 的上游追溯将不可信")

    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": str(date.today()),
        "operation_name": "总装", "input_qty": 6, "output_qty": 6,
        "scrap_qty": 0, "labor_hours": 2})
    report("M1-3 报工 6 件", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    # ══════════════ M2 完工 → 自动生成成品入库单 ══════════════
    print("\n── M2 完工联动成品入库 ──")
    r = c.post(f"{API}/work-orders/{wo_id}/complete", json={})
    pr = (body(r).get("data") or {}).get("production_receipt") or {}
    report("M2-1 完工成功", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")
    report("M2-2 完工自动生成生产入库单", bool(pr.get("created")),
           f"pr={ {k: pr.get(k) for k in ('created', 'receipt_no', 'skipped', 'reason')} }")
    receipt_id = pr.get("receipt_id")
    if not receipt_id:
        gap("M2-3 无入库单，后续段无法验证", str(pr)[:160])
        return finish()
    report("M2-3 入库单号形如 PRD-日期-序号",
           pr.get("receipt_no", "").startswith("PRD-"), pr.get("receipt_no") or "")

    # ══════════════ M3 入库单内容 ══════════════
    print("\n── M3 入库单内容 ──")
    ro = (body(c.get(f"{API}/wms/receipt-orders/{receipt_id}")).get("data") or {})
    ritems = ro.get("items") or []
    report("M3-1 入库单挂回工单（可 JOIN 校验入库量≤完工量）",
           ro.get("work_order_id") == wo_id,
           f"work_order_id={ro.get('work_order_id')} 期望={wo_id}")
    report("M3-2 单头是待收货、来源=production",
           ro.get("status") == "pending" and ro.get("source_type") == "production",
           f"status={ro.get('status')} source={ro.get('source_type')}")
    it = ritems[0] if ritems else {}
    report("M3-3 明细物料=产品编码（成品档案已同步）",
           it.get("material_code") == prod_code,
           f"material_code={it.get('material_code')} 期望={prod_code}")
    report("M3-4 明细数量=完工数量 6", it.get("expected_qty") == 6,
           f"expected_qty={it.get('expected_qty')}")
    report("M3-5 成品批次号=工单号（客诉/召回有抓手）",
           it.get("batch_no") == wo_no, f"batch_no={it.get('batch_no')} 期望={wo_no}")

    # ══════════════ M4 收货 → 库存真的增加 ══════════════
    print("\n── M4 收货上架 ──")
    if not it:
        gap("M4 无明细，无法收货")
        return finish()
    r = c.post(f"{API}/wms/receipt-order-items/{it['id']}/receive",
               json={"received_qty": 6, "batch_no": wo_no})
    report("M4-1 成品收货登记", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")

    r = c.get(f"{API}/wms/inventory", params={"batch_no": wo_no, "page_size": 20})
    inv = (body(r).get("data") or {}).get("items") or (body(r).get("data") or {}).get("list") or []
    total = sum(float(x.get("quantity") or 0) for x in inv)
    report("M4-2 成品库存可见且数量=6", total >= 6,
           f"batch_no={wo_no} 库存行={len(inv)} 合计={total}")

    # ══════════════ M5 批次追溯 ══════════════
    print("\n── M5 批次追溯（成品批 ← 工单 ← 原料批） ──")
    r = c.get(f"{API}/trace/batch/{wo_no}", params={"direction": "both", "depth": 3})
    tr = body(r).get("data") or {}
    report("M5-1 成品批号可追溯", r.status_code == 200,
           f"HTTP {r.status_code} {detail_msg(r) if r.status_code != 200 else ''}")
    blob = str(tr)
    origins = tr.get("origin_work_orders") or []
    report("M5-2 成品批 → 工单 这条边在（不是只有批次档案）",
           bool(origins) and origins[0].get("work_order", {}).get("wo_no") == wo_no,
           f"origin_work_orders={len(origins)}")
    sources = tr.get("source_batches") or []
    report("M5-3 工单 → 原料批 这条边在（领过料才成立）",
           bool(sources) and (raw_code in blob or f"B-{raw_code}-{tag}" in blob),
           f"source_batches={len(sources)} 原料批 {'命中' if (raw_code in blob) else '未命中'}")
    stock = tr.get("stock") or {}
    report("M5-4 追溯页能带出在库数量", float(stock.get("on_hand") or 0) >= 6,
           f"on_hand={stock.get('on_hand')}")

    # ══════════════ M6 重复完工被状态机拦住 ══════════════
    print("\n── M6 幂等 / 状态机 ──")
    r = c.post(f"{API}/work-orders/{wo_id}/complete", json={})
    report("M6-1 重复完工被拒（不会攒第二张入库单）", r.status_code == 400,
           f"HTTP {r.status_code} {detail_msg(r)}")
    r = c.get(f"{API}/wms/receipt-orders", params={"page_size": 50,
                                                   "keyword": pr.get("receipt_no")})
    rows = (body(r).get("data") or {}).get("items") or []
    same = [x for x in rows if x.get("receipt_no") == pr.get("receipt_no")]
    report("M6-2 该工单只挂一张生产入库单", len(same) <= 1,
           f"同号单数={len(same)}")

    # ══════════════ M7 发货出库（边界确认，不是缺陷） ══════════════
    print("\n── M7 发货出库段（现状确认） ──")
    r = c.get(f"{API}/wms/issue-orders", params={"page_size": 5})
    report("M7-1 出库单接口存在", r.status_code == 200, f"HTTP {r.status_code}")
    # 没有任何销售/发运单据入口：查得到出库单，但建不了"发货"这个业务动作
    has_sales = False
    for path in ("/wms/shipments", "/wms/sales-orders", "/shipments", "/sales-orders"):
        rr = c.get(f"{API}{path}", params={"page_size": 1})
        if rr.status_code == 200:
            has_sales = True
            break
    if has_sales:
        ok("M7-2 存在销售/发运单据入口", "")
    else:
        gap("M7-2 无销售/发运单据入口（发货出库只能手工建出库单）",
            "issue_type 留了「销售出库」枚举，但没有销售单/客户主数据 —— 按边界外记，归 ERP")

    return finish()


def finish():
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
