"""D-S7「抽检（AQL 抽样方案）」真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/aql_sampling_e2e.py

要证明的核心
------------
**抽多少、允收几个，必须由批量和 AQL 查表决定，而不是检验员凭经验定。**
此前全库无任何抽样方案代码，``qc_point_config.sampling_plan`` 只是一串自由
文本（种子里写着 ``AQL=1.0``），检验单上连"批量"这一列都没有 ——
同一批货两个人抽能得出相反结论，且事后无法追溯依据。

本探针用真实数据跑完整闭环：
1. 试算端点：批量 3000 / AQL 2.5 → 抽 125、允收 7、拒收 8（外部可核对锚点）
2. 建检验单带批量 → 抽样方案自动落库（不再靠人填）
3. AQL 从检验点的 ``sampling_plan=AQL=1.0`` 自动带出（配置真的生效）
4. 录检验结果 → 建议判定按 Ac/Re 算出来
5. ★不合格数超 Ac 却判 ACC → 必须被 400 拦住（抽样方案不能形同虚设）
6. 样本量 ≥ 批量 → 自动转 100% 全检
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)


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
    print("D-S7 抽检（AQL 抽样方案）")
    print("=" * 62)

    # ── D-S7-1 试算端点可访问（权限码已收敛，不是 403）──
    r = c.get(f"{API}/inspection-orders/aql-plan",
              params={"lot_qty": 3000, "aql": 2.5, "inspection_level": "II"})
    report("D-S7-1 ★试算端点不是 403（权限码收敛到 M03:inspection_order:read）",
           r.status_code != 403, f"HTTP {r.status_code} {msg(r)[:70]}")
    if r.status_code != 200:
        summary()
        return 0
    p = data(r)
    report("D-S7-2 ★批量 3000 / 水平 II / AQL 2.5 → 抽 125、7/8（外部锚点）",
           (p.get("sample_qty"), p.get("ac"), p.get("re")) == (125, 7, 8),
           f"code={p.get('code_letter')} n={p.get('sample_qty')} "
           f"ac={p.get('ac')} re={p.get('re')}")
    report("D-S7-3 返回体带标准与字码（结论可复算）",
           p.get("code_letter") == "K" and "2828" in str(p.get("standard")),
           f"code={p.get('code_letter')} standard={p.get('standard')}")

    # ── 另外两条锚点 ──
    for lot, aql, exp in [(500, 2.5, (50, 3, 4)), (12000, 2.5, (315, 14, 15))]:
        rr = c.get(f"{API}/inspection-orders/aql-plan",
                   params={"lot_qty": lot, "aql": aql, "inspection_level": "II"})
        got = (data(rr).get("sample_qty"), data(rr).get("ac"), data(rr).get("re"))
        report(f"D-S7-4 锚点 批量{lot}/AQL{aql} → {exp}", got == exp, f"实得 {got}")

    # ── 非法 AQL 必须 400，不能静默给个错的 ──
    r = c.get(f"{API}/inspection-orders/aql-plan", params={"lot_qty": 500, "aql": 7.5})
    report("D-S7-5 ★表里没有的 AQL 档位返回 400（不静默退化）",
           r.status_code == 400, f"HTTP {r.status_code} {msg(r)[:70]}")

    # ── 样本量 ≥ 批量 → 100% 全检 ──
    r = c.get(f"{API}/inspection-orders/aql-plan",
              params={"lot_qty": 2, "aql": 2.5, "inspection_level": "III"})
    p = data(r)
    report("D-S7-6 ★样本量 ≥ 批量时自动转 100% 全检",
           p.get("full_inspection") is True and p.get("sample_qty") == 2
           and (p.get("ac"), p.get("re")) == (0, 1),
           f"full={p.get('full_inspection')} n={p.get('sample_qty')} "
           f"ac={p.get('ac')} re={p.get('re')}")

    # ── 准备：物料（建检验单用）──
    r = c.get(f"{API}/wms/materials", params={"page": 1, "page_size": 5})
    mats = (data(r) or {}).get("items") or []
    mat_id = mats[0]["id"] if mats else None
    report("D-S7-7 取到物料", mat_id is not None, f"material_id={mat_id}")
    if mat_id is None:
        summary()
        return 0

    # ── 准备：检验项（录结果要用）；库里没有就现建 ——
    # 种子数据未必带检验标准/检验项，缺了就自己造一条，别让探针依赖存量数据。
    r = c.get(f"{API}/inspection-items", params={"page": 1, "page_size": 5})
    items = (data(r) or {}).get("items") or []
    item_id = items[0]["id"] if items else None
    if item_id is None:
        r = c.post(f"{API}/inspection-standards", json={
            "name": f"D-S7探针标准{tag}", "standard_type": "enterprise", "version": "1.0"})
        r = c.get(f"{API}/inspection-standards", params={"page": 1, "page_size": 50})
        stds = (data(r) or {}).get("items") or []
        std = next((s for s in stds if f"D-S7探针标准{tag}" in str(s.get("name"))), None)
        if std:
            c.post(f"{API}/inspection-items", json={
                "standard_id": std["id"], "item_name": f"D-S7探针项{tag}",
                "spec_upper_limit": 20.0, "spec_lower_limit": 0.0, "unit": "mm"})
            r = c.get(f"{API}/inspection-items", params={"page": 1, "page_size": 50})
            items = (data(r) or {}).get("items") or []
            item_id = items[0]["id"] if items else None
    report("D-S7-8 取到检验项", item_id is not None, f"item_id={item_id}")

    # ── D-S7-9 ★建检验单带批量 → 抽样方案自动落库 ──
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "spot_check", "material_id": mat_id,
        "lot_qty": 3000, "aql": 2.5, "inspection_level": "II",
        "remark": f"D-S7探针{tag}"})
    report("D-S7-9 建检验单（带批量 3000 / AQL 2.5）", r.status_code == 200,
           f"HTTP {r.status_code} {msg(r)[:70]}")
    if r.status_code != 200:
        summary()
        return 0
    oid = (data(r) or {}).get("id")

    r = c.get(f"{API}/inspection-orders/{oid}")
    o = data(r)
    report("D-S7-10 ★抽样方案已落库（n=125, Ac=7, Re=8）",
           (o.get("sample_qty"), o.get("ac"), o.get("re")) == (125, 7, 8),
           f"lot={o.get('lot_qty')} aql={o.get('aql')} level={o.get('inspection_level')} "
           f"n={o.get('sample_qty')} ac={o.get('ac')} re={o.get('re')}")
    report("D-S7-11 输入三要素也一并留痕（批量/AQL/水平）",
           o.get("lot_qty") == 3000 and float(o.get("aql") or 0) == 2.5
           and o.get("inspection_level") == "II",
           f"lot={o.get('lot_qty')} aql={o.get('aql')} level={o.get('inspection_level')}")

    # ── D-S7-12 ★AQL 从检验点的 sampling_plan 自动带出（配置真的生效）──
    r = c.post(f"{API}/qc-points", json={
        "point_type": "IQC", "point_name": f"D-S7探针点{tag}",
        "sampling_plan": "AQL=1.0", "is_enabled": True})
    # create 只回提示语，id 要回读
    r = c.get(f"{API}/qc-points", params={"page": 1, "page_size": 50})
    qcs = (data(r) or {}).get("items") or []
    qc = next((q for q in qcs if f"D-S7探针点{tag}" in str(q.get("point_name"))), None)
    qc_id = qc["id"] if qc else None
    report("D-S7-12 建检验点（sampling_plan=AQL=1.0）", qc_id is not None,
           f"qc_id={qc_id} 已配={qc.get('sampling_plan') if qc else '-'}")

    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "spot_check", "material_id": mat_id,
        "qc_point_id": qc_id, "lot_qty": 500})
    oid2 = (data(r) or {}).get("id")
    if oid2:
        r = c.get(f"{API}/inspection-orders/{oid2}")
        o2 = data(r)
        report("D-S7-13 ★AQL 由检验点配置带出（未显式传也算出 n=50, 1/2）",
               (o2.get("sample_qty"), o2.get("ac"), o2.get("re")) == (50, 1, 2),
               f"aql={o2.get('aql')} n={o2.get('sample_qty')} "
               f"ac={o2.get('ac')} re={o2.get('re')}")
    else:
        report("D-S7-13 AQL 由检验点配置带出", False, f"建单失败 {msg(r)[:70]}")

    # ── D-S7-14 录检验结果后，建议判定按 Ac/Re 算出来 ──
    # 用批量 3000 那张单：Ac=7 / Re=8。录 3 条 PASS → 建议 ACC。
    for i in range(3):
        c.post(f"{API}/inspection-results", json={
            "order_id": oid, "item_id": item_id, "item_name": f"探针项{i}",
            "measured_value": 10.0 + i, "result": "PASS"})
    r = c.get(f"{API}/inspection-orders/{oid}/verdict")
    v = data(r)
    report("D-S7-14 ★建议判定端点不是 403", r.status_code != 403,
           f"HTTP {r.status_code} {msg(r)[:70]}")
    report("D-S7-15 ★3 条全 PASS → 建议 ACC（0 ≤ Ac 7）",
           v.get("suggested_result") == "ACC" and v.get("defect_count") == 0,
           f"defect={v.get('defect_count')} ac={v.get('ac')} re={v.get('re')} "
           f"建议={v.get('suggested_result')}")

    # ── D-S7-16 ★再录 9 条 FAIL（合计 9 > Ac 7）→ 建议 REJ ──
    for i in range(9):
        c.post(f"{API}/inspection-results", json={
            "order_id": oid, "item_id": item_id, "item_name": f"探针不合格{i}",
            "measured_value": 99.0 + i, "result": "FAIL"})
    r = c.get(f"{API}/inspection-orders/{oid}/verdict")
    v = data(r)
    report("D-S7-16 ★9 条 FAIL > Ac 7 → 建议 REJ",
           v.get("suggested_result") == "REJ" and v.get("defect_count") == 9,
           f"defect={v.get('defect_count')} ac={v.get('ac')} re={v.get('re')} "
           f"建议={v.get('suggested_result')}")

    # ── D-S7-17 ★★不合格数已超 Ac 却判 ACC → 必须被拦 ──
    r = c.put(f"{API}/inspection-orders/{oid}/judge", json={"result": "ACC"})
    report("D-S7-17 ★★不合格 9 > Ac 7 时判 ACC 被 400 拦住（抽样方案不是摆设）",
           r.status_code == 400, f"HTTP {r.status_code} {msg(r)[:80]}")
    if r.status_code == 400:
        report("D-S7-18 拒绝文案带具体数字（检验员知道为什么）",
               "9" in msg(r) and "7" in msg(r), f"{msg(r)[:100]}")

    # ── D-S7-19 判 REJ 应当放行（人工裁量方向不拦）──
    r = c.put(f"{API}/inspection-orders/{oid}/judge", json={"result": "REJ"})
    report("D-S7-19 判 REJ 放行（反方向不拦，保留人工裁量）",
           r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:70]}")
    if r.status_code == 200:
        sg = (data(r) or {}).get("sampling_guard")
        report("D-S7-20 判定响应回带抽样校验摘要",
               sg is not None and sg.get("defect_count") == 9, f"sampling_guard={sg}")

    # ── D-S7-21 无抽样方案的旧单照原样判定（不受影响，无回归）──
    r = c.post(f"{API}/inspection-orders", json={
        "order_type": "first", "material_id": mat_id, "remark": f"D-S7无抽样{tag}"})
    oid3 = (data(r) or {}).get("id")
    if oid3:
        r = c.get(f"{API}/inspection-orders/{oid3}/verdict")
        report("D-S7-21 无抽样方案返回 has_plan=False（不报错）",
               r.status_code == 200 and data(r).get("has_plan") is False,
               f"HTTP {r.status_code} {msg(r)[:60]}")
        r = c.put(f"{API}/inspection-orders/{oid3}/judge", json={"result": "ACC"})
        report("D-S7-22 ★无抽样方案的检验单判定不受影响（无回归）",
               r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:70]}")

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
