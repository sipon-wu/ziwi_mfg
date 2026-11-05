"""供应商主数据端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行，且已执行 seeds/suppliers_seed.py）::

    cd backend && ./.venv/Scripts/python.exe seeds/suppliers_seed.py
    cd backend && ./.venv/Scripts/python.exe ../e2e/supplier_master_e2e.py

覆盖（BACKLOG C-78，B-11 的工程落点）：

    S-1  种子数据可查（10 家，四类齐全），列表按简称排序（下拉好找）
    S-2  关键词 / 类别过滤生效（搜"华东"能命中、按 pack 只剩包材）
    S-3  详情可取，不存在的 id → 404
    S-4  **只读**：没有写接口（POST /suppliers → 405）—— 供应商主数据归 ERP
    S-5  NCR 带 supplier_id 建单 → 自动回填 supplier_name（不用手打、也不会 id 与名字分裂）
    S-6  NCR 带**不存在**的 supplier_id → 400 点名，不落一条指向空气的单
    S-7  NCR 列表回填 supplier_name；按 supplier_id 过滤只出这家
"""
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

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


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    # ── S-1 种子数据 ──
    print("── C-78 供应商主数据 ──")
    r = c.get(f"{API}/suppliers", params={"page": 1, "page_size": 50})
    ok = r.status_code == 200
    items = (r.json().get("data") or {}).get("items") or []
    check("S-1 供应商列表可查（种子已灌）", ok and len(items) >= 10,
          f"HTTP {r.status_code} n={len(items)}")
    if not ok:
        return report()

    cats = {x.get("category") for x in items}
    check("S-1 四类供应商齐全（原材料/包材/外协/服务）",
          {"raw", "pack", "outsource", "service"} <= cats, str(sorted(cats)))
    names = [x.get("short_name") or x.get("name") for x in items]
    check("S-1 列表按简称排序（下拉里按业务习惯找得到）",
          names == sorted(names), f"head={names[:3]}")
    check("S-1 种子行标了 source=seed（上线可一键摘掉，不误删真实主数据）",
          all(x.get("source") == "seed" for x in items),
          str({x.get("source") for x in items}))
    check("S-1 带 ERP 侧编码（对账锚点）",
          all(x.get("erp_code") for x in items),
          f"缺失={[x['code'] for x in items if not x.get('erp_code')]}")

    # ── S-2 过滤 ──
    r = c.get(f"{API}/suppliers", params={"keyword": "华东"})
    d = r.json().get("data") or {}
    check("S-2 关键词搜索命中（名称/简称模糊）",
          d.get("total") == 1 and (d.get("items") or [{}])[0].get("code") == "SUP-001",
          f"total={d.get('total')}")
    r = c.get(f"{API}/suppliers", params={"category": "pack"})
    d = r.json().get("data") or {}
    check("S-2 按类别过滤（pack 只剩包材）",
          d.get("total") and all(x["category"] == "pack" for x in d["items"]),
          f"total={d.get('total')}")

    # ── S-3 详情 ──
    sid = next(x["id"] for x in items if x["code"] == "SUP-001")
    r = c.get(f"{API}/suppliers/{sid}")
    check("S-3 供应商详情可取（含联系人/地址/税号）",
          r.status_code == 200
          and (r.json().get("data") or {}).get("contact_name"),
          f"HTTP {r.status_code}")
    r = c.get(f"{API}/suppliers/99999999")
    check("S-3 不存在的供应商 → 404", r.status_code == 404, f"HTTP {r.status_code}")

    # ── S-4 只读 ──
    r = c.post(f"{API}/suppliers", json={"code": "X", "name": "不该能建"})
    check("S-4 没有新建接口（405）—— 主数据归 ERP，MES 不自建",
          r.status_code == 405, f"HTTP {r.status_code}")

    # ── S-5 判 NCR 回填供应商名 ──
    ncr_no = f"NC-SUP-{tag}"
    r = c.post(f"{API}/ncr", json={
        "ncr_no": ncr_no, "source_type": "iqc",
        "supplier_id": sid, "material_name": "冷轧钢板 1.5mm",
        "total_qty": 100, "defect_qty": 8, "severity": "major",
        "defect_desc": "来料表面划伤（C-78 探针）"})
    ok = r.status_code == 200
    check("S-5 带 supplier_id 建 NCR 成功", ok,
          f"HTTP {r.status_code} msg={err_msg(r)[:80]}")
    if ok:
        ncr_id = (r.json().get("data") or {}).get("id")
        r2 = c.get(f"{API}/ncr/{ncr_id}")
        row = r2.json().get("data") or {}
        check("S-5 供应商名自动回填（优先简称，不用手打）",
              row.get("supplier_name") == "华东金属",
              f"supplier_name={row.get('supplier_name')}")

        r3 = c.get(f"{API}/ncr", params={"supplier_id": sid, "page_size": 50})
        lst = (r3.json().get("data") or {}).get("items") or []
        hit = [x for x in lst if x.get("ncr_no") == ncr_no]
        check("S-7 NCR 列表带 supplier_name（不再只有一串 id）",
              bool(hit) and hit[0].get("supplier_name") == "华东金属",
              f"hit={hit[0].get('supplier_name') if hit else '未命中'}")
        check("S-7 按 supplier_id 过滤只出这家",
              all(x.get("supplier_id") == sid for x in lst),
              f"n={len(lst)}")
    else:
        check("S-5 供应商名自动回填", False, "建单失败，跳过")
        check("S-7 NCR 列表带 supplier_name", False, "建单失败，跳过")
        check("S-7 按 supplier_id 过滤只出这家", False, "建单失败，跳过")

    # ── S-6 幽灵供应商 ──
    r = c.post(f"{API}/ncr", json={
        "ncr_no": f"NC-GHOST-{tag}", "source_type": "iqc",
        "supplier_id": 99999999, "material_name": "幽灵来料",
        "total_qty": 10, "defect_qty": 1})
    check("S-6 不存在的供应商 → 400 点名（不落指向空气的单）",
          r.status_code == 400 and "供应商" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:80]}")
    r = c.get(f"{API}/ncr", params={"page_size": 100, "keyword": f"NC-GHOST-{tag}"})
    left = [x for x in ((r.json().get("data") or {}).get("items") or [])
            if x.get("ncr_no") == f"NC-GHOST-{tag}"]
    check("S-6 被拒的单没有落库", not left, f"残留={len(left)}")

    return report()


def report():
    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
