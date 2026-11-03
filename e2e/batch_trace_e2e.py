"""批次追溯闭环端到端**探测**脚本（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/batch_trace_e2e.py

探测而不是验收：通的打 ``[OK]``、断的打 ``[GAP]``，退出码恒 0。
目的是把 ``docs/scenario-inventory-2026-10-29.md`` 里 X6 的
``客诉 → NCR → 批次追溯 → 召回`` 前两环（追溯）落成可复现的事实。

链路（一条完整的数据血缘）::

    采购入库(原料批次) → 领料出库(挂工单) → 报工完工 → 生产入库(成品批次)
                                                        ↓
                                       成品批次向上追溯 → 工单 → 原料批次
                                       原料批次向下追溯 → 工单 → 成品批次

两个前置条件是最近才补齐的，缺任何一个追溯都不可能成立：

- 完工入库从来没写过成品批号（C-35）→ 客诉给了批号，库里查不到；
- 领料单没有 ``work_order_id``（C-35）→ 只能靠工单号字符串 JOIN。
"""
import os
import sys
from datetime import date, datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

RM_CODE = "E2E-TRACE-RM"
FG_CODE = "E2E-TRACE-FG"

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


def data_of(payload):
    return (payload or {}).get("data")


def items_of(payload):
    d = data_of(payload)
    if isinstance(d, dict):
        return d.get("items") or d.get("list") or []
    return d or []


def first_id(payload):
    d = data_of(payload)
    if isinstance(d, dict):
        return d.get("id")
    return d


def paged(c, path, params=None, page_size=100, max_pages=40):
    """把列表接口按页翻完再返回。

    ★本探针复用同一物料反复造批次，库存行会随每次运行线性增长
      （每条批次 × 库位一行，上架/出库还会留 0 行）。实测 material 35
      已 56 行、`page_size=50` 只回第一页 50 条，最新批号排在页外 ——
      T11「原料库存行带批号」于是恒为 0 命中，红得毫无道理。
      凡是"按批号在列表里找某一行"的断言，都必须翻全量，不能读一页。
    """
    out, page = [], 1
    while page <= max_pages:
        r = c.get(path, params={**(params or {}), "page": page,
                                "page_size": page_size})
        chunk = items_of(r.json()) if r.status_code == 200 else []
        out.extend(chunk)
        if len(chunk) < page_size:
            break
        page += 1
    return out


def ensure_material(c, code, name, mtype):
    r = c.get(f"{API}/wms/materials", params={"keyword": code, "page_size": 50})
    hit = next((m for m in items_of(r.json()) if m.get("code") == code), None)
    if hit:
        return hit["id"]
    r = c.post(f"{API}/wms/materials", json={
        "code": code, "name": name, "spec": "E2E",
        "unit": "PCS", "material_type": mtype,
        "pick_strategy": "fifo", "is_batch_managed": True})
    return first_id(r.json()) if r.status_code == 200 else None


def ensure_warehouse(c, wtype):
    r = c.get(f"{API}/wms/warehouses", params={"page_size": 100})
    hit = next((w for w in items_of(r.json()) if w.get("type") == wtype), None)
    return hit["id"] if hit else None


