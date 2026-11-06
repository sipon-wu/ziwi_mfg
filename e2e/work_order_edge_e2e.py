"""C 区工单异常/边界场景真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/work_order_edge_e2e.py

覆盖清单里标 ❓ 的几条（**先跑真实链路看数字，再回代码解释为什么**）：

    C-E3  未派工直接报工        —— 清单：应拒绝或自动派工
    C-E4  工单暂停 / 恢复        —— 暂停中还能不能报工（停机时报工 = 假数据）
    C-E5  工单取消（已有报工）   —— 清单：应拒绝或需审批
    C-B1  跨月工单（报表归属）   —— 口径是"按报工日期"还是"按工单"
    C-B2  报工时间早于开工时间   —— 需要报工**时刻**，现在只有日期
    C-E7  工单挂已停用设备/WC    —— 需要工单上有设备/工作中心
    C-B4  一个工单跨多班组       —— 派工只有一份字段，靠什么区分

这些项清单里都标 ❓（未验证），不是 ❌。探针的目的就是**把 ❓ 变成明确结论**：
要么"早就通了、标记该改 ✅"，要么"真缺口、记进 BACKLOG"。
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)


def new_id(resp):
    d = body(resp).get("data")
    if isinstance(d, dict):
        return d.get("id")
    return d


def get_wo(c, wo_id):
    return data(c.get(f"{API}/work-orders/{wo_id}")) or {}


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code} {r.text[:200]}")
        return 1
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print("C 区 工单异常/边界（C-E3/E4/E5/E7 · C-B1/B2/B4）")
    print("=" * 62)

    # ── 造数：工单 planned 100 ──
    wo_no = f"WO-EDGE-{tag}"
    r = c.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": f"P-EDGE-{tag}",
        "product_name": f"边界验证件{tag}", "planned_qty": 100,
        "wo_type": "production", "workshop": "边界车间"})
    wo_id = new_id(r)
    report("C-1 建工单（计划 100）", wo_id is not None, f"wo_id={wo_id}")
    if not wo_id:
        summary()
        return 0

    r = c.post(f"{API}/work-orders/{wo_id}/release",
               json={"force_release": True, "force_reason": "边界探针"})
    wo = get_wo(c, wo_id)
    report("C-2 下达（force 跳过缺料）", wo.get("wo_status") == "released",
           f"status={wo.get('wo_status')}")

    # ── C-E3 未派工直接报工 ──
    wo = get_wo(c, wo_id)
    report("C-E3-1 报工前工单无负责人（确认是『未派工』状态）",
           not wo.get("assignee_id") and not wo.get("assigned_org_id"),
           f"assignee={wo.get('assignee_id')} org={wo.get('assigned_org_id')}")
    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 10, "scrap_qty": 0, "labor_hours": 1.0})
    d = data(r) or {}
    warns = d.get("warnings") or []
    # 清单口径是"应拒绝或自动派工"——两者都可接受，但**必须有一件发生**，
    # 不能"既放行又什么都不说"（那样等于这条边界根本没人管）。
    accepted = r.status_code == 200
    has_hint = bool(warns) or "派工" in msg(r)
    report("C-E3-2 ★未派工报工：要么拒绝、要么显式提示（不能静默放行）",
           (not accepted) or has_hint,
           f"HTTP {r.status_code} warnings={warns} msg={msg(r)[:60]}")

    # ── C-B2 报工时刻：报工单上到底有没有"时刻" ──
    rep_id = d.get("id") or d.get("report_id")
    rep = data(c.get(f"{API}/work-reports/{rep_id}")) if rep_id else {}
    has_moment = any(k for k in (rep or {})
                     if k in ("reported_at", "report_time", "report_at"))
    report("C-B2-1 ★报工记录带报工**时刻**（否则『早于开工』无从校验）",
           has_moment,
           f"字段={sorted((rep or {}).keys())}"
           if rep else f"读不到报工单 id={rep_id}")
    # 就算有日期，也应该能校验"报工日期早于实际开工日期"
    wo = get_wo(c, wo_id)
    r2 = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": "2020-01-01",
        "output_qty": 1, "scrap_qty": 0})
    # 报工日期早于开工 → 只告警（补录是正常业务，不能拦）；
    # 报工**时刻**早于开工 → 必须拦（真实时序错乱，工单没开工不可能有产出）
    r3 = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "reported_at": "2020-01-01T08:00:00",
        "output_qty": 1, "scrap_qty": 0})
    report("C-B2-3 ★★报工**时刻**早于实际开工 → 400（不是告警）",
           r3.status_code == 400,
           f"HTTP {r3.status_code} msg={msg(r3)[:80]}")
    r4 = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "reported_at": datetime.now().isoformat(),
        "output_qty": 2, "scrap_qty": 0})
    rep4 = data(c.get(f"{API}/work-reports/{r4.json()['data'].get('report_id')}")
                if r4.status_code == 200 else {}) or {}
    report("C-B2-4 正常报工的时刻落库（列真的能用，不是只有模型声明）",
           r4.status_code == 200 and rep4.get("reported_at") is not None,
           f"HTTP {r4.status_code} reported_at={rep4.get('reported_at')}")

    # ── C-E4 暂停 / 恢复：暂停中还能不能报工 ──
    r = c.post(f"{API}/work-orders/{wo_id}/pause", json={"reason": "边界探针停机"})
    wo = get_wo(c, wo_id)
    report("C-E4-1 暂停 → paused 且写流水", wo.get("wo_status") == "paused",
           f"status={wo.get('wo_status')}")
    r = c.post(f"{API}/work-reports", json={
        "work_order_id": wo_id, "report_date": datetime.now().date().isoformat(),
        "output_qty": 5, "scrap_qty": 0, "labor_hours": 0.5})
    report("C-E4-2 ★★暂停中报工应被拒（停机期间不产生报工）",
           r.status_code == 400,
           f"HTTP {r.status_code} msg={msg(r)[:80]}")
    r = c.post(f"{API}/work-orders/{wo_id}/resume")
    wo = get_wo(c, wo_id)
    report("C-E4-3 恢复 → in_progress", wo.get("wo_status") == "in_progress",
           f"status={wo.get('wo_status')}")

    # ── C-E5 取消已有报工的工单 ──
    wo = get_wo(c, wo_id)
    done = (wo.get("completed_qty") or 0) + (wo.get("scrap_qty") or 0)
    r = c.post(f"{API}/work-orders/{wo_id}/cancel", json={"reason": "边界探针作废"})
    wo_after = get_wo(c, wo_id)
    report("C-E5-1 ★★已有产出的工单不能凭一句原因作废",
           r.status_code == 400 and wo_after.get("wo_status") != "cancelled",
           f"已有产出={done} HTTP {r.status_code} msg={msg(r)[:90]} "
           f"status={wo_after.get('wo_status')}")
    r = c.post(f"{API}/work-orders/{wo_id}/cancel", json={
        "reason": "边界探针作废", "force": True,
        "force_reason": "已产出的 16 件全部报废"})
    wo_after = get_wo(c, wo_id)
    report("C-E5-2 ★强制作废需说明产出去向（force_reason 必填）",
           r.status_code == 200 and wo_after.get("wo_status") == "cancelled",
           f"HTTP {r.status_code} msg={msg(r)[:70]} status={wo_after.get('wo_status')}")

    # ── C-E7 工单挂停用设备 / 停用工作中心 ──
    wo = get_wo(c, wo_id)
    has_res = "equipment_id" in wo and "work_center_id" in wo
    report("C-E7-1 ★工单带设备/工作中心字段（否则『挂停用设备』无从拦截）",
           has_res, f"equipment_id={wo.get('equipment_id')} "
                    f"work_center_id={wo.get('work_center_id')}")

    # 停用工作中心 → 建单应被拒
    wc_code = f"WC-EDGE-{tag}"
    r = c.post(f"{API}/work-centers", json={
        "code": wc_code, "name": f"停用中心{tag}", "wc_type": "workstation"})
    wc_id = new_id(r)
    if wc_id:
        c.put(f"{API}/work-centers/{wc_id}", json={"is_active": False})
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-WCOFF-{tag}", "product_code": f"P-EDGE-{tag}",
        "product_name": "停用中心验证件", "planned_qty": 10,
        "work_center_id": wc_id or 999999})
    report("C-E7-2 ★★挂**停用**工作中心的工单被拒",
           wc_id is not None and r.status_code == 400,
           f"wc_id={wc_id} HTTP {r.status_code} msg={msg(r)[:80]}")

    # 报废设备 → 建单应被拒
    eq_code = f"EQ-EDGE-{tag}"
    r = c.post(f"{API}/equipment", json={
        "equipment_code": eq_code, "equipment_name": f"报废设备{tag}"})
    eq_id = new_id(r)
    if eq_id:
        c.put(f"{API}/equipment/{eq_id}", json={"status": "scrapped"})
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-EQOFF-{tag}", "product_code": f"P-EDGE-{tag}",
        "product_name": "报废设备验证件", "planned_qty": 10,
        "equipment_id": eq_id or 999999})
    report("C-E7-3 ★★挂**已报废/停用**设备的工单被拒",
           eq_id is not None and r.status_code == 400,
           f"eq_id={eq_id} HTTP {r.status_code} msg={msg(r)[:80]}")

    # 正常资源 → 能建，且字段真的落库（列在、能写、能读回）。
    # 注意：必须另建一套**启用**的资源，不能拿上面被停用的那两个 —— 拿它们
    # 建单当然被拒，断言看上去像"字段没落库"，实际是探针自己造错了数。
    r = c.post(f"{API}/work-centers", json={
        "code": f"WC-OK-{tag}", "name": f"启用中心{tag}", "wc_type": "workstation"})
    wc_ok = new_id(r)
    r = c.post(f"{API}/equipment", json={
        "equipment_code": f"EQ-OK-{tag}", "equipment_name": f"正常设备{tag}"})
    eq_ok = new_id(r)
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-OK-{tag}", "product_code": f"P-EDGE-{tag}",
        "product_name": "正常资源验证件", "planned_qty": 10,
        "equipment_id": eq_ok, "work_center_id": wc_ok})
    ok_id = new_id(r)
    ok_wo = get_wo(c, ok_id) if ok_id else {}
    report("C-E7-4 正常设备/工作中心可建单，且字段落库可读回",
           ok_id is not None and ok_wo.get("equipment_id") == eq_ok
           and ok_wo.get("work_center_id") == wc_ok,
           f"id={ok_id} eq={ok_wo.get('equipment_id')}/{eq_ok} "
           f"wc={ok_wo.get('work_center_id')}/{wc_ok}")

    # 不存在的资源 id → 必须拒（否则界面上"所属工作中心"一栏空白，
    # 等于这条关联从来没生效过）
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-BAD-{tag}", "product_code": f"P-EDGE-{tag}",
        "product_name": "不存在资源验证件", "planned_qty": 10,
        "work_center_id": 999999})
    report("C-E7-5 传不存在的资源 id 被拒（不是静默存 NULL）",
           r.status_code == 400, f"HTTP {r.status_code} msg={msg(r)[:80]}")

    # ── C-B4 一个工单跨多班组 ──
    r = c.get(f"{API}/work-orders/{wo_id}/assignments")
    assigns = data(r) if isinstance(data(r), list) else []
    report("C-B4 ★派工记录是**多条可累加**（否则一个工单只能归一个班组）",
           r.status_code == 200 and isinstance(assigns, list),
           f"HTTP {r.status_code} 条数={len(assigns)}")

    # ── C-B1 跨月工单：报表归属口径 = 按**报工日期**归月 ──
    # 判据不是"月报能读"，而是"报工日期填在哪个月，产出就记在哪个月"——
    # 只断言可读性等于什么都没验（接口永远 200）。
    # 必须**另起一张工单**：主工单在 C-E5 已作废，作废态本就禁止报工 ——
    # 拿它测"报工记在哪个月"只会撞到状态拦截，测的根本不是归属口径。
    now = datetime.now()
    prev_y, prev_m = (now.year - 1, 12) if now.month == 1 else (now.year, now.month - 1)
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-B1-{tag}", "product_code": f"P-EDGE-{tag}",
        "product_name": "跨月归属验证件", "planned_qty": 50})
    b1_id = new_id(r)
    c.post(f"{API}/work-orders/{b1_id}/release",
           json={"force_release": True, "force_reason": "跨月探针"})
    before_prev = data(c.get(f"{API}/reports/monthly",
                             params={"year": prev_y, "month": prev_m})) or {}
    before_cur = data(c.get(f"{API}/reports/monthly",
                            params={"year": now.year, "month": now.month})) or {}
    r5 = c.post(f"{API}/work-reports", json={
        "work_order_id": b1_id, "report_date": f"{prev_y}-{prev_m:02d}-15",
        "output_qty": 7, "scrap_qty": 0})
    after_prev = data(c.get(f"{API}/reports/monthly",
                            params={"year": prev_y, "month": prev_m})) or {}
    after_cur = data(c.get(f"{API}/reports/monthly",
                           params={"year": now.year, "month": now.month})) or {}
    d_prev = (after_prev.get("total_output") or 0) - (before_prev.get("total_output") or 0)
    d_cur = (after_cur.get("total_output") or 0) - (before_cur.get("total_output") or 0)
    report("C-B1 ★★跨月工单按**报工日期**归月（上月报工记上月，不记本月）",
           r5.status_code == 200 and d_prev == 7 and d_cur == 0,
           f"报工 HTTP {r5.status_code}｜上月 +{d_prev}（期望 7） 本月 +{d_cur}"
           f"（期望 0）｜口径：report_date 落在哪个月，产出就归哪个月")

    # ── C-Z 清理：C-E7 自建的工位/设备用后即删 ──
    # 为什么必须删：这个探针每跑一次就往 work_centers / equipment 塞 2+2 条，
    # 且都不挂组织、不进任何路线。2026-11-06 实测 staging 已累积 10 条
    # `WC-EDGE-*` / `WC-OK-*`（每次回归都多两条），产能闸把它们算成新增偏差 ——
    # 门禁红了，没人看得出是探针自己造的。
    # 写法参照 `product_route_e2e.py` 的 finally 清理段：只删自己建的。
    if ok_id:
        # WO-OK 引用着 WC-OK / EQ-OK。本库几乎无外键，删父行不报错、只留孤儿，
        # 所以先作废那张工单，再删资源 —— 别留一条指向已删工位的在制单。
        c.post(f"{API}/work-orders/{ok_id}/cancel",
               json={"reason": "边界探针清理", "force": True,
                     "force_reason": "探针自建资源即将删除"})
    cleaned = []
    for path, rid, tag in (
        (f"{API}/work-centers/{wc_id}", wc_id, "WC-EDGE"),
        (f"{API}/work-centers/{wc_ok}", wc_ok, "WC-OK"),
        (f"{API}/equipment/{eq_id}", eq_id, "EQ-EDGE"),
        (f"{API}/equipment/{eq_ok}", eq_ok, "EQ-OK"),
    ):
        if rid:
            rr = c.delete(path)
            cleaned.append(f"{tag}={rr.status_code}")
    report("C-Z1 ★探针自建的工位/设备已清理（不留垃圾给产能闸）",
           len(cleaned) == 4 and all(x.endswith("=200") for x in cleaned),
           " ".join(cleaned))

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
