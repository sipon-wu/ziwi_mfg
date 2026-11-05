"""一次性探针：摸清检验单 / checklist / 结果的实际结构。"""
import json
import httpx

API = "https://mfg1.ziwi.cn/api/v1"
TID = "t_1692982c9cb7"  # 2026-11-05 清库重建后 AH-THR 的新 tenant_id（旧值 t_af6dfe17d206 已随旧库归档到 mfg_legacy_20261105）
c = httpx.Client(timeout=30)
tok = c.post(f"{API}/auth/login", json={"username": "ah_admin", "password": "Ah@2026seed", "tenant_id": TID}).json()["access_token"]
c.headers["Authorization"] = f"Bearer {tok}"


def unwrap(r):
    j = r.json()
    return j.get("data", j) if isinstance(j, dict) else j


orders = unwrap(c.get(f"{API}/inspection-orders", params={"page_size": 20}))["items"]
print("订单数", len(orders))
for o in orders:
    oid = o["id"]
    print("=" * 60)
    print("单", o["order_no"], "id", oid, "type", o["order_type"], "result", o.get("result"))
    det = unwrap(c.get(f"{API}/inspection-orders/{oid}"))
    print("  详情 keys:", sorted(det.keys()))
    for k in ("standard_id", "process_id", "work_order_id", "material_id", "qc_point_id"):
        print(f"    {k} =", det.get(k))

    ck = c.get(f"{API}/inspection-orders/{oid}/checklist")
    cb = unwrap(ck)
    print("  checklist", ck.status_code, "类型", type(cb).__name__)
    if isinstance(cb, dict):
        print("    keys:", sorted(cb.keys()))
        for k, v in cb.items():
            if isinstance(v, list):
                print(f"    {k} 长度 {len(v)}", json.dumps(v[:1], ensure_ascii=False)[:280] if v else "")
    elif isinstance(cb, list):
        print("    长度", len(cb), json.dumps(cb[:1], ensure_ascii=False)[:280])

    rb = unwrap(c.get(f"{API}/inspection-orders/{oid}/results"))
    rs = rb.get("items") if isinstance(rb, dict) else rb
    print("  已有结果", len(rs or []))
    if rs:
        print("    样例:", json.dumps(rs[0], ensure_ascii=False)[:280])
