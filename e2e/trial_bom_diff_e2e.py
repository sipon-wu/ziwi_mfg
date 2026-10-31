"""G-E3「试产 BOM 与量产 BOM 差异对比」真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/trial_bom_diff_e2e.py

要证明的核心
------------
试产的本质是"这一版和上一版差在哪"。评审会上要逐条过差异，没有对比就只能
靠人拿两张表对着看 —— 而 **unit 从 g 变 kg 这种改动，数字没变、投料量差
1000 倍，肉眼一定会漏**。

本探针用真实数据构造四类差异，逐条验证端点把它们全报出来：
- qty_changed   用量变了
- unit_changed  ★数字没变、单位变了（唯一的存在理由）
- added         试产新增的料
- removed       试产去掉的料

并额外守两件事：
1. 端点不是 403（权限码必须收敛到 M16:trial:read）
2. 一字未改时 diff 必须为空（不能"always 有差异"）
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
    print("G-E3 试产 BOM 与量产 BOM 差异对比")
    print("=" * 62)

    # ── 准备：产品 ──
    r = c.post(f"{API}/products", json={
        "code": f"GE3{tag}", "name": f"G-E3探针产品{tag}",
        "unit": "pcs", "product_type": "finished"})
    report("G-E3-1 建产品", r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:60]}")
    if r.status_code != 200:
        summary()
        return 0
    pid = (data(r) or {}).get("id")

    # ── 准备：量产侧正式 BOM v1（三条：A 1.0 pcs / B 2.0 g / D 3.0 pcs）──
    base_spec = [("A", 1.0, "pcs"), ("B", 2.0, "g"), ("D", 3.0, "pcs")]
    for code, qty, unit in base_spec:
        rr = c.post(f"{API}/boms", json={
            "product_id": pid, "material_code": f"{code}-{tag}",
            "material_name": f"料{code}", "qty_per_unit": qty,
            "unit": unit, "version": 1, "is_active": True})
        if rr.status_code != 200:
            report(f"G-E3-2 正式BOM行 {code}", False,
                   f"HTTP {rr.status_code} {msg(rr)[:60]}")
            summary()
            return 0
    report("G-E3-2 量产侧正式 BOM v1 落库（3 行）", True, f"product_id={pid}")
    bom_ids = None

    # ── 建试产工单 ──
    r = c.post(f"{API}/trials", json={
        "trial_type": "new_product", "product_id": pid,
        "product_name": f"G-E3探针产品{tag}", "planned_qty": 100})
    report("G-E3-3 建试产工单", r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:60]}")
    if r.status_code != 200:
        summary()
        return 0
    oid = (data(r) or {}).get("id")

    # ── 从正式 BOM 载入（这一步决定 diff 的基线）──
    r = c.get(f"{API}/boms", params={"product_id": pid, "page_size": 50})
    rows = (data(r) or {}).get("items") or []
    report("G-E3-4 正式 BOM 可读回", len(rows) == 3, f"行数={len(rows)}")
    bom_ids = rows[0]["id"] if rows else None

    r = c.post(f"{API}/trials/{oid}/import-bom", json={"source_id": bom_ids})
    report("G-E3-5 从正式 BOM 载入试产 BOM", r.status_code == 200,
           f"HTTP {r.status_code} {msg(r)[:70]}")

    # ── G-E3-6 ★一字未改 → 必须零差异 ──
    # 这条是"反向验证"：如果这里就有差异，说明对齐逻辑是错的，
    # 后面报出来的四类差异也不可信。
    r = c.get(f"{API}/trials/{oid}/bom-diff")
    report("G-E3-6 ★端点不是 403（权限码收敛到 M16:trial:read）",
           r.status_code != 403, f"HTTP {r.status_code} {msg(r)[:70]}")
    if r.status_code != 200:
        summary()
        return 0
    d0 = data(r)
    report("G-E3-7 ★一字未改时零差异",
           d0.get("changed") is False and not d0.get("diffs"),
           f"changed={d0.get('changed')} 差异数={len(d0.get('diffs') or [])} "
           f"unchanged={d0.get('summary', {}).get('unchanged')}")
    report("G-E3-8 基线来自 source_bom_id（不是当前生效版）",
           "源正式BOM" in str(d0.get("baseline")), f"baseline={d0.get('baseline')}")

    # ── 改试产 BOM：A 用量翻倍、B 单位 g→kg（数字不变）、加 C、删 D ──
    trial_items = [
        {"material_code": f"A-{tag}", "material_name": "料A",
         "qty_per_unit": 2.0, "unit": "pcs"},          # qty_changed
        {"material_code": f"B-{tag}", "material_name": "料B",
         "qty_per_unit": 2.0, "unit": "kg"},           # ★unit_changed（数字没变）
        {"material_code": f"C-{tag}", "material_name": "料C",
         "qty_per_unit": 5.0, "unit": "g"},            # added
    ]                                                   # D 不写 → removed
    r = c.put(f"{API}/trials/{oid}/bom", json={
        "bom_json": trial_items, "source_type": "formal", "source_bom_id": bom_ids})
    report("G-E3-9 改试产 BOM（改用量 / 改单位 / 加料 / 删料）",
           r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:60]}")

    r = c.get(f"{API}/trials/{oid}/bom-diff")
    d = data(r)
    s = d.get("summary") or {}
    types = sorted(x.get("type") for x in (d.get("diffs") or []))
    report("G-E3-10 ★四类差异全部报出",
           types == ["added", "qty_changed", "removed", "unit_changed"],
           f"types={types} summary={s}")

    # ── ★核心：单位变了必须单独报，且用量那一项不能算变 ──
    unit_diffs = [x for x in (d.get("diffs") or []) if x.get("type") == "unit_changed"]
    unit_hits = [(x.get("material_code"),
                  (x.get("before") or {}).get("unit"),
                  (x.get("after") or {}).get("unit")) for x in unit_diffs]
    report("G-E3-11 ★★单位变化被单独报出（数字没变、g→kg 投料差 1000 倍）",
           len(unit_diffs) == 1 and unit_diffs[0].get("material_code") == f"B-{tag}",
           f"命中={unit_hits}")
    if unit_diffs:
        u = unit_diffs[0]
        report("G-E3-12 单位差异带 before/after 单位",
               (u.get("before") or {}).get("unit") == "g"
               and (u.get("after") or {}).get("unit") == "kg",
               f"before={u.get('before')} after={u.get('after')}")
    report("G-E3-13 ★B 行不算『用量变了』（2.0 → 2.0 数字确实没动）",
           not any(x.get("type") == "qty_changed" and x.get("material_code") == f"B-{tag}"
                   for x in (d.get("diffs") or [])),
           f"qty_changed 行={[x.get('material_code') for x in (d.get('diffs') or []) if x.get('type') == 'qty_changed']}")

    # ── 新增 / 删除 ──
    report("G-E3-14 新增的料被报出（C）",
           any(x.get("type") == "added" and x.get("material_code") == f"C-{tag}"
               for x in (d.get("diffs") or [])), f"summary.added={s.get('added')}")
    report("G-E3-15 删掉的料被报出（D）",
           any(x.get("type") == "removed" and x.get("material_code") == f"D-{tag}"
               for x in (d.get("diffs") or [])), f"summary.removed={s.get('removed')}")

    # ── 计数一致性 ──
    report("G-E3-16 差异条数与 summary 自洽",
           len(d.get("diffs") or []) == (s.get("added", 0) + s.get("removed", 0)
                                         + s.get("qty_changed", 0) + s.get("unit_changed", 0)),
           f"diffs={len(d.get('diffs') or [])} summary={s}")
    report("G-E3-17 返回体带 trial_count / baseline_count 便于页面展示",
           d.get("trial_count") == 3 and d.get("baseline_count") == 3,
           f"trial={d.get('trial_count')} baseline={d.get('baseline_count')}")

    # ── 不存在的试产单 → 404 而不是 500 ──
    r = c.get(f"{API}/trials/99999999/bom-diff")
    report("G-E3-18 不存在的试产单返回 404（不是 500 / 不是空差异）",
           r.status_code == 404, f"HTTP {r.status_code} {msg(r)[:60]}")

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
