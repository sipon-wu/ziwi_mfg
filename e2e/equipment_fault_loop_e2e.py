"""设备故障闭环端到端**探测**脚本（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/equipment_fault_loop_e2e.py

与 ``*_e2e.py`` 验收脚本的区别同 ``quality_defect_loop_e2e.py``：本脚本是
**探测**不是验收 —— 通的打 ``[OK]``、断的打 ``[GAP]``，退出码 0。
目的是把 ``docs/scenario-inventory-2026-10-29.md`` 里 X2 的
``⚠️ 未自动重排`` 落成可复现的事实。

覆盖链路（清单 §X2 设备故障）：

    安灯报设备故障 → 设备转 fault → 工单暂停 → 停机时长记录 → 恢复 → 重排产

判据说明
--------
- 每条 ``[GAP]`` 都对应一个"业务上该发生但系统没做"的动作，不是"接口不存在"。
- 探测前先自证造数条件（设备/工单都存在），否则测出的"断点"是造数缺陷。
"""
import os
import sys
from datetime import date, datetime, timedelta, timezone

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

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


def first_id(payload):
    d = (payload or {}).get("data")
    if isinstance(d, dict):
        return d.get("id")
    return d


def _dt(value):
    """把接口返回的时间统一成 datetime —— SQLite 回来是字符串，PG 回来是对象。"""
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def main():
    c = httpx.Client(timeout=25)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print(f"\n{'=' * 64}\nX2 设备故障：安灯 → 停机 → 工单暂停 → 恢复 → 重排产\n{'=' * 64}")

    # ── A1 设备（按编码自举，重复跑不产生脏数据） ──
    eq_code = "E2E-EQ-FAULT"
    r = c.get(f"{API}/equipment", params={"page_size": 100})
    eq = next((x for x in items_of(r.json()) if x.get("equipment_code") == eq_code), None)
    if eq:
        eq_id = eq["id"]
        ok("A1 设备已存在（复用）", f"id={eq_id} code={eq_code} status={eq.get('status')}")
    else:
        r = c.post(f"{API}/equipment", json={
            "equipment_code": eq_code, "equipment_name": "E2E 故障测试设备",
            "location": "E2E 车间"})
        eq_id = first_id(r.json()) if r.status_code == 200 else None
        report("A1 建设备", bool(eq_id), f"id={eq_id} HTTP {r.status_code} {r.text[:100]}")
        if not eq_id:
            return 1

    # 确保起点是 running（否则下面"故障后转 fault"测不出变化）
    c.put(f"{API}/equipment/{eq_id}", json={"status": "running"})
    eq0 = (c.get(f"{API}/equipment/{eq_id}").json().get("data") or {})
    report("A1b 设备起点状态=running", eq0.get("status") == "running",
           f"status={eq0.get('status')}")

    # ── A2 工单（运行为 in_progress，才能测"是否被暂停"） ──
    wo_no = f"WO-EQ-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": "E2E-FG-001", "product_name": "E2E 成品",
        "planned_qty": 20, "wo_type": "production",
        "scheduled_start_at": datetime.now().isoformat(timespec="seconds"),
        "scheduled_end_at": (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds"),
        "remark": "探测脚本：设备故障链路"})
    wo_id = first_id(r.json()) if r.status_code == 200 else None
    report("A2 建工单", bool(wo_id), f"id={wo_id} HTTP {r.status_code} {r.text[:100]}")
    if not wo_id:
        return 1
    c.post(f"{API}/work-orders/{wo_id}/release", json={})
    c.post(f"{API}/work-orders/{wo_id}/start", json={})
    wo0 = (c.get(f"{API}/work-orders/{wo_id}").json().get("data") or {})
    report("A2b 工单起点状态=in_progress", wo0.get("wo_status") == "in_progress",
           f"wo_status={wo0.get('wo_status')}")
    end_before = wo0.get("scheduled_end_at")

    # ── A3 报安灯（设备故障，挂到该设备与该工单） ──
    r = c.post(f"{API}/andon/calls", json={
        "call_type": "equipment", "source": "manual",
        "equipment_id": eq_id, "work_order_id": wo_id,
        "station": "E2E-ST-01",
        "description": "探测脚本：主轴异响停机",
        "priority": "high"})
    call_id = first_id(r.json()) if r.status_code == 200 else None
    report("A3 报设备故障安灯", bool(call_id),
           f"id={call_id} HTTP {r.status_code} {r.text[:120]}")
    if not call_id:
        return 1
    call = (c.get(f"{API}/andon/calls/{call_id}").json().get("data") or {})
    print(f"  [INFO] 安灯: call_no={call.get('call_no')} type={call.get('call_type')} "
          f"eq={call.get('equipment_id')} wo={call.get('work_order_id')} "
          f"status={call.get('status')}")

    # ── A4 设备状态是否随故障自动转 fault ──
    eq1 = (c.get(f"{API}/equipment/{eq_id}").json().get("data") or {})
    report("A4 设备故障 → 设备状态自动转 fault", eq1.get("status") == "fault",
           f"status={eq1.get('status')}")

    # ── A5 工单是否随设备故障自动暂停 ──
    wo1 = (c.get(f"{API}/work-orders/{wo_id}").json().get("data") or {})
    report("A5 设备故障 → 关联工单自动暂停", wo1.get("wo_status") == "paused",
           f"wo_status={wo1.get('wo_status')}")

    # ── A6 停机记录：报障即开一条"未关闭"的停机 ──
    r = c.get(f"{API}/downtimes", params={"equipment_id": eq_id, "page_size": 20})
    dts = items_of(r.json()) if r.status_code == 200 else []
    open_dt = [x for x in dts if not x.get("ended_at")]
    report("A6 报障即开停机记录（未关闭）", bool(open_dt),
           f"downtimes 共 {len(dts)} 条，未关闭 {len(open_dt)} 条 "
           f"HTTP {r.status_code} {r.text[:100] if r.status_code != 200 else ''}")
    dt_id = None
    if open_dt:
        d0 = open_dt[0]
        dt_id = d0.get("id")
        print(f"  [INFO] 停机中: id={dt_id} started_at={d0.get('started_at')} "
              f"type={d0.get('downtime_type')} wo={d0.get('work_order_id')}")

    # ── A6b 把停机起点往前挪（模拟真实停机时长） ──
    # 脚本从报障到解决只隔零点几秒，算出的时长必然是 0 分钟 —— 那样
    # "重排产"这段等于没被测到。真实车间停机动辄几十分钟，所以这里用
    # 修正接口把 started_at 前移，让时长成为一个有意义的数。
    FAULT_MINUTES = 90
    backdated = None
    if dt_id:
        backdated = (datetime.now(timezone.utc)
                     - timedelta(minutes=FAULT_MINUTES)).isoformat()
        r = c.put(f"{API}/downtimes/{dt_id}", json={"started_at": backdated})
        report("A6b 停机起点可修正（补录/纠错）", r.status_code == 200,
               f"HTTP {r.status_code} started_at→{backdated[:19]} "
               f"{r.text[:100] if r.status_code != 200 else ''}")
        if r.status_code == 200:
            r2 = c.get(f"{API}/downtimes", params={"equipment_id": eq_id, "page_size": 20})
            now_dts = items_of(r2.json()) if r2.status_code == 200 else []
            cur = next((x for x in now_dts if x.get("id") == dt_id), {})
            got = _dt(cur.get("started_at")) if cur.get("started_at") else None
            report("A6c 修正后的起点已落库", bool(got) and
                   abs((_dt(backdated) - got).total_seconds()) < 120,
                   f"读回 started_at={cur.get('started_at')}")

    # ── A7 人工处置：确认 → 解决，看设备/工单是否恢复 ──
    r = c.put(f"{API}/andon/calls/{call_id}/action", json={"status": "acknowledged"})
    report("A7 安灯可确认", r.status_code == 200, f"HTTP {r.status_code}")
    r = c.put(f"{API}/andon/calls/{call_id}/action",
              json={"status": "resolved", "resolution": "更换主轴轴承"})
    report("A7b 安灯可解决", r.status_code == 200, f"HTTP {r.status_code}")

    eq2 = (c.get(f"{API}/equipment/{eq_id}").json().get("data") or {})
    # 前置依赖要显式挡住：A4 断的时候"A8 恢复"是假的 ——
    # 设备压根没进 fault，谈不上恢复。这种"看起来通"的断言比断更危险。
    if eq1.get("status") == "fault":
        report("A8 故障解决 → 设备状态自动恢复", eq2.get("status") == "running",
               f"status={eq2.get('status')}")
    else:
        gap("A8 故障解决 → 设备状态自动恢复",
            f"前置不成立：故障时设备没进 fault（见 A4，status={eq1.get('status')}）")

    wo2 = (c.get(f"{API}/work-orders/{wo_id}").json().get("data") or {})
    if wo1.get("wo_status") == "paused":
        report("A9 故障解决 → 工单自动恢复", wo2.get("wo_status") == "in_progress",
               f"wo_status={wo2.get('wo_status')}")
    else:
        gap("A9 故障解决 → 工单自动恢复",
            f"前置不成立：故障时工单没被暂停（见 A5，wo_status={wo1.get('wo_status')}）")

    # ── A10 停机记录已关闭且算出时长 ──
    r = c.get(f"{API}/downtimes", params={"equipment_id": eq_id, "page_size": 20})
    dts2 = items_of(r.json()) if r.status_code == 200 else []
    closed = [x for x in dts2 if x.get("ended_at")]
    # ★必须按 id 取"本次关闭的这一条"，不能取 closed[0]：列表按 started_at DESC
    #   排序，而 A6b 刚把这条的起点往前挪了 90 分钟 —— 它反而排到**最后**，
    #   closed[0] 读的是历史上另一条已关闭记录（时长 0.01），
    #   于是服务端明明落库了 90 分钟（A11 顺延 90 也印证了），却被判成缺陷。
    cur_closed = next((x for x in closed if x.get("id") == dt_id), None)
    if cur_closed is None and closed:
        cur_closed = max(closed, key=lambda x: x.get("id") or 0)
    dur = (cur_closed.get("duration_minutes") if cur_closed else None)
    report("A10 解决后停机记录关闭并算出时长", bool(closed) and dur is not None,
           f"closed={len(closed)} duration_minutes={dur}")
    # 时长要和构造出来的 90 分钟对得上 —— 只判"非 None"会让 0 分钟的假时长蒙混过关
    report("A10b 时长与构造的停机时长一致",
           dur is not None and abs(float(dur) - FAULT_MINUTES) <= 2,
           f"duration_minutes={dur} 期望≈{FAULT_MINUTES}")

    # ── A11 重排产：计划完工是否按停机时长顺延 ──
    # 时间必须按 datetime 比，不能比字符串：'2026-11-01 09:29:04' 与
    # '2026-11-01 09:29:04.101083+00:00' 字符串序能过，但换个格式就翻车。
    end_after = wo2.get("scheduled_end_at")
    moved, delta_min = False, None
    try:
        if end_before and end_after:
            delta_min = (_dt(end_after) - _dt(end_before)).total_seconds() / 60.0
            moved = delta_min > 0
    except Exception:  # noqa: BLE001
        moved = False
    report("A11 停机后自动重排产（计划完工顺延）", moved,
           f"scheduled_end_at {end_before} → {end_after}"
           + (f"（顺延 {delta_min:.1f} 分钟）" if moved else "（未顺延）"))
    # 顺延量要等于停机时长，不是"动了一下就算过"
    report("A11b 顺延量等于停机时长",
           moved and delta_min is not None and abs(delta_min - FAULT_MINUTES) <= 2,
           f"顺延 {delta_min if delta_min is None else round(delta_min, 1)} 分钟 "
           f"期望≈{FAULT_MINUTES}")

    # ── 汇总 ──
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