def first_location(c, wh_id):
    r = c.get(f"{API}/wms/warehouses/{wh_id}/locations", params={"page_size": 50})
    locs = items_of(r.json())
    if locs:
        return locs[0]["id"]
    r = c.get(f"{API}/wms/locations", params={"warehouse_id": wh_id, "page_size": 50})
    locs = items_of(r.json())
    return locs[0]["id"] if locs else None


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%m%d%H%M%S")
    batch_rm = f"E2E-RM-{tag}"
    print(f"\n{'=' * 64}\nX6 批次追溯：原料批 → 工单 → 成品批（双向）\n{'=' * 64}")

    # ── T1 主数据自举 ──
    rm_id = ensure_material(c, RM_CODE, "E2E 追溯原料", "raw")
    fg_id = ensure_material(c, FG_CODE, "E2E 追溯成品", "finished")
    wh_raw = ensure_warehouse(c, "raw_material")
    wh_fg = ensure_warehouse(c, "finished")
    report("T1 主数据自举（原料/成品/原料仓/成品仓）",
           bool(rm_id and fg_id and wh_raw and wh_fg),
           f"rm={rm_id} fg={fg_id} wh_raw={wh_raw} wh_fg={wh_fg}")
    if not (rm_id and fg_id and wh_raw and wh_fg):
        return 1

    loc_raw = first_location(c, wh_raw)
    loc_fg = first_location(c, wh_fg)
    report("T1b 库位可用", bool(loc_raw and loc_fg), f"raw={loc_raw} fg={loc_fg}")
    if not (loc_raw and loc_fg):
        return 1

    # ── T2 采购入库：原料带批次入账 ──
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RCV-TRACE-{tag}", "receipt_type": "purchase",
        "warehouse_id": wh_raw,
        "items": [{"line_no": 1, "material_id": rm_id, "expected_qty": 100,
                   "unit": "PCS", "batch_no": batch_rm}]})
    ro_id = first_id(r.json())
    report("T2 建采购入库单（带批次）", bool(ro_id),
           f"id={ro_id} HTTP {r.status_code} {r.text[:100]}")
    if not ro_id:
        return 1
    det = (c.get(f"{API}/wms/receipt-orders/{ro_id}").json().get("data") or {})
    its = det.get("items") or []
    if not its:
        gap("T2b 入库单明细存在", "收货单没有明细行，后续全部无法进行")
        return 1
    ri_id = its[0]["id"]
    for path, payload, label in (
        (f"/wms/receipt-order-items/{ri_id}/receive", {"received_qty": 100}, "收货"),
        (f"/wms/receipt-order-items/{ri_id}/store",
         {"location_id": loc_raw, "stored_qty": 100}, "上架"),
    ):
        rr = c.post(f"{API}{path}", json=payload)
        report(f"T2b 原料{label}", rr.status_code == 200,
               f"HTTP {rr.status_code} {rr.text[:100] if rr.status_code != 200 else ''}")

    # ── T3 工单 ──
    wo_no = f"WO-TRACE-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": FG_CODE, "product_name": "E2E 追溯成品",
        "planned_qty": 10, "wo_type": "production", "remark": "探测脚本：批次追溯"})
    wo_id = first_id(r.json()) if r.status_code == 200 else None
    report("T3 建工单", bool(wo_id), f"id={wo_id} HTTP {r.status_code}")
    if not wo_id:
        return 1
    r = c.post(f"{API}/work-orders/{wo_id}/release",
               json={"force_release": True, "force_reason": "E2E 追溯探测"})
    report("T3b 工单下达", r.status_code == 200, f"HTTP {r.status_code} {r.text[:100]}")

    # ── T4 领料出库：只传 source_doc_no，看后端能否自动挂上 work_order_id ──
    r = c.post(f"{API}/wms/issue-orders", json={
        "issue_no": f"ISO-TRACE-{tag}", "issue_type": "production",
        "source_type": "wo", "source_doc_no": wo_no,
        "warehouse_id": wh_raw,
        "items": [{"line_no": 1, "material_id": rm_id, "required_qty": 10,
                   "unit": "PCS", "batch_no": batch_rm}]})
    io_id = first_id(r.json())
    report("T4 建领料出库单（只传工单号）", bool(io_id),
           f"id={io_id} HTTP {r.status_code} {r.text[:100]}")
    if not io_id:
        return 1

    io = (c.get(f"{API}/wms/issue-orders/{io_id}").json().get("data") or {})
    report("T4b 领料单自动挂上 work_order_id", io.get("work_order_id") == wo_id,
           f"work_order_id={io.get('work_order_id')} 期望={wo_id}")

    io_items = io.get("items") or []
    if not io_items:
        gap("T4c 领料单明细存在", "没有明细行，无法出库")
        return 1
    r = c.post(f"{API}/wms/issue-order-items/{io_items[0]['id']}/issue",
               json={"issued_qty": 10, "batch_no": batch_rm})
    report("T4c 原料出库确认（指定批次）", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120]}")

    # ── T5 报工 + 完工 → 自动生成生产入库单 ──
    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": date.today().isoformat(),
        "output_qty": 10})
    report("T5 报工（自动开工）", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120]}")
    r = c.post(f"{API}/work-orders/{wo_id}/complete", json={})
    report("T5b 工单完工（in_progress→completed）", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:160]}")
    r = c.post(f"{API}/work-orders/{wo_id}/close")
    report("T5c 工单关闭（completed→closed）", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:160]}")

    # ── T6 完工入库单必须带成品批次号（= 工单号） ──
    r = c.get(f"{API}/wms/receipt-orders", params={"receipt_type": "production",
                                                   "page_size": 50})
    prd = next((x for x in items_of(r.json())
                if x.get("work_order_id") == wo_id), None)
    report("T6 完工自动生成生产入库单", bool(prd), f"receipt={prd}")
    if not prd:
        return 1
    prd_det = (c.get(f"{API}/wms/receipt-orders/{prd['id']}").json().get("data") or {})
    prd_items = prd_det.get("items") or []
    batch_fg = prd_items[0].get("batch_no") if prd_items else None
    report("T6b 生产入库明细带成品批次号", batch_fg == wo_no,
           f"batch_no={batch_fg} 期望={wo_no}")
    if not batch_fg:
        return 1

    # 成品收货 + 上架，让批次实体真正落库
    for ri in prd_items:
        c.post(f"{API}/wms/receipt-order-items/{ri['id']}/receive",
               json={"received_qty": 10})
        c.post(f"{API}/wms/receipt-order-items/{ri['id']}/store",
               json={"location_id": loc_fg, "stored_qty": 10})

    # ── T7 成品批次向上追溯：工单 + 原料批次 ──
    r = c.get(f"{API}/trace/batch/{batch_fg}", params={"direction": "up"})
    tr = (r.json().get("data") or {}) if r.status_code == 200 else {}
    report("T7 成品批次可追溯（接口 200）", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")
    wos = [x for x in (tr.get("origin_work_orders") or []) if x.get("work_order")]
    report("T7b 向上找到产出工单",
           any((w.get("work_order") or {}).get("id") == wo_id for w in wos),
           f"工单数={len(wos)} 期望含 {wo_no}")
    src = {b.get("batch_no") for b in (tr.get("source_batches") or [])}
    report("T7c 向上找到原料批次", batch_rm in src,
           f"上游批次={sorted(x for x in src if x)} 期望含 {batch_rm}")

    # ── T8 原料批次向下追溯：工单 + 成品批次 ──
    r = c.get(f"{API}/trace/batch/{batch_rm}", params={"direction": "down"})
    tr2 = (r.json().get("data") or {}) if r.status_code == 200 else {}
    awos = tr2.get("affected_work_orders") or []
    report("T8 原料批次向下找到受影响工单",
           any((w.get("work_order") or {}).get("id") == wo_id for w in awos),
           f"工单数={len(awos)} 期望含 {wo_no}")
    outs = {b.get("batch_no") for b in (tr2.get("output_batches") or [])}
    report("T8b 向下找到成品批次（召回对象）", batch_fg in outs,
           f"下游批次={sorted(x for x in outs if x)} 期望含 {batch_fg}")

    # ── T9 批次检索（客诉只给一个批号，得先搜得到） ──
    r = c.get(f"{API}/trace/batches", params={"keyword": batch_rm})
    hits = items_of(r.json()) if r.status_code == 200 else []
    report("T9 批次可按批号检索", any(h.get("batch_no") == batch_rm for h in hits),
           f"命中 {len(hits)} 条 HTTP {r.status_code}")

    # ── T10 未知批号不 404（历史数据兜底） ──
    r = c.get(f"{API}/trace/batch/NO-SUCH-BATCH-{tag}")
    body = r.json() if r.status_code == 200 else {}
    report("T10 未知批号返回 200 + warning（不 404）",
           r.status_code == 200 and bool((body.get("data") or {}).get("warning")),
           f"HTTP {r.status_code} warning={(body.get('data') or {}).get('warning')}")

    # ── T11 库存行带批次（批次能被冻结/召回的前提） ──
    rows = paged(c, f"{API}/wms/inventory", params={"material_id": rm_id})
    with_batch = [x for x in rows if x.get("batch_no") == batch_rm]
    report("T11 原料库存行带批号", bool(with_batch),
           f"带该批号的行数={len(with_batch)}（全量 {len(rows)} 行）")

    # ══════════════════════════════════════════════════════════
    # 第二段：客诉 → NCR → 召回（X6 的后两环）
    # ══════════════════════════════════════════════════════════
    print(f"\n{'-' * 64}\n客诉 → NCR → 召回\n{'-' * 64}")

    # ── T12 受理客诉：带批号必须当场跑出追溯快照 ──
    r = c.post(f"{API}/complaints", json={
        "customer_name": "E2E 客户", "customer_contact": "13800000000",
        "product_code": FG_CODE, "product_name": "E2E 追溯成品",
        "batch_no": batch_fg, "complaint_qty": 2,
        "complaint_type": "功能", "severity": "major",
        "source_channel": "phone",
        "description": "探测脚本：客户反馈该批出现异响"})
    comp = (r.json().get("data") or {}) if r.status_code == 200 else {}
    comp_id = comp.get("id")
    report("T12 受理客诉（带批号）", bool(comp_id),
           f"id={comp_id} HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")
    if not comp_id:
        return 1
    report("T12b 受理即生成追溯快照", bool(comp.get("trace_summary")),
           f"trace_summary={comp.get('trace_summary')}")
    comp_det = (c.get(f"{API}/complaints/{comp_id}").json().get("data") or {})
    snap = comp_det.get("trace_snapshot")
    report("T12c 快照落库且含下游批次",
           isinstance(snap, dict) and batch_fg in (snap.get("output_batches") or [])
           or isinstance(snap, dict) and snap.get("batch_no") == batch_fg,
           f"snapshot_keys={sorted(snap.keys()) if isinstance(snap, dict) else snap}")

    # ── T13 客诉开 NCR（幂等） ──
    r = c.post(f"{API}/complaints/{comp_id}/ncr", json={"defect_qty": 2})
    ncr = (r.json().get("data") or {}) if r.status_code == 200 else {}
    ncr_id = ncr.get("ncr_id")
    report("T13 客诉开 NCR", bool(ncr_id) and ncr.get("created") is True,
           f"ncr_id={ncr_id} created={ncr.get('created')} HTTP {r.status_code}")
    if ncr_id:
        d = (c.get(f"{API}/ncr/{ncr_id}").json().get("data") or {})
        report("T13b NCR 带上客诉批号与来源",
               d.get("batch_no") == batch_fg and d.get("source_type") == "customer",
               f"batch_no={d.get('batch_no')} source_type={d.get('source_type')}")
    r = c.post(f"{API}/complaints/{comp_id}/ncr", json={})
    ncr2 = (r.json().get("data") or {}) if r.status_code == 200 else {}
    report("T13c 重复开 NCR 不建第二张",
           ncr2.get("created") is False and ncr2.get("ncr_id") == ncr_id,
           f"第二次 created={ncr2.get('created')} ncr_id={ncr2.get('ncr_id')}")

    # ── T14 客诉实时追溯 ──
    r = c.get(f"{API}/complaints/{comp_id}/trace", params={"direction": "up"})
    tr3 = (r.json().get("data") or {}) if r.status_code == 200 else {}
    report("T14 客诉可实时追溯（不只看快照）",
           r.status_code == 200 and bool(tr3.get("source_batches")),
           f"HTTP {r.status_code} 上游批次={len(tr3.get('source_batches') or [])}")

    # ── T15 建召回：按追溯结果自动算范围并冻结批次 ──
    r = c.post(f"{API}/recalls", json={
        "complaint_id": comp_id, "reason": "探测脚本：客诉转召回"})
    rec = (r.json().get("data") or {}) if r.status_code == 200 else {}
    rec_id = rec.get("id")
    report("T15 建召回单（按追溯自动定范围）", bool(rec_id),
           f"id={rec_id} batch_count={rec.get('batch_count')} "
           f"locked={rec.get('locked_count')} HTTP {r.status_code} "
           f"{r.text[:120] if r.status_code != 200 else ''}")
    report("T15b 召回范围含该成品批次且成功冻结",
           (rec.get("locked_count") or 0) >= 1,
           f"batch_count={rec.get('batch_count')} locked_count={rec.get('locked_count')}")

    # ── T16 批次真的被冻结了（不是只写了个字段在召回单上） ──
    r = c.get(f"{API}/trace/batch/{batch_fg}")
    after = (r.json().get("data") or {}) if r.status_code == 200 else {}
    report("T16 召回后批次实体标记为已冻结", after.get("is_locked") is True,
           f"is_locked={after.get('is_locked')}")
    # 拣选排除锁定批次由单测锁住（test_wms_issue_pick::test_excludes_locked_batch）：
    # 靶场里可能还有其他未锁批次，用"自动拣选是否失败"判断会产生假阴性。
    r = c.get(f"{API}/trace/batches", params={"status": "locked", "keyword": batch_fg})
    locked_hits = items_of(r.json()) if r.status_code == 200 else []
    report("T16b 冻结批次出现在锁定清单",
           any(h.get("batch_no") == batch_fg for h in locked_hits),
           f"命中 {len(locked_hits)} 条")

    # ── T17 召回单详情：明细能查到"锁了哪几批、多少在库" ──
    r = c.get(f"{API}/recalls/{rec_id}")
    rec_det = (r.json().get("data") or {}) if r.status_code == 200 else {}
    its = rec_det.get("items") or []
    report("T17 召回单明细可查", bool(its),
           f"明细 {len(its)} 行 HTTP {r.status_code}")
    hit_item = next((x for x in its if x.get("batch_no") == batch_fg), None)
    report("T17b 明细记录在库数量与冻结状态",
           bool(hit_item) and hit_item.get("is_locked") is True,
           f"该批次明细={hit_item}")

    # ── T18 召回可闭环 ──
    r = c.post(f"{API}/recalls/{rec_id}/complete", json={"remark": "探测脚本：处理完毕"})
    report("T18 召回可完成关闭", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")

    # ── T19 客诉单上能反查到召回（闭环留痕） ──
    comp_after = (c.get(f"{API}/complaints/{comp_id}").json().get("data") or {})
    report("T19 客诉单回填 ncr_id 与 recall_id",
           comp_after.get("ncr_id") == ncr_id and comp_after.get("recall_id") == rec_id,
           f"ncr_id={comp_after.get('ncr_id')} recall_id={comp_after.get('recall_id')}")

    print(f"\n{'=' * 64}\n汇总：{len(OK)} 段通 / {len(GAP)} 段断\n{'=' * 64}")
    for name in GAP:
        print(f"  断点  {name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] 探测异常: {type(e).__name__}: {e}")
        sys.exit(2)
