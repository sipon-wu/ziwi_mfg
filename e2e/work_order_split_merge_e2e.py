"""工单拆分 / 合并端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/work_order_split_merge_e2e.py

覆盖场景（``docs/scenario-inventory-2026-10-29.md`` C 区，BACKLOG C-75）：

    C-S6  工单拆分：草稿单按数量拆成多张子单，母单留余量
          - 子单号 ``{母单号}-S1/-S2`` 可追溯，继承产品/工艺/设备/交期
          - 母单计划量减为余量、备注写明拆出哪几张
          - 非草稿单拒绝（已下达的单拆完物料账对不上）
          - 分出总量 >= 母单计划量 → 拒绝（母单不能变成 0 量空壳）
          - 重复拆同一张单 → 子单号冲突拒绝（不静默生成 -S3/-S4）
    C-S7  工单合并：多张同产品同工艺草稿单合成一张
          - 合并单计划量 = 各单之和，单号 ``{首单号}-M1``
          - 被合并单不删除，置 cancelled 且流水点名合并到哪张单
          - 不同产品 / 不同工艺路线 → 拒绝（那不是合并，是记成一笔）
          - 设备/工作中心不一致 → 只告警，不阻断
"""
import os
import sys
from datetime import datetime, timedelta

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
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


def err_code(r):
    try:
        d = r.json().get("detail")
        return d.get("code", "") if isinstance(d, dict) else ""
    except Exception:
        return ""


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    actx = c.get(f"{API}/routes", params={"page": 1, "page_size": 1}).json()["data"]
    if not actx["items"]:
        print("[FATAL] 库里没有任何工艺路线，无法验证工艺继承")
        return 1
    route_id = actx["items"][0]["id"]
    print(f"复用工艺路线 route_id={route_id}\n")

    def mk_equipment(code):
        r = c.post(f"{API}/equipment", json={
            "equipment_code": code, "equipment_name": f"设备{code}",
            "location": "C车间", "status": "idle"})
        assert r.status_code == 200, f"建设备失败 {r.status_code} {r.text[:300]}"
        return r.json()["data"]["id"]

    def mk_order(wo_no, qty=100, route=None, product="P-SPLIT",
                 equipment_id=None):
        body = {"wo_no": wo_no, "product_code": product,
                "product_name": f"产品{product}", "planned_qty": qty,
                "route_id": route_id if route is None else route,
                "scheduled_start_at": (datetime.now() + timedelta(days=2)
                                       ).isoformat(timespec="seconds"),
                "scheduled_end_at": (datetime.now() + timedelta(days=5)
                                     ).isoformat(timespec="seconds")}
        if equipment_id:
            body["equipment_id"] = equipment_id
        r = c.post(f"{API}/work-orders", json=body)
        assert r.status_code == 200, f"建工单 {wo_no} 失败 {r.status_code} {r.text[:400]}"
        return r.json()["data"]["id"]

    def get_order(oid):
        return c.get(f"{API}/work-orders/{oid}").json()["data"]

    def set_status(oid, status):
        r = c.put(f"{API}/work-orders/{oid}", json={"wo_status": status})
        assert r.status_code == 200, f"改状态失败 {r.status_code} {r.text[:300]}"

    # ==================== C-S6 拆分 ====================
    print("--- C-S6 工单拆分 ---")
    parent_no = f"E2E-SP-{tag}"
    pid = mk_order(parent_no, qty=100, product=f"P-SP-{tag}")

    r = c.post(f"{API}/work-orders/{pid}/split", json={"qtys": [30, 30]})
    ok = r.status_code == 200
    check("C-S6 草稿单拆 100 → 30+30 成功", ok,
          f"HTTP {r.status_code} msg={err_msg(r)[:100]}")
    if not ok:
        return report()
    d = r.json()["data"]
    kids = d.get("children") or []
    check("C-S6 母单计划量减为余量 40",
          d["parent"]["planned_qty"] == 40,
          f"before={d['parent'].get('planned_qty_before')} "
          f"after={d['parent'].get('planned_qty')}")
    check("C-S6 子单号为 {母单号}-S1/-S2（可追溯）",
          [k["wo_no"] for k in kids] == [f"{parent_no}-S1", f"{parent_no}-S2"],
          str([k["wo_no"] for k in kids]))

    kid1 = get_order(kids[0]["id"])
    check("C-S6 子单继承工艺路线 / 产品 / 交期",
          kid1.get("route_id") == route_id
          and kid1.get("product_code") == f"P-SP-{tag}"
          and kid1.get("scheduled_end_at"),
          f"route={kid1.get('route_id')} product={kid1.get('product_code')}"
          f" end={kid1.get('scheduled_end_at')}")
    check("C-S6 子单齐套状态重置为待检查（不继承母单结论）",
          kid1.get("material_check_status") == "pending",
          f"material_check_status={kid1.get('material_check_status')}")
    check("C-S6 子单仍为草稿状态", kid1.get("wo_status") == "draft",
          f"wo_status={kid1.get('wo_status')}")
    check("C-S6 子单备注写明从哪张单拆出",
          parent_no in (kid1.get("remark") or ""),
          f"remark={(kid1.get('remark') or '')[:60]}")

    parent = get_order(pid)
    check("C-S6 母单备注留拆分痕迹（拆出几张、单号）",
          "已拆分" in (parent.get("remark") or "")
          and f"{parent_no}-S1" in (parent.get("remark") or ""),
          f"remark={(parent.get('remark') or '')[:80]}")

    r = c.post(f"{API}/work-orders/{pid}/split", json={"qtys": [10]})
    check("C-S6 重复拆同一张单 → 400（子单号已存在）",
          r.status_code == 400 and err_code(r) == "400-0023",
          f"HTTP {r.status_code} code={err_code(r)} msg={err_msg(r)[:80]}")

    pid2 = mk_order(f"E2E-SP2-{tag}", qty=50, product=f"P-SP2-{tag}")
    r = c.post(f"{API}/work-orders/{pid2}/split", json={"qtys": [50]})
    check("C-S6 分出总量 == 母单计划量 → 400（母单不能变成 0 量空壳）",
          r.status_code == 400 and err_code(r) == "400-0022",
          f"HTTP {r.status_code} code={err_code(r)} msg={err_msg(r)[:80]}")

    pid3 = mk_order(f"E2E-SP3-{tag}", qty=60, product=f"P-SP3-{tag}")
    set_status(pid3, "released")
    r = c.post(f"{API}/work-orders/{pid3}/split", json={"qtys": [10]})
    check("C-S6 已下达单不可拆 → 400（拆完物料账对不上）",
          r.status_code == 400 and err_code(r) == "400-0020",
          f"HTTP {r.status_code} code={err_code(r)} msg={err_msg(r)[:80]}")

    r = c.post(f"{API}/work-orders/{pid2}/split", json={"qtys": []})
    check("C-S6 qtys 为空 → 400", r.status_code == 400,
          f"HTTP {r.status_code} code={err_code(r)}")

    r = c.post(f"{API}/work-orders/{pid2}/split", json={"qtys": [0, 5]})
    check("C-S6 子单数量为 0 → 400（不做 0 量空单）",
          r.status_code == 400 and err_code(r) == "400-0021",
          f"HTTP {r.status_code} code={err_code(r)}")

    # ==================== C-S7 合并 ====================
    print("\n--- C-S7 工单合并 ---")
    prod = f"P-MG-{tag}"
    eq_a = mk_equipment(f"EQ-MG-A-{tag}")
    eq_b = mk_equipment(f"EQ-MG-B-{tag}")
    m1 = mk_order(f"E2E-MG1-{tag}", qty=20, product=prod, equipment_id=eq_a)
    m2 = mk_order(f"E2E-MG2-{tag}", qty=30, product=prod, equipment_id=eq_a)

    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [m1, m2]})
    ok = r.status_code == 200
    check("C-S7 两张同产品同工艺草稿单合并成功", ok,
          f"HTTP {r.status_code} msg={err_msg(r)[:100]}")
    if not ok:
        return report()
    d = r.json()["data"]
    merged = d["merged_order"]
    check("C-S7 合并单计划量 = 各单之和 50",
          merged["planned_qty"] == 50, f"planned_qty={merged['planned_qty']}")
    check("C-S7 合并单号默认为 {首单号}-M1",
          merged["wo_no"] == f"E2E-MG1-{tag}-M1", f"wo_no={merged['wo_no']}")

    mo = get_order(merged["id"])
    check("C-S7 合并单继承工艺路线 / 产品",
          mo.get("route_id") == route_id and mo.get("product_code") == prod,
          f"route={mo.get('route_id')} product={mo.get('product_code')}")

    src1, src2 = get_order(m1), get_order(m2)
    check("C-S7 被合并单不删除、置为已作废（终态）",
          src1.get("wo_status") == "cancelled"
          and src2.get("wo_status") == "cancelled",
          f"{src1.get('wo_status')} / {src2.get('wo_status')}")

    logs = c.get(f"{API}/work-orders/{m1}/status-log").json()["data"]
    rows = logs.get("items") if isinstance(logs, dict) else logs
    hit = [x for x in (rows or [])
           if "merge" in (x.get("remark") or "") and merged["wo_no"] in (x.get("remark") or "")]
    check("C-S7 状态流水点名合并到哪张单（原单不脱钩）", bool(hit),
          f"hit={len(hit)} remark={(hit[0].get('remark') if hit else '')[:60]}")

    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [m1]})
    check("C-S7 只有一张单 → 400", r.status_code == 400 and err_code(r) == "400-0030",
          f"HTTP {r.status_code} code={err_code(r)}")

    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [m1, 99999999]})
    check("C-S7 引用不存在的工单 → 400（不静默略过）",
          r.status_code == 400 and err_code(r) == "400-0031",
          f"HTTP {r.status_code} code={err_code(r)}")

    n1 = mk_order(f"E2E-MG3-{tag}", qty=10, product=prod)
    n2 = mk_order(f"E2E-MG4-{tag}", qty=10, product=f"P-OTHER-{tag}")
    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [n1, n2]})
    check("C-S7 不同产品 → 400（那是两笔换型，不是合并）",
          r.status_code == 400 and err_code(r) == "400-0033",
          f"HTTP {r.status_code} code={err_code(r)} msg={err_msg(r)[:80]}")

    # 造"同产品、不同工艺路线"：新建一条路线挂到 n4 上
    # （注意 PUT /work-orders/{id} 不接受 route_id —— 工艺路线是建单时冻结的）
    rr = c.post(f"{API}/routes", json={
        "code": f"RTE-E2E-{tag}", "name": f"拆并测试路线 {tag}",
        "route_type": "production"})
    assert rr.status_code == 200, f"建路线失败 {rr.status_code} {rr.text[:300]}"
    other_route = (rr.json().get("data") or {}).get("id") \
        or rr.json()["data"].get("route_id")
    n3 = mk_order(f"E2E-MG5-{tag}", qty=10, product=prod)
    n4 = mk_order(f"E2E-MG6-{tag}", qty=10, product=prod, route=other_route)
    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [n3, n4]})
    check("C-S7 不同工艺路线 → 400",
          r.status_code == 400 and err_code(r) == "400-0034",
          f"HTTP {r.status_code} code={err_code(r)} msg={err_msg(r)[:80]}")

    n5 = mk_order(f"E2E-MG7-{tag}", qty=10, product=prod)
    n6 = mk_order(f"E2E-MG8-{tag}", qty=10, product=prod)
    set_status(n6, "released")
    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [n5, n6]})
    check("C-S7 含已下达单 → 400 且点名是哪张",
          r.status_code == 400 and err_code(r) == "400-0032"
          and f"E2E-MG8-{tag}" in err_msg(r),
          f"HTTP {r.status_code} code={err_code(r)} msg={err_msg(r)[:90]}")

    n7 = mk_order(f"E2E-MG9-{tag}", qty=10, product=prod, equipment_id=eq_a)
    n8 = mk_order(f"E2E-MGA-{tag}", qty=10, product=prod, equipment_id=eq_b)
    r = c.post(f"{API}/work-orders/merge", json={"order_ids": [n7, n8]})
    ok = r.status_code == 200
    warns = (r.json().get("data") or {}).get("warnings") or [] if ok else []
    check("C-S7 设备不一致只告警不阻断",
          ok and any("设备不一致" in w for w in warns),
          f"HTTP {r.status_code} warnings={warns}")

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
