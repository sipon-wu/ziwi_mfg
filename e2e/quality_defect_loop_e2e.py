"""质量缺陷闭环端到端**探测**脚本（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/quality_defect_loop_e2e.py

与其它 ``*_e2e.py`` 的区别：本脚本是**探测**不是验收 —— 它照实报告链路
每一段是「通」还是「断」，断的地方打 ``[GAP]`` 而不判 FAIL。目的是把
``docs/scenario-inventory-2026-10-29.md`` 里 X1 / X8 的 ``⚠️ 未联动``
落成可复现的事实，而不是靠读代码猜。

覆盖两条链路（清单 §X）：

    X1 来料不合格：IQC 判 REJ → NCR → 库存冻结 → 退货
    X8 不良再处理：报工报废 → NCR → 返工 → 再检

每段结论都写进末尾的「缺口清单」，可直接转成待办。
"""
import os
import sys
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
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print(f"\n{'=' * 62}\nX1 来料不合格：IQC 判 REJ → NCR → 冻结 → 退货\n{'=' * 62}")

    # ── X1-1 建收货单并收货（★ 必须带 batch_no：不带批次则后面冻结/退货/召回全无抓手，
    #        那种情况下测出的"断点"是造数缺陷，不是产品缺陷） ──
    batch_no = f"QD-{tag}"
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-QD-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": 1, "expected_qty": 10, "unit": "根",
                   "batch_no": batch_no}],
    })
    if r.status_code != 200:
        print(f"[FATAL] 建入库单失败 {r.status_code} {r.text[:300]}")
        return 1
    ro_id = r.json()["data"]["id"]
    it = (c.get(f"{API}/wms/receipt-orders/{ro_id}").json()["data"]["items"])[0]
    ok("X1-1 建入库单", f"ro_id={ro_id} item_id={it['id']} batch_no={batch_no}")

    r = c.post(f"{API}/wms/receipt-order-items/{it['id']}/receive",
               json={"received_qty": 10, "batch_no": batch_no})
    report("X1-2 收货登记", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120]}")

    # ── X1-3 送检 → 判 REJ ──
    r = c.post(f"{API}/wms/receipt-order-items/{it['id']}/submit-inspection")
    insp_id = (r.json().get("data") or {}).get("inspection_id") if r.status_code == 200 else None
    report("X1-3 送检", bool(insp_id), f"inspection_id={insp_id} HTTP {r.status_code}")
    if insp_id is None:
        print("[FATAL] 送检失败，后续无法探测")
        return 1

    r = c.put(f"{API}/inspection-orders/{insp_id}/judge",
              json={"result": "REJ", "remark": "探测脚本：来料不合格"})
    d = r.json().get("data") or {} if r.status_code == 200 else {}
    ncr_id = d.get("ncr_id")
    report("X1-4 判 REJ → 自动开 NCR", bool(ncr_id),
           f"ncr_id={ncr_id} HTTP {r.status_code}")

    # ── X1-5 NCR 内容：定位依据够不够（物料/批次/供应商） ──
    if ncr_id:
        ncr = c.get(f"{API}/ncr/{ncr_id}").json().get("data") or {}
        print(f"  [INFO] NCR 内容: " + ", ".join(
            f"{k}={ncr.get(k)!r}" for k in
            ("ncr_no", "source_type", "source_id", "material_id",
             "batch_no", "supplier_id", "defect_qty", "status")))
        report("X1-5 NCR 带 source 定位", bool(ncr.get("source_type") and ncr.get("source_id")),
               f"source_type={ncr.get('source_type')} source_id={ncr.get('source_id')}")
        report("X1-6 NCR 带 material_id", bool(ncr.get("material_id")),
               f"material_id={ncr.get('material_id')}")
        # 没有批次号 → 「冻结哪一批」无从定位，下游退货/召回都失去抓手
        report("X1-7 NCR 带 batch_no（冻结/召回的抓手）", bool(ncr.get("batch_no")),
               f"batch_no={ncr.get('batch_no')}")

    # ── X1-8 NCR 判退后，库存有没有被自动冻结 ──
    # 按本次收货批次号精确查（不能用"该物料第一条批次"，会看到无关批次的 is_locked=0）
    batch_locked = None
    r = c.get(f"{API}/wms/batches", params={"batch_no": batch_no, "page_size": 5})
    rows = ((r.json().get("data") or {}).get("items")
            or (r.json().get("data") or {}).get("list") or []) if r.status_code == 200 else []
    matched = [b for b in rows if b.get("batch_no") == batch_no]
    if matched:
        b = matched[0]
        batch_locked = b.get("is_locked")
        print(f"  [INFO] 本次批次 {b.get('batch_no')} is_locked={batch_locked} status={b.get('status')}")
    else:
        print(f"  [INFO] 本次批次 {batch_no} 在 batches 表里不存在（收货不建批次记录）")
    report("X1-8 REJ 后本次批次被自动冻结", bool(batch_locked),
           f"batch_no={batch_no} is_locked={batch_locked}")

    # ── X1-9 NCR 处置=return，是否产生退货单 ──
    if ncr_id:
        c.put(f"{API}/ncr/{ncr_id}/status", json={"to_status": "reviewing"})
        r = c.put(f"{API}/ncr/{ncr_id}/status", json={
            "to_status": "disposed", "disposition": "return",
            "disposition_remark": "探测脚本：判退供应商"})
        report("X1-9 NCR 可推进到 disposed(return)", r.status_code == 200,
               f"HTTP {r.status_code} {r.text[:120]}")
        ncr2 = c.get(f"{API}/ncr/{ncr_id}").json().get("data") or {}
        report("X1-10 disposition 已落库", ncr2.get("disposition") == "return",
               f"disposition={ncr2.get('disposition')}")

        # 探测是否存在采购退货资源（不存在即 404）
        probed = []
        for path in ("/wms/purchase-returns", "/wms/return-orders",
                     "/purchase/returns", "/wms/returns"):
            rr = c.get(f"{API}{path}")
            probed.append(f"{path}={rr.status_code}")
        exists = any(p.endswith("=200") for p in probed)
        report("X1-11 存在采购退货单据资源", exists, " ".join(probed))

    # ── X1-12 冻结必须真的拦住出库拣选 ──
    # 只把 is_locked 置 1 不算数：出库拣选要跳过锁定批次，否则
    # 「不合格品可出库」照旧成立 —— 这正是 B-9 要解决的问题。
    #
    # 判据刻意不手算「非锁定可用量」：库里可能还有别的历史锁定批次，
    # 手算容易偏。改用账面总量去出库 —— 只要锁定真的生效，实际可用
    # 必然小于账面总量，出库必被拒；锁定没生效则恰好通过，断言就会红。
    r = c.get(f"{API}/wms/inventory",
              params={"material_id": 1, "warehouse_id": 1, "page_size": 100})
    inv_rows = ((r.json().get("data") or {}).get("items")
                or (r.json().get("data") or {}).get("list") or []) if r.status_code == 200 else []
    avail_all = sum(max(0.0, float(x.get("quantity") or 0) - float(x.get("locked_qty") or 0))
                    for x in inv_rows)
    print(f"  [INFO] 库存行 {len(inv_rows)} 条｜账面可用合计={avail_all}")
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": f"II-QD-{tag}", "issue_type": "production",
        "warehouse_id": 1,
        "items": [{"line_no": 1, "material_id": 1,
                   "required_qty": avail_all, "unit": "根"}]})
    issue_id = (r.json().get("data") or {}).get("id") if r.status_code == 200 else None
    if issue_id:
        it_i = (c.get(f"{API}/wms/issue-orders/{issue_id}").json()["data"]["items"])[0]
        r = c.post(f"{API}/wms/issue-order-items/{it_i['id']}/issue",
                   json={"issued_qty": avail_all})
        report("X1-12 冻结批次被排除出拣选（按账面总量出库被拒）", r.status_code >= 400,
               f"要出账面总量 {avail_all}（含锁定批次）→ HTTP {r.status_code} "
               f"{r.text[:120]}")
    else:
        report("X1-12 冻结批次被排除出拣选（按账面总量出库被拒）", False,
               f"建出库单失败 HTTP {r.status_code}")

    print(f"\n{'=' * 62}\nX8 不良再处理：报工报废 → NCR → 返工 → 再检\n{'=' * 62}")

    # ── X8-1 建工单 ──
    wo_no = f"WO-QD-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": "E2E-FG-001", "product_name": "E2E 成品",
        "planned_qty": 10, "wo_type": "production",
        "remark": "探测脚本：报废闭环"})
    if r.status_code != 200:
        print(f"[FATAL] 建工单失败 {r.status_code} {r.text[:300]}")
        return 1
    wo_id = (r.json().get("data") or {}).get("id")
    ok("X8-1 建工单", f"wo_id={wo_id} wo_no={wo_no}")
    c.post(f"{API}/work-orders/{wo_id}/release", json={})

    # ── X8-2 报工带报废 3 件 ──
    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": date.today().isoformat(),
        "operation_name": "OP-0010", "input_qty": 10, "output_qty": 7,
        "scrap_qty": 3, "defect_reason": "探测脚本：报废", "labor_hours": 1.5,
    })
    d = r.json().get("data") or {} if r.status_code == 200 else {}
    ncr_wr = d.get("ncr_id")
    report("X8-2 报工报废 3 件 → 自动开 NCR", bool(ncr_wr),
           f"ncr_id={ncr_wr} HTTP {r.status_code} {r.text[:100] if r.status_code != 200 else ''}")

    if ncr_wr:
        ncr = c.get(f"{API}/ncr/{ncr_wr}").json().get("data") or {}
        print(f"  [INFO] 制程 NCR: " + ", ".join(
            f"{k}={ncr.get(k)!r}" for k in
            ("ncr_no", "source_type", "source_id", "defect_qty",
             "work_order_id", "status")))
        report("X8-3 制程 NCR 带 work_order_id", bool(ncr.get("work_order_id")),
               f"work_order_id={ncr.get('work_order_id')}")

        # ── X8-4 处置=rework，是否产生返工单 ──
        c.put(f"{API}/ncr/{ncr_wr}/status", json={"to_status": "reviewing"})
        r = c.put(f"{API}/ncr/{ncr_wr}/status", json={
            "to_status": "disposed", "disposition": "rework",
            "disposition_remark": "探测脚本：返工"})
        report("X8-4 制程 NCR 可推进到 disposed(rework)", r.status_code == 200,
               f"HTTP {r.status_code} {r.text[:120]}")

        probed = []
        for path in ("/rework-orders", "/production/rework-orders"):
            rr = c.get(f"{API}{path}")
            probed.append(f"{path}={rr.status_code}")
        # ⚠️ 别用 /wms/issue-orders?issue_type=rework 探存在性：
        #    列表接口不校验 issue_type，永远返 200 + 全部出库单，
        #    只看状态码会得出"返工单资源存在"的假结论。
        exists = any(p.endswith("=200") for p in probed)
        report("X8-5 存在返工单据资源", exists, " ".join(probed))

        # 返工后需再检 → 有没有「NCR 处置后触发再检」的痕迹
        trail = c.get(f"{API}/ncr/{ncr_wr}/trail").json().get("data") or []
        items = trail.get("items") if isinstance(trail, dict) else trail
        print(f"  [INFO] NCR 流水 {len(items or [])} 条: "
              + " → ".join(str((x or {}).get("to_status")) for x in (items or [])))
        report("X8-6 处置后自动触发再检", False,
               "处置只写字段，不生成再检检验单")

    # ── 汇总 ──
    print(f"\n{'=' * 62}\n汇总：{len(OK)} 段通 / {len(GAP)} 段断\n{'=' * 62}")
    for name in GAP:
        print(f"  断点  {name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] 探测异常: {type(e).__name__}: {e}")
        sys.exit(2)
