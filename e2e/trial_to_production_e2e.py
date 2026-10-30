"""试产 → 转量产（真落库）端到端场景验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/trial_to_production_e2e.py

覆盖场景（``docs/scenario-verification-2026-10-29.md`` §二 P0-4 / G-S3）：

    T1   建专用产品（避免动种子数据的 BOM）
    T2   建试产工单（new_product）
    T3   保存试产 BOM（3 行：2 行有效 + 1 行缺 material_code）
    T4   保存试产路线（3 道：2 道有 operation_id + 1 道缺）
    T5   提交评审 → 拿到 review_id
    T6   评审结论 approved
    T7   一键转量产 → 逐项核对写入量与告警
    T8   回查正式 BOM：product_bom 真有 2 行、version=1、is_active
    T9   回查正式路线：process_routes 状态 draft + route_steps 真有 2 道
    T10  重复转产被拒（已不在评审阶段）
    T11  第二张试产单「从正式 BOM 载入」→ trial_bom 真有数据
    T12  第二张试产单「从正式路线载入」→ trial_routes 真有数据
    T13  终止试产 → 终态后再转产被拒

改造前的失败现象：转产接口回 200 "转量产完成"，但 BOM 管理页与工艺路线页
查不到任何新增数据（``convert_to_production`` 只翻状态位、
``import_*_from_formal`` 是直接 return 空壳的桩函数）。
"""
import os
import sys
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

