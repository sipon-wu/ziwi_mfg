"""全流程造数前的**只读**底数盘点（临时脚本，不入库）。

用法::

    API_BASE=https://mfg1.ziwi.cn/api/v1 E2E_TENANT=AH-THR \
      ./backend/.venv/Scripts/python.exe e2e/_flow_survey.py

只打印 + 落一份 JSON 到 ``e2e/_flow_survey.json``，不写任何数据。
"""
import json
import os

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")
OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "_flow_survey.json")


def body(r):
    try:
        return r.json()
    except Exception:  # noqa: BLE001
        return {}


def data_of(r):
    d = body(r).get("data")
    if isinstance(d, dict):
        for k in ("items", "list", "records", "rows"):
            if isinstance(d.get(k), list):
                return d[k]
        return d
    return d if isinstance(d, list) else []


def get(c, path, **params):
    params.setdefault("page_size", 100)   # 各列表端点上限都是 100
    r = c.get(f"{API}{path}", params=params)
    if r.status_code != 200:
        print(f"  ! GET {path} -> {r.status_code} {(r.text or '')[:120]}")
        return []
    return data_of(r)


def main():
    c = httpx.Client(timeout=40)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT} api={API}")

    snap = {}

    # ── 产品 / 物料 ──
    products = get(c, "/products")
    snap["products"] = [
        {"id": p.get("id"), "code": p.get("code"), "name": p.get("name"),
         "unit": p.get("unit"), "type": p.get("product_type")} for p in products]
    print(f"\n产品 {len(products)}")
    for p in snap["products"]:
        print(f"  {p['id']:>3} {p['code']:<16} {p['name']:<12} {p['unit']}  {p['type']}")

    mats = get(c, "/wms/materials")
    snap["materials"] = [
        {"id": m.get("id"), "code": m.get("code"), "name": m.get("name"),
         "unit": m.get("unit"), "type": m.get("material_type")} for m in mats]
    print(f"\n物料 {len(mats)}")
    for m in snap["materials"]:
        print(f"  {m['id']:>3} {m['code']:<16} {m['name']:<14} {m['unit']:<4} {m['type']}")

    # ── BOM 明细（扁平） ──
    boms = get(c, "/boms")
    snap["boms"] = [
        {"id": b.get("id"), "product": b.get("product_code") or b.get("parent_code"),
         "material": b.get("material_code"), "qty": b.get("qty_per_unit"),
         "seq": b.get("seq_no") or b.get("seq"), "op": b.get("issue_operation_seq")}
        for b in boms]

    # ── 仓库 / 库位 ──
    whs = get(c, "/wms/warehouses")
    snap["warehouses"] = [
        {"id": w.get("id"), "code": w.get("code") or w.get("warehouse_code"),
         "name": w.get("name")} for w in whs]
    print(f"\n仓库 {len(whs)}")
    for w in snap["warehouses"]:
        print(f"  {w['id']:>3} {w['code']:<14} {w['name']}")

    locs = get(c, "/wms/locations")
    snap["locations"] = [
        {"id": l.get("id"), "code": l.get("location_code") or l.get("code"),
         "name": l.get("name"), "wh": l.get("warehouse_id")} for l in locs]
    print(f"\n库位 {len(locs)}")
    for l in snap["locations"]:
        print(f"  {l['id']:>3} {l['code']:<14} wh={l['wh']}  {l['name']}")

    # ── 路线 / 步骤 ──
    routes = get(c, "/routes")
    snap["routes"] = []
    print(f"\n路线 {len(routes)}")
    for rt in routes:
        steps = get(c, f"/routes/{rt['id']}/steps")
        snap["routes"].append({
            "id": rt.get("id"), "code": rt.get("code"), "name": rt.get("name"),
            "product": rt.get("product_code"),
            "steps": [{"seq": s.get("seq_no"), "op": s.get("op_code"),
                       "name": s.get("op_name"), "wc": s.get("work_center_id"),
                       "wc_code": s.get("work_center_code"),
                       "is_inspect": s.get("is_inspect") or s.get("inspect_flag"),
                       "std_min": s.get("standard_minutes") or s.get("unit_time"),
                       "setup": s.get("setup_time")} for s in steps]})
        print(f"  {rt['id']:>3} {rt.get('code'):<18} {rt.get('name'):<10} "
              f"steps={len(steps)}")

    # ── 工作中心 ──
    wcs = get(c, "/work-centers")
    snap["work_centers"] = [
        {"id": w.get("id"), "code": w.get("code"), "name": w.get("name")} for w in wcs]
    print(f"\n工作中心 {len(wcs)}")

    # ── 检验点 / 标准 / 项目 ──
    qps = get(c, "/qc-points")
    snap["qc_points"] = [
        {"id": q.get("id"), "name": q.get("point_name"),
         "type": q.get("point_type"), "material_id": q.get("material_id"),
         "process_id": q.get("process_id"), "enabled": q.get("is_enabled")}
        for q in qps]
    print(f"\n检验点 {len(qps)}")
    for q in snap["qc_points"]:
        print(f"  {q['id']:>3} {str(q['type']):<6} {str(q['name'])[:28]:<30} "
              f"mat={q['material_id']} proc={q['process_id']}")

    stds = get(c, "/inspection-standards")
    all_items = get(c, "/inspection-items")
    snap["standards"] = []
    print(f"\n检验标准 {len(stds)} / 检验项 {len(all_items)}")
    for s in stds:
        mine = [i for i in all_items if i.get("standard_id") == s.get("id")]
        snap["standards"].append({
            "id": s.get("id"), "name": s.get("name"),
            "type": s.get("standard_type"), "version": s.get("version"),
            "enabled": s.get("is_enabled"), "remark": s.get("remark"),
            "items": [{"id": i.get("id"), "name": i.get("item_name"),
                       "unit": i.get("unit"),
                       "min": i.get("spec_lower_limit"),
                       "max": i.get("spec_upper_limit")} for i in mine]})
        print(f"  {s.get('id'):>3} {str(s.get('name'))[:26]:<28} "
              f"{str(s.get('standard_type')):<10} items={len(mine)}")

    # ── 现存量 ──
    stock = get(c, "/wms/reports/stock-summary")
    snap["stock"] = stock
    print(f"\n现存汇总行 {len(stock)}")
    for s in stock[:30]:
        print(f"  {s}")

    # ── 已有工单 / 报工 / 检验单 ──
    wos = get(c, "/work-orders")
    snap["work_orders"] = [
        {"id": w.get("id"), "wo_no": w.get("wo_no"), "product": w.get("product_code"),
         "qty": w.get("planned_qty"), "status": w.get("status")} for w in wos]
    print(f"\n工单 {len(wos)}")
    for w in snap["work_orders"]:
        print(f"  {w['id']:>3} {w['wo_no']:<24} {w['product']:<14} {w['qty']}  {w['status']}")

    ios = get(c, "/inspection-orders")
    snap["inspection_orders_count"] = len(ios)
    print(f"\n检验单 {len(ios)}")

    ros = get(c, "/wms/receipt-orders")
    snap["receipt_orders"] = len(ros)
    print(f"收货单 {len(ros)}")
    iss = get(c, "/wms/issue-orders")
    snap["issue_orders"] = len(iss)
    print(f"领料单 {len(iss)}")

    with open(OUT, "w", encoding="utf-8") as f:
        json.dump(snap, f, ensure_ascii=False, indent=1)
    print(f"\n已写入 {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
