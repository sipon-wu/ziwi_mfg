"""清理 A推进器厂 在 staging 上因造数脚本重跑产生的重复行（只删重复副本，保留 id 最小的一条）。

用法：
    unset https_proxy; NO_PROXY='*' backend/.venv/Scripts/python.exe scripts/cleanup_thruster_dups.py [--apply]
不带 --apply 只打印计划，不动数据。
"""
import argparse
import os
import sys
from collections import defaultdict

import httpx

API = os.environ.get("API_BASE", "https://mfg1.ziwi.cn/api/v1")
TID = "t_5436c733aa1e"


def items_of(r):
    try:
        b = r.json()
    except Exception:  # noqa: BLE001
        return []
    d = b.get("data", b) if isinstance(b, dict) else b
    if isinstance(d, list):
        return d
    if isinstance(d, dict):
        for k in ("items", "list", "records"):
            if isinstance(d.get(k), list):
                return d[k]
    return []


def pages(c, path, params=None, cap=50):
    out, page = [], 1
    while page <= cap:
        p = dict(params or {})
        p.update({"page": page, "page_size": 100})
        r = c.get(path, params=p)
        if r.status_code != 200:
            return out
        batch = items_of(r)
        if not batch:
            return out
        out.extend(batch)
        if len(batch) < 100:
            return out
        page += 1
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true")
    args = ap.parse_args()

    c = httpx.Client(timeout=60)
    r = c.post(f"{API}/auth/login", json={
        "username": "ah_admin", "password": "Ah@2026seed", "tenant_id": TID})
    if r.status_code != 200:
        print("登录失败", r.status_code, r.text[:200])
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TID})

    plan = []  # (kind, delete_path, id, label)

    # ── 设备：按 equipment_code 去重 ──
    eqs = pages(c, f"{API}/equipment")
    g = defaultdict(list)
    for e in eqs:
        code = e.get("equipment_code")
        if code and code.startswith(("PRS-AH", "TQS-AH", "ETS-AH", "EOL-AH", "LKT-AH",
                                     "HFH-AH", "OVN-AH", "VAC-AH", "RWS-AH", "DSP-AH",
                                     "DBM-AH", "OIL-AH")):
            g[code].append(e.get("id"))
    for code, ids in g.items():
        ids = sorted(i for i in ids if i)
        for extra in ids[1:]:
            plan.append(("equipment", f"{API}/equipment/{extra}", extra, code))

    # ── 库位：按 location_code 去重 ──
    locs = pages(c, f"{API}/wms/locations")
    gl = defaultdict(list)
    for x in locs:
        code = x.get("location_code")
        if code and code.startswith("WH-AH-"):
            gl[code].append(x.get("id"))
    for code, ids in gl.items():
        ids = sorted(i for i in ids if i)
        for extra in ids[1:]:
            plan.append(("location", f"{API}/wms/locations/{extra}", extra, code))

    # ── 用户：按 username 去重 ──
    us = pages(c, f"{API}/users")
    gu = defaultdict(list)
    for x in us:
        code = x.get("username")
        if code and code.startswith("ah_"):
            gu[code].append(x.get("id"))
    for code, ids in gu.items():
        ids = sorted(i for i in ids if i)
        for extra in ids[1:]:
            plan.append(("user", f"{API}/users/{extra}", extra, code))

    # ── BOM：按 (product_id, material_code) 去重 ──
    for pid in (236, 237, 238):
        rows = pages(c, f"{API}/boms", {"product_id": pid})
        gg = defaultdict(list)
        for b in rows:
            gg[b.get("material_code")].append(b.get("id"))
        for mat, ids in gg.items():
            ids = sorted(i for i in ids if i)
            for extra in ids[1:]:
                plan.append(("bom", f"{API}/boms/{extra}", extra, f"{pid}/{mat}"))

    print(f"待清理重复行 {len(plan)} 条：")
    for kind, _, i, label in plan:
        print(f"  {kind:10s} id={i:<6} {label}")

    if not args.apply:
        print("\n（dry-run，加 --apply 才真删）")
        return 0

    okc = 0
    for kind, path, i, label in plan:
        r = c.delete(path)
        if r.status_code in (200, 204):
            okc += 1
        else:
            print(f"  [FAIL] {kind} id={i} {label} → HTTP {r.status_code} {r.text[:120]}")
    print(f"\n删除成功 {okc}/{len(plan)}")

    # 回读复核
    eqs2 = pages(c, f"{API}/equipment")
    ah = [e for e in eqs2 if (e.get("equipment_code") or "").startswith(
        ("PRS-AH", "TQS-AH", "ETS-AH", "EOL-AH", "LKT-AH", "HFH-AH", "OVN-AH",
         "VAC-AH", "RWS-AH", "DSP-AH", "DBM-AH", "OIL-AH"))]
    print(f"复核：艾华设备 {len(ah)} 台；BOM 行 {sum(len(pages(c, f'{API}/boms', {'product_id': p})) for p in (236, 237, 238))}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
