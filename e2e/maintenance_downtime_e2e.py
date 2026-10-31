"""保养停机闭环端到端**探测**脚本（真实 HTTP，台账 C-39 / 场景 X9）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/maintenance_downtime_e2e.py

探测而不是验收：通的打 ``[OK]``、断的打 ``[GAP]``，退出码恒 0。

链路（``docs/scenario-inventory-2026-10-29.md`` X9）::

    保养计划到期 → 生成任务 → 开工(设备停机) → 受影响工单暂停
                → 完工(关停机、算时长) → 设备恢复 → 交期顺延 → 计划滚到下一周期

改造前这条链一环都没接上：计划表 ``next_execute_at`` 从不写、没有到期扫描、
任务的 ``task_no`` 在 INSERT 里被丢掉、开工/完工只改一个 status 字段。
"""
import os
import sys
from datetime import datetime, timedelta, timezone

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

EQ_CODE = "E2E-EQ-MT"

OK, GAP = [], []


def ok(name, detail=""):
    OK.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def gap(name, detail=""):
    GAP.append(name)
    print(f"  [GAP] {name}" + (f" · {detail}" if detail else ""))


def report(name, is_ok, detail=""):
    (ok if is_ok else gap)(name, detail)
    return is_ok


def items_of(payload):
    d = (payload or {}).get("data")
    if isinstance(d, dict):
        return d.get("items") or d.get("list") or []
    return d or []


def data_of(payload):
    return (payload or {}).get("data")


def first_id(payload):
    d = data_of(payload)
    if isinstance(d, dict):
        return d.get("id")
    return d


