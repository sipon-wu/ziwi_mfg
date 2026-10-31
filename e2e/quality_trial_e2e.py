"""场景清单 ⚠️ 项复核探针（真实 HTTP）——D-S1 / D-S5 / G-S2。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/quality_trial_e2e.py

三条都是清单里剩下的 ⚠️，改判依据是**跑出来的数字**，不是读代码：

- **D-S1 来料检验 → ACC → 入库**（标注"联动未闭环"）：E-S1 已经证明
  「送检 → 判定 ACC → 入库明细转 qualified → 上架 → 库存真的增加」。
  但 D-S1 的关键校验点写的是「**检验单 + 结果**」—— 也就是判定之前还要
  **录入检验结果明细**（measured_value）。E-S1 那段是直接判定、没录结果，
  所以严格说它只覆盖了半条。这里补齐：录结果 → 判定 → 放行，三段都要有。
- **D-S5 成品检验 → REJ → NCR → 让步接收**（标注"处置=让步，需审批"）：
  验整条链能不能走到 disposition=concession，且留痕可查。
- **G-S2 试产执行 → 检验 → 评审**（标注"试产检验结论回流"）：
  试产单 advance → 评审 review → decide，结论是否回流到试产单。

输出 [OK]/[GAP]，退出码恒 0 —— 这是**探测**，不是断言。
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)
from wms_receipt_count_e2e import rows_of


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print("⚠️ 项复核：D-S1 来料检验 / D-S5 让步接收 / G-S2 试产评审")
    print("=" * 62)

    # ───────── 准备 ─────────
    r = c.get(f"{API}/wms/materials", params={"page": 1, "page_size": 3})
    mat = rows_of(r)[0]
    r = c.get(f"{API}/wms/warehouses", params={"page": 1, "page_size": 3})
    wh = rows_of(r)[0]
    r = c.get(f"{API}/wms/warehouses/{wh['id']}/locations")
    loc = (rows_of(r) or [None])[0]

    def inv_state(mid):
        """按物料取库存 —— 不能用 /wms/inventory 全量分页：
        库存行数早已过百，新行落在第 2 页，快照会"看不见"刚加的货（假绿/假红）。"""
        rr = c.get(f"{API}/wms/inventory/by-material", params={"material_id": mid})
        rows = rows_of(rr)
        if not rows:
            rr = c.get(f"{API}/wms/inventory", params={"page": 1, "page_size": 100})
            rows = [x for x in rows_of(rr) if x.get("material_id") == mid]
        return {x["id"]: float(x.get("quantity") or 0) for x in rows}

    # ══════════════ D-S1 来料检验 → ACC → 入库 ══════════════
    print("\n── D-S1 来料检验 → ACC → 入库（原标注：联动未闭环）──")
    ro_no = f"DS1-{tag}"
    r = c.post(f"{API}/wms/receipt-orders", json={
        "receipt_no": ro_no, "receipt_type": "purchase", "source_type": "purchase",
        "warehouse_id": wh["id"],
        "items": [{"line_no": 1, "material_id": mat["id"], "expected_qty": 20,
                   "received_qty": 0, "unit": mat.get("unit") or "PCS",
                   "batch_no": f"DS1B-{tag}"}],
    })
    ro_id = data(r).get("id")
    report("D-S1-1 建来料入库单", r.status_code == 200 and bool(ro_id),
           f"receipt_no={ro_no} {msg(r) if r.status_code != 200 else ''}")

    item_id = None
    if ro_id:
        item_id = (data(c.get(f"{API}/wms/receipt-orders/{ro_id}")).get("items")
                   or [{}])[0].get("id")
        c.post(f"{API}/wms/receipt-order-items/{item_id}/receive",
               json={"received_qty": 20})
        r = c.post(f"{API}/wms/receipt-order-items/{item_id}/submit-inspection")
        insp_id = data(r).get("inspection_id")
        report("D-S1-2 送检开出检验单", bool(insp_id), f"inspection_id={insp_id}")

        if insp_id:
            # ★D-S1 的关键点：判定之前必须能**录入检验结果明细**
            r = c.post(f"{API}/inspection-results", json={
                "order_id": insp_id, "item_name": "外观",
                "spec_value": "无划伤", "measured_value": 1.0,
                "unit": "级", "result": "PASS", "remark": f"D-S1 {tag}"})
            report("D-S1-3 ★可录入检验结果明细（measured_value）",
                   r.status_code == 200, msg(r) if r.status_code != 200 else "PASS")

            r = c.get(f"{API}/inspection-orders/{insp_id}/results")
            rr = rows_of(r)
            report("D-S1-4 检验结果可读回且挂在检验单上", bool(rr),
                   f"{len(rr)} 条 " + (f"measured={rr[0].get('measured_value')}"
                                       if rr else ""))

            def loc_qty(lid):
                """目标库位上该物料的数量。

                ★不能用"物料总量"当判据：收货那一步已经把货记进**待检区**，
                上架只是把它从待检区**挪到**正式库位 —— 总量不变、行数 +1。
                所以"检验放行的意义"是**货进了可用库位**（可以被拣选），
                而不是总量增加。拿总量比会得到恒假的结论。
                """
                if not lid:
                    return 0.0
                rr = c.get(f"{API}/wms/inventory/by-location",
                           params={"location_id": lid})
                return sum(float(x.get("quantity") or 0)
                           for x in rows_of(rr)
                           if x.get("material_id") == mat["id"])

            pre = loc_qty((loc or {}).get("id"))
            r = c.put(f"{API}/inspection-orders/{insp_id}/judge",
                      json={"result": "ACC", "remark": f"D-S1 {tag}"})
            report("D-S1-5 判定 ACC", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "ACC")

            st = (data(c.get(f"{API}/wms/receipt-orders/{ro_id}")).get("items")
                  or [{}])[0].get("inspection_status")
            report("D-S1-6 判定放行回写到入库明细", st == "qualified",
                   f"inspection_status={st}")

            r = c.post(f"{API}/wms/receipt-order-items/{item_id}/store",
                       json={"stored_qty": 20,
                             "location_id": (loc or {}).get("id")})
            report("D-S1-7 放行后可上架", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "stored_qty=20")

            post = loc_qty((loc or {}).get("id"))
            report("D-S1-8 ★放行后货进入正式库位（可被拣选）", post > pre,
                   f"目标库位 {pre:g} → {post:g}（+{post - pre:g}）")

    # ══════════════ D-S5 成品检验 → REJ → NCR → 让步接收 ══════════════
    print("\n── D-S5 成品检验 → REJ → NCR → 让步接收（原标注：处置=让步）──")
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "fqc", "material_id": mat["id"], "remark": f"D-S5 {tag}"})
    fqc_id = data(r).get("id")
    # 检验单号由服务端生成（QC-YYYYMMDD-NNNN），必须回读；
    # 拿自己传的 order_no 去匹配下游单据永远匹配不上（请求里根本没有这个字段）
    fqc_no = None
    if fqc_id:
        fqc_no = (data(c.get(f"{API}/inspection-orders/{fqc_id}")) or {}).get("order_no")
    report("D-S5-1 可建成品检验单（fqc）", r.status_code == 200 and bool(fqc_id),
           f"{msg(r)[:90] if r.status_code != 200 else f'id={fqc_id} no={fqc_no}'}")

    if fqc_id:
        r = c.put(f"{API}/inspection-orders/{fqc_id}/judge",
                  json={"result": "REJ", "remark": f"D-S5 {tag}"})
        report("D-S5-2 成品检验判定 REJ", r.status_code == 200,
               msg(r) if r.status_code != 200 else "REJ")

        r = c.get(f"{API}/ncr", params={"page": 1, "page_size": 100})
        ncrs = [x for x in rows_of(r)
                if str(x.get("source_no") or "") == str(fqc_no)]
        ncr_id = ncrs[0].get("id") if ncrs else None
        report("D-S5-3 判 REJ 自动开 NCR", bool(ncr_id),
               f"ncr_id={ncr_id}（命中 {len(ncrs)} 张）")

        if ncr_id:
            r = c.put(f"{API}/ncr/{ncr_id}/status",
                      json={"to_status": "reviewing", "action": "start_review"})
            report("D-S5-4 NCR 可进入评审", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "reviewing")

            r = c.put(f"{API}/ncr/{ncr_id}/status", json={
                "to_status": "disposed", "action": "dispose",
                "disposition": "concession",
                "disposition_remark": f"D-S5 让步接收 {tag}"})
            report("D-S5-5 ★可处置为让步接收（concession）",
                   r.status_code == 200, msg(r) if r.status_code != 200 else "concession")

            r = c.get(f"{API}/ncr/{ncr_id}")
            d = data(r)
            report("D-S5-6 处置结论落库", (d.get("disposition") == "concession"),
                   f"disposition={d.get('disposition')} status={d.get('status')}")

            r = c.get(f"{API}/ncr/{ncr_id}/trail")
            tr = rows_of(r)
            report("D-S5-7 ★处置留痕可追溯（trail）", bool(tr),
                   f"{len(tr)} 条 "
                   + (str((tr[0].get('action') or tr[0].get('to_status') or ''))
                      if tr else ""))

    # ══════════════ G-S2 试产执行 → 检验 → 评审 ══════════════
    print("\n── G-S2 试产执行 → 检验 → 评审（原标注：试产检验结论回流）──")
    r = c.post(f"{API}/trials", json={
        "trial_type": "new_product", "product_name": f"G-S2 试产{tag}",
        "planned_qty": 10, "lab_required": False})
    t_id = data(r).get("id") or data(r).get("order_id")
    report("G-S2-1 可建试产单", r.status_code == 200 and bool(t_id),
           f"{msg(r)[:90] if r.status_code != 200 else t_id}")

    if t_id:
        r = c.post(f"{API}/trials/{t_id}/advance", json={"to_status": "running"})
        report("G-S2-2 试产单可推进（执行中）", r.status_code == 200,
               f"{msg(r)[:90] if r.status_code != 200 else 'running'}")

        r = c.get(f"{API}/trials/{t_id}")
        st = (data(r) or {}).get("status")
        # advance 是"推进一步"（draft → lab_trial），不是"设为指定状态"，
        # 所以断言只能是"状态确实前进了"，不能咬死 running
        report("G-S2-3 试产状态真的前进了（不是只返回 200）",
               st not in (None, "draft", "pending"), f"status={st}")

        r = c.post(f"{API}/trials/{t_id}/review", json={
            "review_type": "trial_result", "conclusion": "pass",
            "remark": f"G-S2 评审 {tag}"})
        rv_id = data(r).get("id") or data(r).get("review_id")
        report("G-S2-4 可发起试产评审", r.status_code == 200 and bool(rv_id),
               f"{msg(r)[:90] if r.status_code != 200 else rv_id}")

        r = c.get(f"{API}/trials/{t_id}/reviews")
        rvs = rows_of(r)
        if not rv_id and rvs:
            rv_id = rvs[0].get("id")
        report("G-S2-5 评审记录可读回", bool(rvs), f"{len(rvs)} 条")

        if rv_id:
            r = c.post(f"{API}/trials/{t_id}/reviews/{rv_id}/decide",
                       json={"conclusion": "approved"})
            report("G-S2-6 ★评审可出结论（decide）", r.status_code == 200,
                   msg(r) if r.status_code != 200 else "approved")

        r = c.get(f"{API}/trials/{t_id}/reviews")
        rvs = rows_of(r)
        concl = [x for x in rvs
                 if str(x.get("conclusion") or x.get("decision")
                        or x.get("status") or "").lower() == "approved"]
        report("G-S2-7 ★评审结论回流到试产单（可查到已批准记录）", bool(concl),
               f"{len(concl)} 条已批准 "
               + (f"conclusion={rvs[0].get('conclusion')}" if rvs else ""))

    return summary()


if __name__ == "__main__":
    raise SystemExit(main())
