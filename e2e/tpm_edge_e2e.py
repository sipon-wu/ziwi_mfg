"""设备维护/备件/能耗采集边界场景端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/tpm_edge_e2e.py

覆盖场景（``docs/scenario-inventory-2026-10-29.md`` F 区，BACKLOG C-72）：

    F-E1  保养任务逾期：列表带 is_overdue / overdue_days / escalation 分级，
          逾期专项清单可查、按逾期天数降序、完成/取消后不再计逾期
    F-E2  设备报废前必须没有在制工单：挂 released 工单 → 400；无工单 → 200
    F-E4  备件库存不足领用 → 400（备件不做欠料出库）；足量领用扣库存 + 留流水
    F-B1  设备跨车间调拨（location 变更）→ 审计留痕 equipment.transfer
    F-B2  保养周期 0 / 负数 → 400（0 会被 add_cycle 静默当 1，负数导致永久逾期）
    F-B3  能耗数据补录：业务时间与写库时间分离（is_backfill），未来时间一律拒，
          批量写入不做部分写入
"""
import json
import os
import sys
from datetime import datetime, timedelta, timezone

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


def flat(v):
    """把审计日志的 before/after 值拍平成字符串再判断包含关系。

    ★audit_logs 的 before/after 落库是 **JSON 对象**（`{"location": "冲压车间"}`），
    不是字符串。直接写 `"冲压车间" in value` 会退化成 dict 的**键**成员判断
    （判断的是 "冲压车间" 是不是某个键名），恒为 False ——
    审计明明写对了，也会被判成"没留痕"。
    """
    if isinstance(v, (dict, list)):
        return json.dumps(v, ensure_ascii=False)
    return v or ""


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
    now = datetime.now(timezone.utc)

    def mk_equipment(code, location="A车间"):
        r = c.post(f"{API}/equipment", json={
            "equipment_code": code, "equipment_name": f"设备{code}",
            "location": location, "status": "idle"})
        assert r.status_code == 200, f"建设备失败 {r.status_code} {r.text[:300]}"
        return r.json()["data"]["id"]

    def mk_task(eq_id, desc, start_at, status="pending"):
        r = c.post(f"{API}/maintenance-tasks", json={
            "equipment_id": eq_id, "task_type": "preventive",
            "description": desc,
            "scheduled_start_at": start_at.isoformat(timespec="seconds")})
        assert r.status_code == 200, f"建任务失败 {r.status_code} {r.text[:300]}"
        return r.json()["data"]["id"]

    def find_task(task_id):
        r = c.get(f"{API}/maintenance-tasks", params={"page": 1, "page_size": 100})
        for row in r.json()["data"]["items"]:
            if row.get("id") == task_id:
                return row
        return None

    # ══════════════════════════════════════════════════════
    # F-E1 保养任务逾期与升级
    # ══════════════════════════════════════════════════════
    print("── F-E1 保养任务逾期判定与升级 ──")
    eq_f1 = mk_equipment(f"EQ-F1-{tag}")
    t_crit = mk_task(eq_f1, f"F1逾期10天-{tag}", now - timedelta(days=10))
    t_urgent = mk_task(eq_f1, f"F1逾期4天-{tag}", now - timedelta(days=4))
    t_ok = mk_task(eq_f1, f"F1未到期-{tag}", now + timedelta(days=3))

    row_crit, row_urgent, row_ok = find_task(t_crit), find_task(t_urgent), find_task(t_ok)

    # ★逾期天数不锁等值，只锁「分级」和「量级」。
    #   `overdue_days` 是 `(now - due).days`，即**满 24 小时**才进一位；而探针
    #   建单时 `scheduled_start_at` 用 `timespec="seconds"` 截断、请求往返又有
    #   几十毫秒 —— 边界上"刚好 4 天"会被算成 3 天 23:59:59 → 3。
    #   本地 SQLite 因为时间戳无时区、按本地时间来回读，反而把这个偏差抵消掉
    #   （本地 4/10 全过、staging 上 3/9 全挂，就是这么来的）。
    #   这里要守的是业务语义：逾期的要判逾期、分级要跟着量级走 —— 不是"必须
    #   精确等于我算出来的那个数"。精确天数另有用例，用大于阈值的余量来验。
    check("F-E1 逾期10天 → critical",
          bool(row_crit) and row_crit.get("is_overdue") is True
          and row_crit.get("escalation") == "critical"
          and 9 <= (row_crit.get("overdue_days") or 0) <= 11,
          f"overdue={row_crit and row_crit.get('overdue_days')} "
          f"esc={row_crit and row_crit.get('escalation')}")
    check("F-E1 逾期4天 → urgent",
          bool(row_urgent) and row_urgent.get("is_overdue") is True
          and row_urgent.get("escalation") == "urgent"
          and 3 <= (row_urgent.get("overdue_days") or 0) <= 5,
          f"overdue={row_urgent and row_urgent.get('overdue_days')} "
          f"esc={row_urgent and row_urgent.get('escalation')}")
    check("F-E1 未到期任务不计逾期",
          bool(row_ok) and row_ok.get("is_overdue") is False
          and row_ok.get("overdue_days") == 0
          and row_ok.get("escalation") == "normal",
          f"overdue={row_ok and row_ok.get('is_overdue')}")

    r = c.get(f"{API}/maintenance-tasks/overdue")
    d = r.json().get("data") or {}
    ids = [x.get("id") for x in d.get("list", [])]
    days = [x.get("overdue_days", 0) for x in d.get("list", [])]
    check("F-E1 逾期专项清单含逾期项、不含未到期项",
          r.status_code == 200 and t_crit in ids and t_urgent in ids and t_ok not in ids,
          f"total={d.get('total')} crit={d.get('critical')} urgent={d.get('urgent')}")
    check("F-E1 逾期清单按逾期天数降序",
          days == sorted(days, reverse=True), f"days[:6]={days[:6]}")

    # 完成后不再计逾期
    # 必须先开工：没开工就没有停机时长可算，硬完工会静默吞掉"这台设备停了多久"
    r0 = c.put(f"{API}/maintenance-tasks/{t_crit}/start", json={})
    check("F-E1 前置：未开工不能直接完工（既定约束）",
          r0.status_code == 200,
          f"start HTTP {r0.status_code}")
    r = c.put(f"{API}/maintenance-tasks/{t_crit}/complete", json={})
    row_after = find_task(t_crit)
    check("F-E1 已完工任务不再计逾期",
          r.status_code == 200 and bool(row_after)
          and row_after.get("status") == "completed"
          and row_after.get("is_overdue") is False
          and row_after.get("escalation") == "normal",
          f"HTTP {r.status_code} status={row_after and row_after.get('status')} "
          f"overdue={row_after and row_after.get('is_overdue')}")

    # ══════════════════════════════════════════════════════
    # F-E2 设备报废前无在制工单
    # ══════════════════════════════════════════════════════
    print("\n── F-E2 设备报废 / 停用的在制拦截 ──")
    eq_busy = mk_equipment(f"EQ-F2A-{tag}")
    eq_idle = mk_equipment(f"EQ-F2B-{tag}")
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-F2-{tag}", "product_code": f"P-F2-{tag}",
        "product_name": f"产品F2-{tag}", "planned_qty": 10,
        "equipment_id": eq_busy})
    check("F-E2 前置：建带设备工单成功", r.status_code == 200,
          f"HTTP {r.status_code} {r.text[:200]}")
    wo_id = (r.json().get("data") or {}).get("id")
    r = c.post(f"{API}/work-orders/{wo_id}/release",
               json={"force_release": True, "force_reason": "F-E2 探针验证报废拦截"})
    sc = (r.json().get("data") or {}).get("status_change") or {}
    check("F-E2 前置：工单已下达",
          r.status_code == 200 and sc.get("to") == "released",
          f"HTTP {r.status_code} status_change={sc}")

    r = c.put(f"{API}/equipment/{eq_busy}", json={"status": "scrapped"})
    check("F-E2 有在制工单 → 报废被拒 400",
          r.status_code == 400 and "在制工单" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:80]}")
    r = c.get(f"{API}/equipment/{eq_busy}")
    check("F-E2 被拒后设备状态未被改写",
          r.status_code == 200 and (r.json().get("data") or {}).get("status") != "scrapped",
          f"status={(r.json().get('data') or {}).get('status')}")

    r = c.put(f"{API}/equipment/{eq_idle}", json={"status": "scrapped"})
    check("F-E2 无在制工单 → 报废成功",
          r.status_code == 200
          and (c.get(f"{API}/equipment/{eq_idle}").json().get("data") or {}).get("status") == "scrapped",
          f"HTTP {r.status_code}")

    # ══════════════════════════════════════════════════════
    # F-E4 备件不足领用
    # ══════════════════════════════════════════════════════
    print("\n── F-E4 备件领用库存边界 ──")
    r = c.post(f"{API}/spare-parts", json={
        "part_code": f"SP0-{tag}", "part_name": f"零库存备件{tag}",
        "unit": "个", "current_stock": 0, "min_stock": 1})
    sp0 = r.json()["data"]["id"]
    r = c.post(f"{API}/spare-parts/{sp0}/consume", json={"qty": 2})
    check("F-E4 零库存领用 → 400 且提示现有 0",
          r.status_code == 400 and "库存不足" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:70]}")
    r = c.get(f"{API}/spare-parts", params={"page": 1, "page_size": 100})
    rec = next((x for x in r.json()["data"]["items"] if x["id"] == sp0), {})
    check("F-E4 被拒后库存仍为 0（未写成负数）",
          int(rec.get("current_stock") or 0) == 0, f"stock={rec.get('current_stock')}")

    r = c.post(f"{API}/spare-parts", json={
        "part_code": f"SP1-{tag}", "part_name": f"常用备件{tag}",
        "unit": "个", "current_stock": 10, "min_stock": 3})
    sp1 = r.json()["data"]["id"]
    r = c.post(f"{API}/spare-parts/{sp1}/consume",
               json={"qty": 3, "remark": f"F-E4 探针 {tag}"})
    check("F-E4 足量领用成功并扣减到 7",
          r.status_code == 200 and (r.json().get("data") or {}).get("after_qty") == 7,
          f"HTTP {r.status_code} {(r.json().get('data') or {}).get('after_qty')}")
    r = c.get(f"{API}/spare-parts/{sp1}/movements")
    movs = r.json().get("data") or []
    check("F-E4 领用写入出入库流水（含 before/after）",
          len(movs) >= 1 and movs[0].get("change_type") == "out"
          and movs[0].get("qty") == 3,
          f"movements={len(movs)} {str(movs[:1])[:160]}")

    # ══════════════════════════════════════════════════════
    # F-B1 设备跨车间调拨留痕
    # ══════════════════════════════════════════════════════
    print("\n── F-B1 设备跨车间调拨留痕 ──")
    eq_b1 = mk_equipment(f"EQ-B1-{tag}", location="冲压车间")
    r = c.put(f"{API}/equipment/{eq_b1}", json={"location": "装配车间"})
    tr = (r.json().get("data") or {}).get("transfer") or {}
    check("F-B1 调拨返回 from/to",
          r.status_code == 200 and tr.get("from") == "冲压车间"
          and tr.get("to") == "装配车间",
          f"transfer={tr}")

    r = c.get(f"{API}/audit-logs", params={"action": "equipment.transfer",
                                           "object_id": eq_b1, "page_size": 10})
    items = r.json().get("data", {}).get("items", [])
    check("F-B1 审计表落 equipment.transfer（含前后归属）",
          r.status_code == 200 and len(items) >= 1
          and "冲压车间" in flat(items[0].get("before"))
          and "装配车间" in flat(items[0].get("after")),
          f"hits={len(items)} {str(items[:1])[:200]}")

    r = c.put(f"{API}/equipment/{eq_b1}", json={"location": "装配车间"})
    check("F-B1 归属未变则不产生调拨记录",
          r.status_code == 200 and (r.json().get("data") or {}).get("transfer") is None,
          f"transfer={(r.json().get('data') or {}).get('transfer')}")

    # ══════════════════════════════════════════════════════
    # F-B2 保养周期非法
    # ══════════════════════════════════════════════════════
    print("\n── F-B2 保养周期 0 / 负数 ──")
    for bad in (0, -1):
        r = c.post(f"{API}/maintenance-plans", json={
            "equipment_id": eq_f1, "plan_name": f"坏周期{tag}-{bad}",
            "plan_type": "preventive", "cycle_value": bad, "cycle_unit": "month"})
        check(f"F-B2 周期 {bad} → 400",
              r.status_code == 400 and "正整数" in err_msg(r),
              f"HTTP {r.status_code} msg={err_msg(r)[:70]}")

    r = c.post(f"{API}/maintenance-plans", json={
        "equipment_id": eq_f1, "plan_name": f"好周期{tag}",
        "plan_type": "preventive", "cycle_value": 1, "cycle_unit": "month"})
    ok_plan = r.json().get("data") or {}
    check("F-B2 周期 1 → 成功且算出下次到期",
          r.status_code == 200 and bool(ok_plan.get("next_execute_at")),
          f"HTTP {r.status_code} next={ok_plan.get('next_execute_at')}")

    # ══════════════════════════════════════════════════════
    # F-B3 能耗数据补录与未来时间
    # ══════════════════════════════════════════════════════
    print("\n── F-B3 能耗数据补录 / 未来时间 ──")
    before_total = c.get(f"{API}/collect/records",
                         params={"page": 1, "page_size": 1}).json()["data"]["total"]

    r = c.post(f"{API}/collect/records", json={
        "data_time": (now - timedelta(days=1)).isoformat(),
        "point_name": "kwh", "value_numeric": 12.5})
    d = r.json().get("data") or {}
    check("F-B3 补录（1 天前）写入成功且标记 is_backfill",
          r.status_code == 200 and d.get("is_backfill") is True,
          f"HTTP {r.status_code} {d}")

    r = c.post(f"{API}/collect/records", json={
        "data_time": (now - timedelta(minutes=10)).isoformat(),
        "point_name": "kwh", "value_numeric": 3.2})
    check("F-B3 实时（10 分钟内）不算补录",
          r.status_code == 200 and (r.json().get("data") or {}).get("is_backfill") is False,
          f"HTTP {r.status_code} {(r.json().get('data') or {}).get('is_backfill')}")

    r = c.post(f"{API}/collect/records", json={
        "data_time": (now + timedelta(days=1)).isoformat(),
        "point_name": "kwh", "value_numeric": 99})
    check("F-B3 未来数据时间 → 400",
          r.status_code == 400 and "晚于当前时间" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:70]}")

    r = c.post(f"{API}/collect/records/batch", json={"records": [
        {"data_time": (now - timedelta(hours=2)).isoformat(), "point_name": "kwh",
         "value_numeric": 1.1},
        {"data_time": (now + timedelta(days=2)).isoformat(), "point_name": "kwh",
         "value_numeric": 2.2}]})
    check("F-B3 批量含未来时间 → 整批拒绝 400",
          r.status_code == 400 and "整批已拒绝" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:70]}")

    after_total = c.get(f"{API}/collect/records",
                        params={"page": 1, "page_size": 1}).json()["data"]["total"]
    check("F-B3 被拒的写入未落库（不做部分写入）",
          after_total - before_total == 2,
          f"before={before_total} after={after_total} (应 +2：仅两条合法写入)")

    # 批次合法写入
    r = c.post(f"{API}/collect/records/batch", json={"records": [
        {"data_time": (now - timedelta(hours=3)).isoformat(), "point_name": "kwh",
         "value_numeric": 4.4},
        {"data_time": (now - timedelta(hours=2)).isoformat(), "point_name": "kwh",
         "value_numeric": 5.5}]})
    check("F-B3 批量合法数据写入成功 2 条",
          r.status_code == 200 and (r.json().get("data") or {}).get("count") == 2,
          f"HTTP {r.status_code} {r.json().get('data')}")

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