def _dt(value):
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print(f"\n{'=' * 64}\nX9 保养停机：计划到期 → 任务 → 停机 → 排产调整\n{'=' * 64}")

    # ── M1 设备（起点 running） ──
    r = c.get(f"{API}/equipment", params={"page_size": 100})
    eq = next((x for x in items_of(r.json()) if x.get("equipment_code") == EQ_CODE), None)
    if eq:
        eq_id = eq["id"]
        ok("M1 设备已存在（复用）", f"id={eq_id}")
    else:
        r = c.post(f"{API}/equipment", json={
            "equipment_code": EQ_CODE, "equipment_name": "E2E 保养测试设备",
            "location": "E2E 车间"})
        eq_id = first_id(r.json()) if r.status_code == 200 else None
        report("M1 建设备", bool(eq_id), f"id={eq_id} HTTP {r.status_code}")
        if not eq_id:
            return 1
    c.put(f"{API}/equipment/{eq_id}", json={"status": "running"})

    # ── M2 建保养计划：到期日设在昨天，模拟"已经该保养了" ──
    overdue = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    r = c.post(f"{API}/maintenance-plans", json={
        "equipment_id": eq_id, "plan_name": f"E2E 月度保养 {tag}",
        "plan_type": "monthly", "cycle_value": 1, "cycle_unit": "month",
        "next_execute_at": overdue})
    plan_id = first_id(r.json()) if r.status_code == 200 else None
    report("M2 建保养计划（到期日在昨天）", bool(plan_id),
           f"id={plan_id} HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")
    if not plan_id:
        return 1
    plans = items_of(c.get(f"{API}/maintenance-plans",
                           params={"page_size": 100}).json())
    prow = next((x for x in plans if x.get("id") == plan_id), None)
    report("M2b 计划落库带 next_execute_at", bool(prow and prow.get("next_execute_at")),
           f"next_execute_at={prow.get('next_execute_at') if prow else None}")

    # ── M3 到期扫描 → 生成任务 ──
    r = c.post(f"{API}/maintenance-tasks/generate-due", json={})
    gen = data_of(r.json()) or {}
    report("M3 到期扫描生成任务", r.status_code == 200 and (gen.get("created") or 0) >= 1,
           f"scanned={gen.get('scanned')} created={gen.get('created')} "
           f"HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")
    mine = next((t for t in (gen.get("tasks") or []) if t.get("plan_id") == plan_id), None)
    task_id = mine["task_id"] if mine else None
    report("M3b 本计划的到期任务已生成", bool(task_id),
           f"task_id={task_id} task_no={mine.get('task_no') if mine else None}")
    if not task_id:
        return 1

    # ── M4 幂等：同日重复扫描不再生成 ──
    r = c.post(f"{API}/maintenance-tasks/generate-due", json={})
    gen2 = data_of(r.json()) or {}
    report("M4 重复扫描不重复建任务",
           (gen2.get("created") or 0) == 0 and (gen2.get("skipped") or 0) >= 1,
           f"created={gen2.get('created')} skipped={gen2.get('skipped')}")

    # ── M5 工单（in_progress）+ 指定受影响工单 ──
    wo_no = f"WO-MT-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": "E2E-FG-001", "product_name": "E2E 成品",
        "planned_qty": 10, "wo_type": "production",
        "scheduled_start_at": datetime.now().isoformat(timespec="seconds"),
        "scheduled_end_at": (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"),
        "remark": "探测脚本：保养停机"})
    wo_id = first_id(r.json()) if r.status_code == 200 else None
    report("M5 建工单", bool(wo_id), f"id={wo_id} HTTP {r.status_code}")
    if not wo_id:
        return 1
    c.post(f"{API}/work-orders/{wo_id}/release", json={"force_release": True,
                                                       "force_reason": "E2E 保养探测"})
    c.post(f"{API}/work-orders/{wo_id}/start", json={})
    wo0 = data_of((c.get(f"{API}/work-orders/{wo_id}").json())) or {}
    report("M5b 工单起点 in_progress", wo0.get("wo_status") == "in_progress",
           f"wo_status={wo0.get('wo_status')}")
    end_before = wo0.get("scheduled_end_at")

    r = c.put(f"{API}/maintenance-tasks/{task_id}", json={"work_order_id": wo_id})
    report("M5c 任务可指定受影响工单", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")

    # ── M6 开工：设备转 maintenance + 开停机 + 工单暂停 ──
    r = c.put(f"{API}/maintenance-tasks/{task_id}/start", json={})
    st = data_of(r.json()) or {}
    report("M6 保养开工", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:160] if r.status_code != 200 else ''}")
    eq1 = data_of((c.get(f"{API}/equipment/{eq_id}").json())) or {}
    report("M6b 开工后设备转 maintenance", eq1.get("status") == "maintenance",
           f"status={eq1.get('status')}")
    wo1 = data_of((c.get(f"{API}/work-orders/{wo_id}").json())) or {}
    report("M6c 受影响工单自动暂停", wo1.get("wo_status") == "paused",
           f"wo_status={wo1.get('wo_status')}")
    dt_id = st.get("downtime_id")
    report("M6d 开了停机记录（type=maintenance）", bool(dt_id), f"downtime_id={dt_id}")
    if not dt_id:
        return 1

    # ── M7 把停机起点前移 60 分钟，让时长有意义 ──
    FAULT_MIN = 60
    backdated = (datetime.now(timezone.utc) - timedelta(minutes=FAULT_MIN)).isoformat()
    r = c.put(f"{API}/downtimes/{dt_id}", json={"started_at": backdated})
    report("M7 停机起点可修正（补录）", r.status_code == 200, f"HTTP {r.status_code}")

    # ── M8 完工：关停机 + 设备恢复 + 工单恢复 + 顺延 + 计划滚动 ──
    r = c.put(f"{API}/maintenance-tasks/{task_id}/complete",
              json={"result": "更换润滑油、清洁导轨"})
    done = data_of(r.json()) or {}
    report("M8 保养完工", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:160] if r.status_code != 200 else ''}")
    eq2 = data_of((c.get(f"{API}/equipment/{eq_id}").json())) or {}
    report("M8b 完工后设备恢复 running", eq2.get("status") == "running",
           f"status={eq2.get('status')}")
    wo2 = data_of((c.get(f"{API}/work-orders/{wo_id}").json())) or {}
    report("M8c 受影响工单恢复 in_progress", wo2.get("wo_status") == "in_progress",
           f"wo_status={wo2.get('wo_status')}")

    minutes = done.get("downtime_minutes")
    report("M8d 算出停机时长", minutes is not None and abs(float(minutes) - FAULT_MIN) <= 2,
           f"downtime_minutes={minutes} 期望≈{FAULT_MIN}")

    end_after = wo2.get("scheduled_end_at")
    delta = None
    try:
        if end_before and end_after:
            delta = (_dt(end_after) - _dt(end_before)).total_seconds() / 60.0
    except Exception:  # noqa: BLE001
        delta = None
    report("M8e 交期按停机时长顺延", delta is not None and abs(delta - FAULT_MIN) <= 2,
           f"{end_before} → {end_after}"
           + (f"（顺延 {delta:.1f} 分钟）" if delta is not None else ""))

    report("M8f 计划滚到下一周期",
           bool(done.get("plan_next_execute_at")),
           f"plan_next_execute_at={done.get('plan_next_execute_at')}")

    # ── M9 计划已推进 → 再次扫描不该再生成 ──
    r = c.post(f"{API}/maintenance-tasks/generate-due", json={})
    gen3 = data_of(r.json()) or {}
    still = [t for t in (gen3.get("tasks") or []) if t.get("plan_id") == plan_id]
    report("M9 计划推进后不再重复到期", not still,
           f"本次仍生成 {len(still)} 条该计划任务")

    # ── M10 未开工直接完工应被拒（否则停机时长被静默吞掉） ──
    r = c.put(f"{API}/maintenance-tasks/{task_id}/complete", json={})
    report("M10 已完工任务重复完工幂等", r.status_code == 200,
           f"HTTP {r.status_code} {r.text[:120] if r.status_code != 200 else ''}")

    print(f"\n{'=' * 64}\n汇总：{len(OK)} 段通 / {len(GAP)} 段断\n{'=' * 64}")
    for name in GAP:
        print(f"  断点  {name}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as e:  # noqa: BLE001
        print(f"\n[FATAL] 探测异常: {type(e).__name__}: {e}")
        sys.exit(2)
