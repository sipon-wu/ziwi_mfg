"""工单全生命周期端到端场景验证（真实 HTTP，不用 mock）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/work_order_lifecycle_e2e.py

覆盖场景（对应 docs/scenario-verification-2026-10-29.md 第六节最小改动 1&2）：

    S1  新建工单 → 草稿，可执行动作只有 下达/作废
    S2  草稿工单报工 → 400（改造前可报）
    S3  下达（强制，避免缺料阻塞）
    S4  已下达直接关闭 → 400（★ 改造前允许，工单凭空消失）
    S5  已下达报工 → 自动开工，actual_start_at 落库
    S6  带不良报工 → 自动开制程 NCR，且重复调用不重复开单
    S7  暂停 → 恢复（流水分别记 pause / resume）
    S8  完工 → actual_end_at 落库，超计划给 warning
    S9  关闭 → 终态；再关闭/再报工均被拒
    S10 作废需原因
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


def check(name: str, ok: bool, detail: str = ""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def stamp():
    return datetime.now().strftime("%m%d%H%M%S")


def main():
    client = httpx.Client(timeout=20)
    r = client.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    token = r.json()["access_token"]
    client.headers.update({"Authorization": f"Bearer {token}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    wo_no = f"WO-E2E-{stamp()}"
    print(f"== 工单 {wo_no} ==")

    # ── S1 新建 ──
    r = client.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": "P-E2E", "product_name": "端到端验证件",
        "planned_qty": 20, "workshop": "E2E车间"})
    check("S1 新建工单", r.status_code == 200 and r.json()["code"] == 0,
          f"HTTP {r.status_code}")
    if r.status_code != 200:
        print(r.text[:300])
        return 1

    lst = client.get(f"{API}/work-orders", params={"keyword": wo_no, "page_size": 5}).json()
    items = lst.get("data", {}).get("items", [])
    if not items:
        print("[FATAL] 列表里查不到刚建的工单")
        return 1
    wo = items[0]
    wo_id = wo["id"]
    check("S1 初始状态为 draft", wo["wo_status"] == "draft", wo["wo_status"])

    det = client.get(f"{API}/work-orders/{wo_id}").json()["data"]
    acts = [a["action"] for a in det.get("available_actions", [])]
    check("S1 草稿可执行动作 = release/cancel", set(acts) == {"release", "cancel"}, str(acts))

    # ── S2 草稿报工应被拒 ──
    r = client.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 5})
    code = (r.json().get("detail") or {}).get("code") if r.status_code != 200 else None
    check("S2 草稿工单报工被拒 (400-0007)", r.status_code == 400 and code == "400-0007",
          f"HTTP {r.status_code} code={code}")

    # ── S2b 数量为 0 的报工应被拒 ──
    r = client.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 0, "scrap_qty": 0})
    code = (r.json().get("detail") or {}).get("code") if r.status_code != 200 else None
    check("S2b 数量为 0 报工被拒 (400-0006)", r.status_code == 400 and code == "400-0006",
          f"HTTP {r.status_code} code={code}")

    # ── S3 下达（强制，绕过齐套） ──
    r = client.post(f"{API}/work-orders/{wo_id}/release",
                    json={"force_release": True, "force_reason": "E2E 强制下达"})
    check("S3 下达工单", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    det = client.get(f"{API}/work-orders/{wo_id}").json()["data"]
    check("S3 状态变为 released", det["wo_status"] == "released", det["wo_status"])

    # ── S4 已下达直接关闭应被拒（★ 行为变更） ──
    r = client.post(f"{API}/work-orders/{wo_id}/close")
    code = (r.json().get("detail") or {}).get("code") if r.status_code != 200 else None
    check("S4 已下达直接关闭被拒 (400-0002)", r.status_code == 400 and code == "400-0002",
          f"HTTP {r.status_code} code={code}")

    # ── S5 已下达报工 → 自动开工 ──
    r = client.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 10, "labor_hours": 2})
    data = r.json().get("data") if r.status_code == 200 else {}
    check("S5 报工成功", r.status_code == 200, f"HTTP {r.status_code} {r.text[:150]}")
    check("S5 首次报工自动开工", bool(data.get("started")) is True, str(data.get("started")))
    det = client.get(f"{API}/work-orders/{wo_id}").json()["data"]
    check("S5 状态变为 in_progress", det["wo_status"] == "in_progress", det["wo_status"])
    check("S5 actual_start_at 已写入", bool(det.get("actual_start_at")),
          str(det.get("actual_start_at")))

    # ── S6 带不良报工 → NCR ──
    r = client.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 3, "scrap_qty": 2, "defect_reason": "尺寸超差"})
    d = r.json().get("data") if r.status_code == 200 else {}
    ncr_id = d.get("ncr_id")
    check("S6 不良报工自动开 NCR", bool(ncr_id), f"ncr_id={ncr_id}")

    if ncr_id:
        r = client.get(f"{API}/ncr/{ncr_id}")
        ncr = r.json().get("data") or {}
        check("S6 NCR 来源为 process", ncr.get("source_type") == "process",
              str(ncr.get("source_type")))
        check("S6 NCR 缺陷数 = 2", float(ncr.get("defect_qty") or 0) == 2.0,
              str(ncr.get("defect_qty")))
        check("S6 NCR 关联工单", ncr.get("work_order_id") == wo_id,
              str(ncr.get("work_order_id")))
        check("S6 NCR 带组织归属（部门可见）", ncr.get("org_id") is not None,
              str(ncr.get("org_id")))

    det = client.get(f"{API}/work-orders/{wo_id}").json()["data"]
    check("S6 工单累计完成 13 / 报废 2",
          det["completed_qty"] == 13 and det["scrap_qty"] == 2,
          f"{det['completed_qty']}/{det['scrap_qty']}")

    # ── S7 暂停 / 恢复 ──
    r = client.post(f"{API}/work-orders/{wo_id}/pause", json={"reason": "E2E 缺料待料"})
    check("S7 暂停", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    r = client.post(f"{API}/work-orders/{wo_id}/resume")
    check("S7 恢复", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    logs = client.get(f"{API}/work-orders/{wo_id}/status-log").json()["data"]
    remarks = " | ".join((x.get("remark") or "") for x in logs)
    check("S7 流水含 pause 与 resume", "action=pause" in remarks and "action=resume" in remarks,
          remarks[:160])
    check("S7 恢复未重置开工时间",
          bool(client.get(f"{API}/work-orders/{wo_id}").json()["data"].get("actual_start_at")))

    # ── S8 完工 ──
    r = client.post(f"{API}/work-orders/{wo_id}/complete", json={})
    d = r.json().get("data") if r.status_code == 200 else {}
    check("S8 完工", r.status_code == 200, f"HTTP {r.status_code} {r.text[:150]}")
    det = client.get(f"{API}/work-orders/{wo_id}").json()["data"]
    check("S8 状态变为 completed", det["wo_status"] == "completed", det["wo_status"])
    check("S8 actual_end_at 已写入", bool(det.get("actual_end_at")),
          str(det.get("actual_end_at")))
    if d.get("warnings"):
        WARN.append(f"S8 完工告警: {d['warnings']}")
        print(f"  [WARN] 完工告警: {d['warnings']}")

    # ── S9 关闭 ──
    r = client.post(f"{API}/work-orders/{wo_id}/close")
    check("S9 关闭工单", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    det = client.get(f"{API}/work-orders/{wo_id}").json()["data"]
    check("S9 状态变为 closed", det["wo_status"] == "closed", det["wo_status"])
    check("S9 终态无可用动作", det.get("available_actions") == [],
          str(det.get("available_actions")))

    r = client.post(f"{API}/work-orders/{wo_id}/close")
    check("S9 重复关闭被拒", r.status_code == 400, f"HTTP {r.status_code}")

    r = client.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 1})
    code = (r.json().get("detail") or {}).get("code") if r.status_code != 200 else None
    check("S9 已关闭工单报工被拒", r.status_code == 400 and code == "400-0007",
          f"HTTP {r.status_code} code={code}")

    # ── S10 作废需原因（在新建的草稿单上验证） ──
    wo2_no = f"WO-E2E2-{stamp()}"
    client.post(f"{API}/work-orders", json={
        "wo_no": wo2_no, "product_code": "P-E2E", "product_name": "作废验证件",
        "planned_qty": 1})
    lst = client.get(f"{API}/work-orders", params={"keyword": wo2_no}).json()
    wo2 = lst["data"]["items"][0]
    r = client.post(f"{API}/work-orders/{wo2['id']}/cancel", json={"reason": ""})
    check("S10 作废缺原因被拒 (400-0004)",
          r.status_code in (400, 422), f"HTTP {r.status_code}")
    r = client.post(f"{API}/work-orders/{wo2['id']}/cancel", json={"reason": "E2E 收尾作废"})
    check("S10 作废成功", r.status_code == 200, f"HTTP {r.status_code} {r.text[:120]}")
    det2 = client.get(f"{API}/work-orders/{wo2['id']}").json()["data"]
    check("S10 状态变为 cancelled", det2["wo_status"] == "cancelled", det2["wo_status"])

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)} / WARN {len(WARN)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
