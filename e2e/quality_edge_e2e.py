"""品质边界场景端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/quality_edge_e2e.py

覆盖场景（``docs/scenario-inventory-2026-10-29.md`` D 区，BACKLOG C-70）：

    D-E1  检验单无检验项 → 可建单（by design：纸面记录后统一判定，不拦）
    D-E2  检验结果未填 → 可判定（by design：未录入明细时不拦，见 judge 注释）
    D-E5  检验单关联不存在的工单 → 必须 400（修复后）
    D-B1  一批货部分合格部分不合格 → 混录 PASS/FAIL；
          不合格数超 Ac 判 ACC 被抽样守卫拦；改判 UAI 放行
    D-B2  同一检验单多个检验员录明细 → 每条结果有 created_by 归属（修复后）
    D-B3  判 REJ（锁批 + 自动 NCR）后改判 ACC → 批次解锁 + NCR 作废（修复后）
    D-E7  PPAP 必填要素缺失提交 → 400（submit_for_approval 完整性守卫，已通）

探针方法论：期望值由实测上游数字动态推导（Ac 从单上读回）；
断言区分"是谁拒的"（抽样守卫的 400 文案含"超过允收数"）；
批次/NCR 用 tag 隔离，不与存量数据争用。
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

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def err_msg(r):
    try:
        d = r.json().get("detail")
        return d.get("message", "") if isinstance(d, dict) else str(d)
    except Exception:
        return ""


def login(c, username, password):
    r = c.post(f"{API}/auth/login", json={
        "username": username, "password": password, "tenant_id": TENANT})
    if r.status_code != 200:
        return None
    return r.json()["access_token"]


def main():
    c = httpx.Client(timeout=25)
    token = login(c, USER, PWD)
    if not token:
        print("[FATAL] 登录失败")
        return 1
    c.headers.update({"Authorization": f"Bearer {token}", "X-Tenant-Id": TENANT})
    me = c.get(f"{API}/auth/me").json()
    admin_id = (me.get("data") or me).get("id")
    print(f"登录成功 tenant={TENANT} admin_id={admin_id}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    # ── D-E1 / D-E2：无检验项建单 + 无明细判定（by design 允许） ──
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "inspection", "material_id": 1,
        "remark": f"D-E1 无检验项 {tag}"})
    check("D-E1 无检验项检验单可建（by design）", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:120]}")
    if r.status_code != 200:
        return 1
    e1_order = r.json()["data"]["id"]

    r = c.put(f"{API}/inspection-orders/{e1_order}/judge", json={"result": "ACC"})
    check("D-E2 未录明细可判定（by design）", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:120]}")

    # ── D-E5：关联不存在工单 → 必须 400 ──
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "inspection", "material_id": 1,
        "work_order_id": 999999999, "remark": f"D-E5 幽灵工单 {tag}"})
    check("D-E5 关联不存在工单被拒", r.status_code == 400,
          f"HTTP {r.status_code} {err_msg(r)[:80]}")
    check("D-E5 报错指明工单不存在", "工单" in err_msg(r) and "不存在" in err_msg(r),
          err_msg(r)[:80])
    # 反向：不关联工单仍可建（D-E1 已覆盖），关联真实工单可建
    r = c.get(f"{API}/work-orders", params={"page": 1, "page_size": 1})
    real_wo = (r.json().get("data") or {}).get("list") or []
    if real_wo:
        r = c.post(f"{API}/inspection-orders", json={
            "order_type": "inspection", "material_id": 1,
            "work_order_id": real_wo[0]["id"], "remark": f"D-E5 真实工单 {tag}"})
        check("D-E5 关联真实工单可建", r.status_code == 200,
              f"HTTP {r.status_code} {r.text[:100]}")

    # ── D-B1：一批货部分合格部分不合格 ──
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "inspection", "material_id": 1,
        "lot_qty": 200, "aql": 2.5, "inspection_level": "II",
        "remark": f"D-B1 混判 {tag}"})
    check("D-B1 建抽样检验单", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:120]}")
    if r.status_code == 200:
        b1_order = r.json()["data"]["id"]
        od = c.get(f"{API}/inspection-orders/{b1_order}").json()["data"]
        ac = od.get("ac")
        check("D-B1 抽样方案已解析（Ac 非空）", ac is not None,
              f"ac={ac} re={od.get('re')} sample={od.get('sample_qty')}")
        if ac is not None:
            ac = int(ac)
            n_fail = ac + 1
            # 混录：n_fail 条 FAIL + 2 条 PASS（部分合格部分不合格共存）
            ok_all = True
            for i in range(n_fail):
                rr = c.post(f"{API}/inspection-results", json={
                    "order_id": b1_order, "item_name": f"尺寸{i+1}",
                    "measured_value": 99.9, "result": "FAIL"})
                ok_all = ok_all and rr.status_code == 200
            for i in range(2):
                rr = c.post(f"{API}/inspection-results", json={
                    "order_id": b1_order, "item_name": f"外观{i+1}",
                    "result": "PASS"})
                ok_all = ok_all and rr.status_code == 200
            check(f"D-B1 混录 {n_fail} FAIL + 2 PASS 成功", ok_all)
            results = c.get(f"{API}/inspection-orders/{b1_order}/results").json()["data"]
            check("D-B1 明细条数正确", len(results) == n_fail + 2,
                  f"got {len(results)} expect {n_fail + 2}")
            # 不合格数超 Ac → 判 ACC 被抽样守卫拦（★ 断言区分是谁拒的）
            r = c.put(f"{API}/inspection-orders/{b1_order}/judge", json={"result": "ACC"})
            check("D-B1 超 Ac 判 ACC 被拦", r.status_code == 400,
                  f"HTTP {r.status_code}")
            check("D-B1 拦截来自抽样守卫", "超过允收数" in err_msg(r),
                  err_msg(r)[:80])
            # 让步接收 UAI 是人工裁量 → 放行
            r = c.put(f"{API}/inspection-orders/{b1_order}/judge",
                      json={"result": "UAI", "remark": "特采放行"})
            check("D-B1 改判 UAI 放行（人工裁量）", r.status_code == 200,
                  f"HTTP {r.status_code} {r.text[:120]}")

    # ── D-B2：同一检验单多个检验员 → 明细归属可追溯 ──
    # 无角色用户会被权限闸 403 → 给检验员乙挂角色（优先管理员角色）
    #
    # ★ 必须翻**全量**、且优先按 code 精确命中 —— 不能用"第一页第一个"。
    #   实测：`mfg_demo` 里历次探针自建的 `role_empty_*` / `role_ro_*` 攒到 50+ 个，
    #   把内置的 `admin` 挤出了第一页（page_size=50），于是 `role_list[0]` 落到
    #   **空权限角色**上，新账号登录成功但 `M03:inspection_result:create` 403 ——
    #   表面看是"平台不给录明细"，实际是探针给自己挂了一个没权限的角色。
    role_list = []
    page = 1
    while True:
        d = c.get(f"{API}/roles", params={"page": page, "page_size": 100}).json().get("data") or {}
        batch = d.get("list") or d.get("items") or []
        role_list.extend(batch)
        if len(batch) < 100 or page >= 10:
            break
        page += 1

    role_id = None
    for want in ("admin", "inspector", "quality"):
        hit = next((r for r in role_list
                    if str(r.get("code", "")).lower() == want), None)
        if hit:
            role_id = hit["id"]
            break
    if role_id is None:
        # 退一步按名称找（内置角色名的中文写法）
        hit = next((r for r in role_list
                    if "管理员" in str(r.get("name", ""))), None)
        role_id = hit["id"] if hit else None
    insp2_name = f"inspector_{tag}"
    r = c.post(f"{API}/users", json={
        "username": insp2_name, "password": "test12345",
        "real_name": "检验员乙",
        "role_ids": [role_id] if role_id else None})
    check("D-B2 建第二检验员账号", r.status_code == 200,
          f"HTTP {r.status_code} role_id={role_id} {r.text[:100]}")
    tok2 = login(c, insp2_name, "test12345")
    check("D-B2 第二检验员可登录", tok2 is not None)
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "inspection", "material_id": 1,
        "remark": f"D-B2 多检验员 {tag}"})
    b2_order = r.json()["data"]["id"] if r.status_code == 200 else None
    if tok2 and b2_order:
        r1 = c.post(f"{API}/inspection-results", json={
            "order_id": b2_order, "item_name": "甲录-长度", "result": "PASS"})
        c2 = httpx.Client(timeout=25, headers={
            "Authorization": f"Bearer {tok2}", "X-Tenant-Id": TENANT})
        r2 = c2.post(f"{API}/inspection-results", json={
            "order_id": b2_order, "item_name": "乙录-宽度", "result": "PASS"})
        check("D-B2 两名检验员均可录明细",
              r1.status_code == 200 and r2.status_code == 200,
              f"甲 HTTP {r1.status_code} 乙 HTTP {r2.status_code} {r2.text[:100]}")
        results = c.get(f"{API}/inspection-orders/{b2_order}/results").json()["data"]
        creators = {x.get("item_name"): x.get("created_by") for x in results}
        check("D-B2 明细带 created_by 归属",
              len(creators) == 2 and all(v is not None for v in creators.values()),
              f"created_by={list(creators.values())}")
        check("D-B2 两名检验员归属不同",
              len({v for v in creators.values() if v is not None}) == 2,
              f"creators={creators}")

    # ── D-B3：REJ 改判 ACC → 批次解锁 + NCR 作废 ──
    batch_no = f"B-D3-{tag}"
    r = c.post(f"{API}/wms/batches", json={"batch_no": batch_no, "material_id": 1})
    check("D-B3 建批次", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    batch_id = (r.json().get("data") or {}).get("id") if r.status_code == 200 else None
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": f"RC-D3-{tag}", "receipt_type": "purchase",
        "source_type": "purchase", "warehouse_id": WAREHOUSE_ID,
        "items": [{"line_no": 1, "material_id": 1, "expected_qty": 5, "unit": "件"}]})
    if r.status_code == 200 and batch_id:
        ro_id = r.json()["data"]["id"]
        item = c.get(f"{API}/wms/receipt-orders/{ro_id}").json()["data"]["items"][0]
        r = c.post(f"{API}/wms/receipt-order-items/{item['id']}/receive",
                   json={"received_qty": 5, "batch_no": batch_no})
        check("D-B3 收货（带批次）", r.status_code == 200,
              f"HTTP {r.status_code} {r.text[:120]}")
        r = c.post(f"{API}/wms/receipt-order-items/{item['id']}/submit-inspection")
        insp_id = (r.json().get("data") or {}).get("inspection_id")
        check("D-B3 送检", bool(insp_id), f"inspection_id={insp_id}")
        r = c.put(f"{API}/inspection-orders/{insp_id}/judge", json={"result": "REJ"})
        d = r.json().get("data") or {}
        check("D-B3 判 REJ 锁批 + 开 NCR",
              r.status_code == 200 and d.get("batch_locked") is True and d.get("ncr_id"),
              f"locked={d.get('batch_locked')} ncr={d.get('ncr_id')}")
        ncr_id = d.get("ncr_id")
        b = c.get(f"{API}/wms/batches/{batch_id}").json()["data"]
        check("D-B3 REJ 后批次已锁", b.get("is_locked") in (True, 1),
              f"is_locked={b.get('is_locked')}")
        # 改判 ACC → 期望副作用回滚
        r = c.put(f"{API}/inspection-orders/{insp_id}/judge",
                  json={"result": "ACC", "remark": "复检合格，改判"})
        d = r.json().get("data") or {}
        check("D-B3 改判 ACC 成功", r.status_code == 200, f"HTTP {r.status_code}")
        b = c.get(f"{API}/wms/batches/{batch_id}").json()["data"]
        check("D-B3 改判后批次已解锁", b.get("is_locked") in (False, 0),
              f"is_locked={b.get('is_locked')}")
        if ncr_id:
            n = c.get(f"{API}/ncr/{ncr_id}").json()["data"]
            check("D-B3 改判后 NCR 已作废",
                  n.get("status") == "cancelled",
                  f"status={n.get('status')}")
        check("D-B3 改判回写明细 qualified",
              d.get("receipt_inspection_status") == "qualified",
              str(d.get("receipt_inspection_status")))

    # ── D-E7：PPAP 必填要素缺失提交被拦（已通，回归） ──
    lvl = 9
    r = c.post(f"{API}/ppap/levels", json={"level_no": lvl, "level_name": "D-E7 等级"})
    check("D-E7 建等级（或已存在复用）", r.status_code in (200, 400),
          f"HTTP {r.status_code}")
    r = c.post(f"{API}/ppap/elements", json={
        "element_code": f"DE7-{tag}", "element_name": "D-E7 必填要素",
        "level_no": lvl, "is_required": True, "sort_order": 1})
    check("D-E7 建必填要素", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    r = c.post(f"{API}/ppap/submissions/build", json={
        "product_id": 1, "customer_id": 1, "level_no": lvl,
        "change_note": f"D-E7 {tag}"})
    sub_id = (r.json().get("data") or {}).get("submission_id") if r.status_code == 200 else None
    check("D-E7 构建提交包", bool(sub_id), f"HTTP {r.status_code} {r.text[:120]}")
    if sub_id:
        r = c.post(f"{API}/ppap/submissions/{sub_id}/submit")
        check("D-E7 缺必填要素提交被拦", r.status_code == 400,
              f"HTTP {r.status_code}")
        check("D-E7 报错列出缺失要素", "提交不完整" in err_msg(r), err_msg(r)[:80])

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