PASS, FAIL, WARN = [], [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def warn(name, detail=""):
    WARN.append(name)
    print(f"  [WARN] {name}" + (f" · {detail}" if detail else ""))


def body(r):
    try:
        return r.json()
    except Exception:
        return {}


def msg(r):
    d = body(r).get("detail")
    if isinstance(d, dict):
        return d.get("message") or str(d)
    return body(r).get("message") or r.text[:160]


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    # ── T1 建专用产品 ────────────────────────────────────────
    print("── T1 建专用产品 ──")
    code = f"PRO-E2E-{tag}"
    r = c.post(f"{API}/products", json={
        "code": code, "name": f"试产验证件{tag}", "unit": "件",
        "product_type": "finished", "spec": "E2E",
    })
    b = body(r)
    product_id = (b.get("data") or {}).get("id") if isinstance(b.get("data"), dict) else b.get("data")
    check("T1 建产品成功", r.status_code == 200 and bool(product_id),
          f"status={r.status_code} product_id={product_id} {msg(r) if r.status_code != 200 else ''}")
    if not product_id:
        return report()

    # ── T2 建试产工单 ────────────────────────────────────────
    print("\n── T2 建试产工单 ──")
    r = c.post(f"{API}/trials", json={
        "trial_type": "new_product", "product_id": product_id,
        "product_name": f"试产验证件{tag}", "product_spec": "E2E",
        "planned_qty": 100, "priority": 500,
    })
    b = body(r)
    order_id = (b.get("data") or {}).get("id")
    order_no = (b.get("data") or {}).get("order_no")
    check("T2 建试产工单成功", r.status_code == 200 and bool(order_id),
          f"order_no={order_no} {msg(r) if r.status_code != 200 else ''}")
    if not order_id:
        return report()

    # ── T3 保存试产 BOM ──────────────────────────────────────
    print("\n── T3 保存试产 BOM（2 有效 + 1 缺编码）──")
    bom_rows = [
        {"material_code": "M-001", "material_name": "冷轧钢板", "qty_per_unit": 2.5,
         "unit": "kg", "material_type": "raw", "scrap_rate": 0.02, "is_key_material": True},
        {"material_code": "M-002", "material_name": "深沟球轴承", "qty_per_unit": 4,
         "unit": "件", "material_type": "raw", "scrap_rate": 0},
        {"material_name": "无编码试制辅料", "qty_per_unit": 1, "unit": "kg"},
    ]
    r = c.put(f"{API}/trials/{order_id}/bom", json={"bom_json": bom_rows, "source_type": "manual"})
    check("T3 试产 BOM 已保存", r.status_code == 200, msg(r) if r.status_code != 200 else "")
    r = c.get(f"{API}/trials/{order_id}/bom")
    got = (body(r).get("data") or {}).get("bom_json") or []
    check("T3 回查试产 BOM 有 3 行", len(got) == 3, f"实际 {len(got)} 行")

    # ── T4 保存试产路线 ──────────────────────────────────────
    print("\n── T4 保存试产路线（2 道有工序ID + 1 道缺）──")
    route_rows = [
        {"operation_id": 2, "step_name": "粗车外圆", "step_seq": 10},
        {"operation_id": 3, "step_name": "精车外圆", "step_seq": 20},
        {"step_name": "去毛刺（未维护工序主数据）", "step_seq": 30},
    ]
    r = c.put(f"{API}/trials/{order_id}/routes", json={
        "route_json": route_rows, "source_type": "manual",
        "name": f"{code} 试制路线"})
    check("T4 试产路线已保存", r.status_code == 200, msg(r) if r.status_code != 200 else "")

    # ── T5 提交评审 ──────────────────────────────────────────
    print("\n── T5 提交评审 ──")
    r = c.post(f"{API}/trials/{order_id}/review", json={
        "review_stage": "final", "review_items": [{"item": "尺寸", "result": "ok"}]})
    review_id = (body(r).get("data") or {}).get("id")
    check("T5 提交评审成功", r.status_code == 200 and bool(review_id),
          f"review_id={review_id} {msg(r) if r.status_code != 200 else ''}")

    # ── T6 评审通过 ──────────────────────────────────────────
    print("\n── T6 评审结论 approved ──")
    r = c.post(f"{API}/trials/{order_id}/reviews/{review_id}/decide",
               json={"conclusion": "approved"})
    check("T6 评审通过", r.status_code == 200, msg(r) if r.status_code != 200 else "")

    # ── T7 转量产 ────────────────────────────────────────────
    print("\n── T7 一键转量产 ──")
    r = c.post(f"{API}/trials/{order_id}/convert")
    b = body(r)
    d = b.get("data") or {}
    check("T7 转产量接口返回 200", r.status_code == 200,
          msg(r) if r.status_code != 200 else "")
    if r.status_code != 200:
        return report()

    bom_res = d.get("bom") or {}
    route_res = d.get("route") or {}
    check("T7 正式 BOM 写入 2 行", bom_res.get("written") == 2, f"实际 {bom_res.get('written')}")
    check("T7 缺编码的 BOM 行被跳过", bom_res.get("skipped") == 1, f"skipped={bom_res.get('skipped')}")
    check("T7 正式 BOM 版本从 1 起", bom_res.get("version") == 1, f"version={bom_res.get('version')}")
    check("T7 正式路线写入 2 道", route_res.get("written") == 2, f"实际 {route_res.get('written')}")
    check("T7 正式路线状态为 draft", route_res.get("status") == "draft",
          f"status={route_res.get('status')}")
    check("T7 缺工序主数据的工艺被跳过", route_res.get("missing_operation") == 1,
          f"missing={route_res.get('missing_operation')}")
    ws = d.get("warnings") or []
    check("T7 告警含「缺 material_code」", any("material_code" in w for w in ws), " / ".join(ws))
    check("T7 告警含「缺 operation_id」", any("operation_id" in w for w in ws))
    check("T7 告警提示路线需发布", any("draft" in w for w in ws))

    # ── T8 回查正式 BOM ──────────────────────────────────────
    print("\n── T8 回查正式 BOM（product_bom 真实数据）──")
    r = c.get(f"{API}/boms", params={"product_id": product_id, "page_size": 50})
    b = body(r)
    items = (b.get("data") or {}).get("items") or []
    codes = [it.get("material_code") for it in items]
    check("T8 BOM 列表能查到刚写入的物料", "M-001" in codes and "M-002" in codes,
          f"codes={codes}")
    check("T8 只写入了 2 行", len(items) == 2, f"实际 {len(items)} 行")
    check("T8 缺编码的辅料没有落库", all(x for x in codes), f"codes={codes}")
    check("T8 版本号为 1", all(it.get("version") == 1 for it in items),
          f"versions={[it.get('version') for it in items]}")
    check("T8 全部处于生效状态", all(it.get("is_active") in (True, 1) for it in items))
    row0 = items[0] if items else {}
    check("T8 remark 标注了来源试产单", order_no in str(row0.get("remark") or ""),
          f"remark={row0.get('remark')}")

    # ── T9 回查正式路线 ──────────────────────────────────────
    print("\n── T9 回查正式路线（process_routes + route_steps）──")
    want_code = f"RTE-{code}"
    r = c.get(f"{API}/routes", params={"keyword": want_code, "page_size": 20})
    ritems = (body(r).get("data") or {}).get("items") or []
    target = next((x for x in ritems if x.get("code") == want_code), None)
    check("T9 路线列表能查到自动生成的路线", target is not None,
          f"找 {want_code}，实际 {[x.get('code') for x in ritems]}")
    if target:
        check("T9 路线状态为 draft（不自动发布）", target.get("status") == "draft",
              f"status={target.get('status')}")
        route_id = target.get("id")
        r = c.get(f"{API}/routes/{route_id}/steps")
        steps = body(r).get("data") or []
        check("T9 路线工序有 2 道", len(steps) == 2, f"实际 {len(steps)} 道")
        ops = sorted([s.get("operation_id") for s in steps])
        check("T9 工序关联到正确的主数据 ID", ops == [2, 3], f"operations={ops}")
        seqs = sorted([s.get("step_seq") for s in steps])
        check("T9 工序顺序保留", seqs == [10, 20], f"seqs={seqs}")
    else:
        route_id = None

    # ── T10 重复转产被拒 ─────────────────────────────────────
    print("\n── T10 重复转产被拒 ──")
    r = c.post(f"{API}/trials/{order_id}/convert")
    check("T10 重复转产返回 400", r.status_code == 400, f"status={r.status_code}")
    check("T10 错误信息说明不在评审阶段", "评审阶段" in msg(r), msg(r))

    # ── T11 从正式 BOM 载入 ──────────────────────────────────
    print("\n── T11 第二张试产单：从正式 BOM 载入 ──")
    r = c.post(f"{API}/trials", json={
        "trial_type": "new_process", "product_id": product_id,
        "product_name": f"试产验证件{tag}-B", "planned_qty": 50,
    })
    order2 = (body(r).get("data") or {}).get("id")
    check("T11 建第二张试产单", r.status_code == 200 and bool(order2), f"id={order2}")
    if order2:
        src_bom_id = items[0].get("id") if items else 0
        r = c.post(f"{API}/trials/{order2}/import-bom", json={"source_id": src_bom_id})
        check("T11 import-bom 返回 200", r.status_code == 200, msg(r))
        check("T11 载入行数为 2", len(body(r).get("data") or []) == 2,
              f"实际 {len(body(r).get('data') or [])} 行")
        r = c.get(f"{API}/trials/{order2}/bom")
        got = (body(r).get("data") or {}).get("bom_json") or []
        check("T11 试产 BOM 表真有数据（不再是空壳）", len(got) == 2, f"实际 {len(got)} 行")
        check("T11 载入的是正式版本内容", {x.get("material_code") for x in got} == {"M-001", "M-002"},
              f"codes={[x.get('material_code') for x in got]}")

        # ── T12 从正式路线载入 ──
        print("\n── T12 第二张试产单：从正式路线载入 ──")
        r = c.post(f"{API}/trials/{order2}/import-route", json={"source_id": route_id or 0})
        check("T12 import-route 返回 200", r.status_code == 200, msg(r))
        r = c.get(f"{API}/trials/{order2}/routes")
        data = body(r).get("data") or {}
        rj = data.get("route_json") or []
        check("T12 试产路线表真有工序", len(rj) == 2, f"实际 {len(rj)} 道")
        check("T12 工序带 operation_id", all(x.get("operation_id") for x in rj),
              f"{[x.get('operation_id') for x in rj]}")

        # ── T13 终止试产 ──
        print("\n── T13 终止试产 ──")
        r = c.post(f"{API}/trials/{order2}/terminate", json={
            "conclusion": "terminated", "terminated_reason": "E2E 验证完毕"})
        check("T13 终止成功", r.status_code == 200, msg(r))
        r = c.post(f"{API}/trials/{order2}/convert")
        check("T13 终态后再转产被拒", r.status_code == 400, f"status={r.status_code}")

    return report()


def report():
    print("\n" + "=" * 66)
    print(f"合计 {len(PASS) + len(FAIL)} 项：PASS {len(PASS)} / FAIL {len(FAIL)}"
          + (f" / WARN {len(WARN)}" if WARN else ""))
    if FAIL:
        print("失败项：")
        for f in FAIL:
            print(f"  - {f}")
    print("=" * 66)
    return 0 if not FAIL else 1


if __name__ == "__main__":
    sys.exit(main())
