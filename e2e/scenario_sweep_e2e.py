"""场景清单 ⚠️ 项复核探针（真实 HTTP）——A-S2 / F-S7 / G-S4。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/scenario_sweep_e2e.py

为什么要有这个脚本
------------------
``docs/scenario-inventory-2026-10-29.md`` 里挂着 26 个 ⚠️，但**清单本身会撒谎**
（台账 C-49：X4 标 ❌ 而实跑 45/0 全绿，断的只是"最后一跳没人验"）。反过来也
一样：有些 ⚠️ 其实早就修好了，只是没人回来改标记。

用 OpenAPI 事实底座先筛一遍后发现 A-S2 / F-S7 / G-S4 三项的端点**都在**，
怀疑是"已修未更新"。本脚本逐项自证，不靠推断：

- **A-S2 组织树搭建**（标注"缺部门主数据"）：`/organizations` 全量 CRUD +
  `tree` + `members` + `move` 都在。验：能不能真建出 部门/班组、层级白名单
  会不会拦住"把班组挂到班组下"、移动会不会造成环。
- **F-S7 碳排放核算**：`/energy/carbon/accounting` 在。但"接口 200"不等于
  "口径对" —— 这里做一次**交叉校验**：核算接口返回的按能源类型明细，必须与
  自己从 `/carbon/emissions` 明细逐行加总的结果一致。对不上就是静默读错。
- **G-S4 实验委托 → 报告 → 审批**：14 个 lab 端点齐全。验整条链能不能真的
  走到"报告已发布"（原标注是"报告未发布 404"）。

输出 [OK]/[GAP]，退出码恒 0 —— 这是**探测**，不是断言。
"""
import os
from datetime import datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")
USER = os.environ.get("E2E_USER", "mfg_admin")
PWD = os.environ.get("E2E_PWD", "admin123")

OK, GAP = [], []
BOUNDARY = []


def ok(name, detail=""):
    OK.append(name)
    print(f"  [OK ] {name}" + (f" · {detail}" if detail else ""))


def gap(name, detail=""):
    GAP.append(name)
    print(f"  [GAP] {name}" + (f" · {detail}" if detail else ""))


def boundary(name, reason=""):
    """标记为「边界外」——不是缺陷，是本平台按产品边界**不做**的东西。

    ★为什么需要单独一个出口而不是并入 ok()：并入 ok 会让"缺一个功能"看起来
    像"已具备"，报表上永远绿；并入 gap 又会让闸长期挂红，最后没人看。
    边界外就该被**显式地、带理由地**标出来，既不假装完成也不假装是缺陷。
    """
    BOUNDARY.append(name)
    print(f"  [OUT] {name}" + (f" · {reason}" if reason else ""))


def report(name, is_ok, detail=""):
    (ok if is_ok else gap)(name, detail)
    return is_ok


def body(r):
    try:
        return r.json()
    except Exception:
        return {}


def data(r):
    return body(r).get("data") or {}


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
    c.headers.update({"Authorization": f"Bearer {body(r)['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")
    print("=" * 62)
    print("⚠️ 项复核：A-S2 组织树 / F-S7 碳核算 / G-S4 实验室报告")
    print("=" * 62)

    # ══════════════ A-S2 组织树搭建 ══════════════
    print("\n── A-S2 组织树搭建（原标注：缺部门主数据）──")
    r = c.get(f"{API}/organizations/tree")
    tree = data(r)
    nodes = tree if isinstance(tree, list) else (tree.get("tree") or [])
    report("A-S2-1 组织树可读且有层级", r.status_code == 200 and bool(nodes),
           f"根节点 {len(nodes)} 个")

    # 找一个车间作为父节点
    flat = []

    def walk(ns, depth=0):
        for n in ns or []:
            n["_depth"] = depth
            flat.append(n)
            walk(n.get("children"), depth + 1)
    walk(nodes)
    workshop = next((n for n in flat if (n.get("org_type") or "") == "workshop"), None)
    parent = workshop or (flat[0] if flat else None)

    dept_id = None
    if parent:
        r = c.post(f"{API}/organizations", json={
            "code": f"DEPT-{tag}", "name": f"复核部门{tag}",
            "org_type": "dept", "parent_id": parent.get("id")})
        dept_id = data(r).get("id")
        report("A-S2-2 可建部门主数据", r.status_code == 200 and bool(dept_id),
               f"parent={parent.get('name')} {msg(r) if r.status_code != 200 else ''}")

    team_id = None
    if dept_id:
        r = c.post(f"{API}/organizations", json={
            "code": f"TEAM-{tag}", "name": f"复核班组{tag}",
            "org_type": "team", "parent_id": dept_id})
        team_id = data(r).get("id")
        report("A-S2-3 部门下可建班组", r.status_code == 200 and bool(team_id),
               msg(r) if r.status_code != 200 else "")

    if team_id:
        # 层级白名单：班组下面不能再挂班组
        r = c.post(f"{API}/organizations", json={
            "code": f"TEAM2-{tag}", "name": "班组下的班组",
            "org_type": "team", "parent_id": team_id})
        report("A-S2-4 层级白名单拦住「班组挂班组」", r.status_code == 400,
               f"status={r.status_code} {msg(r)[:60]}")

    if dept_id and team_id:
        # 成环：把部门移到自己的子孙下，必须被拒
        r = c.put(f"{API}/organizations/{dept_id}/move", json={"parent_id": team_id})
        report("A-S2-5 移动不会造成环（移到自己的子孙被拒）",
               r.status_code in (400, 409), f"status={r.status_code} {msg(r)[:60]}")

    if team_id:
        r = c.get(f"{API}/organizations/{team_id}/members")
        report("A-S2-6 组织可挂成员", r.status_code == 200,
               f"status={r.status_code} {msg(r)[:60] if r.status_code != 200 else ''}")

    # ══════════════ F-S7 碳排放核算 ══════════════
    print("\n── F-S7 碳排放核算（交叉校验口径）──")
    r = c.get(f"{API}/energy/carbon/emissions", params={"page_size": 100})
    rows = data(r).get("items") or []
    # ★ 只断言"接口可读"，**不把"没有数据"算成断点**。
    #   `carbon_emission_record` 由 ECMS（独立产品线 ziwi_project_dna）写入，
    #   mfg 仓里 `repositories/energy_repo.py` 全是 SELECT，没有任何写入口 ——
    #   所以"mfg 的库里有排放明细"本来就不是本产品线的责任。
    #   把空表判成 FAIL，等于把产品边界当故障：红的不是缺陷，绿的可信度也被拖下水
    #   （历史上已经吃过"把设计内降级 403 当故障"的亏）。这里改为先证伪
    #   "mfg 有写入口"这个假设，再明示边界。
    report("F-S7-1 排放明细接口可读", r.status_code == 200, f"HTTP {r.status_code} {len(rows)} 条")

    if not rows:
        w = c.post(f"{API}/energy/carbon/emissions", json={"energy_type": "electricity"})
        report("F-S7-1b mfg 侧无能耗写入口（边界证伪）", w.status_code in (404, 405),
               f"POST → {w.status_code}")
        print("[OUT] 排放明细为空：数据由 ECMS 提供、mfg 只读，核算口径交叉校验本次无法执行")

    if rows:
        days = sorted({str(x.get("record_date")) for x in rows})
        start, end = days[0], days[-1]
        # 自己按明细算一遍
        mine_c, mine_e = {}, {}
        for x in rows:
            et = x.get("energy_type")
            mine_c[et] = mine_c.get(et, 0) + float(x.get("energy_consumption") or 0)
            mine_e[et] = mine_e.get(et, 0) + float(x.get("emission_amount") or 0)

        r = c.get(f"{API}/energy/carbon/accounting",
                  params={"start_date": start, "end_date": end})
        acc = data(r)
        report("F-S7-2 核算接口可用", r.status_code == 200,
               f"{start} ~ {end} {msg(r) if r.status_code != 200 else ''}")

        bd = acc.get("source_breakdown") or []
        theirs_c = {b.get("energy_type"): float(b.get("total_consumption") or 0) for b in bd}
        theirs_e = {b.get("energy_type"): float(b.get("total_emission") or 0) for b in bd}

        diff_c = {k: (round(theirs_c.get(k, 0), 4), round(v, 4))
                  for k, v in mine_c.items()
                  if abs(theirs_c.get(k, 0) - v) > 0.01}
        diff_e = {k: (round(theirs_e.get(k, 0), 4), round(v, 4))
                  for k, v in mine_e.items()
                  if abs(theirs_e.get(k, 0) - v) > 0.01}
        report("F-S7-3 能耗口径与明细自算一致（接口 vs 逐行加总）",
               not diff_c, f"不一致 {diff_c}" if diff_c else f"{len(mine_c)} 类能源全对得上")
        report("F-S7-4 排放口径与明细自算一致",
               not diff_e, f"不一致 {diff_e}" if diff_e else f"{len(mine_e)} 类能源全对得上")

        total_kg = float(acc.get("total_co2_kg") or 0)
        mine_total = sum(mine_e.values())
        report("F-S7-5 总排放 = 各能源类型之和",
               abs(total_kg - mine_total) < 0.05,
               f"接口 {total_kg:g} vs 自算 {mine_total:g}")
        report("F-S7-6 吨与公斤换算一致",
               abs(float(acc.get("total_co2_ton") or 0) * 1000 - total_kg) < 0.05,
               f"{acc.get('total_co2_ton')} t vs {total_kg:g} kg")

    # ══════════════ G-S4 实验委托 → 报告 → 审批 ══════════════
    print("\n── G-S4 实验委托 → 收样 → 检测 → 报告 → 审批 ──")
    r = c.get(f"{API}/users", params={"page_size": 50})
    users = data(r).get("items") or []
    tester = next((u for u in users if u.get("username") != USER), users[0] if users else None)

    r = c.post(f"{API}/lab/requests", json={
        "title": f"复核委托{tag}", "request_type": "material",
        "priority": "medium", "description": "E2E 复核实验室链路"})
    req_id = data(r).get("id")
    report("G-S4-1 建实验委托", r.status_code == 200 and bool(req_id),
           msg(r) if r.status_code != 200 else "")
    if not req_id:
        return summary()

    steps = [
        ("G-S4-2 收样", "post", f"{API}/lab/requests/{req_id}/receive", {}),
        ("G-S4-3 分派检测人", "post", f"{API}/lab/requests/{req_id}/assign",
         {"assignee_id": tester.get("id")} if tester else {}),
        ("G-S4-4 开始检测", "post", f"{API}/lab/requests/{req_id}/start", {}),
        ("G-S4-5 提交检测结果", "post", f"{API}/lab/requests/{req_id}/results",
         {"results": [{"item_name": "硬度", "test_value": "52",
                       "unit": "HRC", "conclusion": "pass"}]}),
        ("G-S4-6 复核", "post", f"{API}/lab/requests/{req_id}/review", {}),
        ("G-S4-7 审批", "post", f"{API}/lab/requests/{req_id}/approve", {}),
        ("G-S4-8 发布报告", "post", f"{API}/lab/requests/{req_id}/publish-report",
         {"conclusion": "E2E 复核结论：合格"}),
    ]
    stopped = None
    for name, method, url, payload in steps:
        r = c.post(url, json=payload)
        good = r.status_code == 200
        if good:
            ok(name)
        else:
            gap(name, f"HTTP {r.status_code} {msg(r)[:100]}")
            stopped = name
            break

    if not stopped:
        r = c.get(f"{API}/lab/requests/{req_id}/report")
        rep = data(r)
        report("G-S4-9 报告可读（原标注 404）", r.status_code == 200,
               f"status={r.status_code} {msg(r)[:80] if r.status_code != 200 else ''}")
        r = c.get(f"{API}/lab/requests/{req_id}")
        # 终态是 done（报告已发布的那个状态），不是 published —— 按实际状态机来
        report("G-S4-10 委托进入终态（报告已发布）",
               (data(r).get("status") or "") in ("done", "published", "approved", "completed"),
               f"status={data(r).get('status')}")

    # ══════════════ E-B1 跨仓调拨 ══════════════
    print("\n── E-B1 跨仓调拨（原标注 ⚠️：无 transfer 端点）──")
    # 端点其实是有的（POST /wms/inventory/stock-move），但只支持同仓移位，
    # 且因 find_one 传 None 与 unit_price 漏传两个 bug 叠加，从未成功过。
    r = c.get(f"{API}/wms/inventory", params={"page_size": 100})
    inv = data(r).get("items") or []
    # 库位 → 所属仓库（判定"跨仓"的权威依据）
    r = c.get(f"{API}/wms/locations", params={"page_size": 100})
    locs_all = (data(r).get("items") if isinstance(data(r), dict) else data(r)) or []
    loc_wh = {l.get("id"): l.get("warehouse_id") for l in locs_all}
    # 只挑"库存仓库 == 库位归属仓库"的行当源。实测 90 行里有 1 行不一致
    # （inventory.warehouse_id 与所在库位的 warehouse_id 对不上，见 BACKLOG），
    # 那一行本身是脏数据，不该拿它当靶子——但它暴露了另一个写入路径的同源缺陷。
    src = next((x for x in inv
                if (x.get("quantity") or 0) - (x.get("locked_qty") or 0) > 0
                and x.get("location_id")
                and loc_wh.get(x.get("location_id")) == x.get("warehouse_id")), None)
    inconsistent = [x for x in inv
                    if x.get("location_id")
                    and loc_wh.get(x.get("location_id"))
                    and loc_wh.get(x.get("location_id")) != x.get("warehouse_id")]
    report("E-B1-1 找到有货且归属一致的源库存行", src is not None,
           f"{len(inv)} 行库存，源={src and (src.get('warehouse_id'), src.get('location_id'))}"
           f"；归属不一致的脏数据 {len(inconsistent)} 行")
    if src:
        src_wh = src.get("warehouse_id")
        r = c.get(f"{API}/wms/warehouses", params={"page_size": 50})
        whs = data(r).get("items") or []
        tgt_wh = next((w for w in whs if w.get("id") != src_wh), None)
        report("E-B1-2 存在另一个仓库", tgt_wh is not None,
               f"{len(whs)} 个仓库，目标={tgt_wh and tgt_wh.get('code')}")

        tgt_loc = None
        if tgt_wh:
            r = c.get(f"{API}/wms/warehouses/{tgt_wh['id']}/locations", params={"page_size": 50})
            locs = (data(r).get("items") if isinstance(data(r), dict) else data(r)) or []
            tgt_loc = next((l for l in locs if l.get("is_active") in (True, 1, None)), None)
            report("E-B1-3 目标仓有可用库位", tgt_loc is not None,
                   f"{len(locs)} 个库位，目标库位={tgt_loc and tgt_loc.get('location_code')}")

        if tgt_loc:
            qty = 1.0
            before = float(src.get("quantity") or 0)
            r = c.post(f"{API}/wms/inventory/stock-move", json={
                "source_location_id": src.get("location_id"),
                "target_location_id": tgt_loc.get("id"),
                "material_id": src.get("material_id"),
                "quantity": qty, "unit": src.get("unit") or "个",
                "remark": "E2E 跨仓调拨复核"})
            res = data(r)
            report("E-B1-4 跨仓调拨接口成功（改造前 100% 失败）", r.status_code == 200,
                   f"status={r.status_code} {msg(r)[:100] if r.status_code != 200 else ''}")

            if r.status_code == 200:
                report("E-B1-5 识别为跨仓", res.get("cross_warehouse") is True,
                       f"src_wh={res.get('source_warehouse_id')} "
                       f"tgt_wh={res.get('target_warehouse_id')}")
                report("E-B1-6 目标仓库 = 目标库位实际归属（不再抄源仓）",
                       res.get("target_warehouse_id") == tgt_wh.get("id"),
                       f"期望 {tgt_wh.get('id')} 实际 {res.get('target_warehouse_id')}")

                # 目标库存真的落在目标仓名下
                r = c.get(f"{API}/wms/inventory/by-location",
                          params={"location_id": tgt_loc.get("id")})
                rows = data(r) if isinstance(data(r), list) else []
                hit = next((x for x in rows
                            if x.get("material_id") == src.get("material_id")), None)
                report("E-B1-7 目标仓能查到这批货（账实相符）",
                       hit is not None and hit.get("warehouse_id") == tgt_wh.get("id"),
                       f"warehouse_id={hit and hit.get('warehouse_id')} "
                       f"qty={hit and hit.get('quantity')}")

                # 双仓流水：两条同凭证号
                r = c.get(f"{API}/wms/storage-moves",
                          params={"material_id": src.get("material_id"), "page_size": 50})
                txs = (data(r).get("items") if isinstance(data(r), dict) else data(r)) or []
                same = [t for t in txs if t.get("voucher_no") == res.get("voucher_no")]
                report("E-B1-8 双仓流水（两条同凭证号）", len(same) == 2,
                       f"{len(same)} 条 voucher={res.get('voucher_no')}")
                if len(same) == 2:
                    whs_tx = sorted(t.get("warehouse_id") for t in same)
                    report("E-B1-9 两条流水分属两个仓",
                           whs_tx == sorted([src_wh, tgt_wh.get("id")]), f"{whs_tx}")

    # ══════════════ F-S4 设备维修工单 + 停机时长 ══════════════
    print("\n── F-S4 设备维修工单 → 停机时长统计 ──")
    r = c.get(f"{API}/equipment", params={"page_size": 20})
    eqs = (data(r).get("items") if isinstance(data(r), dict) else data(r)) or []
    eq = next((e for e in eqs if (e.get("status") or "") != "maintenance"), None)
    report("F-S4-1 取到可用设备", eq is not None,
           f"{len(eqs)} 台，选中 id={eq and eq.get('id')} status={eq and eq.get('status')}")

    if eq:
        r = c.post(f"{API}/maintenance-tasks", json={
            "equipment_id": eq.get("id"), "task_type": "repair",
            "description": f"E2E 维修工单{tag}", "priority": 5})
        task_id = data(r).get("id")
        report("F-S4-2 可建维修工单", r.status_code == 200 and bool(task_id),
               f"status={r.status_code} {msg(r)[:80] if r.status_code != 200 else ''}")

        if task_id:
            r = c.put(f"{API}/maintenance-tasks/{task_id}/start")
            st = data(r)
            report("F-S4-3 维修开工（设备转 maintenance + 开停机记录）",
                   r.status_code == 200 and bool(st.get("downtime_id")),
                   f"downtime_id={st.get('downtime_id')} "
                   f"eq_status={st.get('equipment_status')}")

            r = c.put(f"{API}/maintenance-tasks/{task_id}/complete",
                      json={"result": "E2E 修复完成", "cost": 0})
            fin = data(r)
            report("F-S4-4 维修完工（关停机算时长）", r.status_code == 200,
                   f"status={r.status_code} {msg(r)[:80] if r.status_code != 200 else ''}")

            r = c.get(f"{API}/downtimes", params={"equipment_id": eq.get("id"),
                                                  "page_size": 20})
            dts = (data(r).get("items") if isinstance(data(r), dict) else data(r)) or []
            want_id = st.get("downtime_id")
            mine = next((d for d in dts if d.get("id") == want_id), None)
            report("F-S4-5 停机记录可查（按开工返回的 downtime_id 定位）",
                   mine is not None,
                   f"{len(dts)} 条停机记录，找 id={want_id}")
            if mine:
                report("F-S4-6 停机已关闭并算出时长",
                       mine.get("ended_at") is not None
                       and (mine.get("duration_minutes") or 0) >= 0,
                       f"duration={mine.get('duration_minutes')} 分")
                # 维修 = 故障停机，不能记成保养（否则 OEE 可用率虚高）
                report("F-S4-7 维修停机类型为 fault（改造前写死 maintenance，越界值）",
                       mine.get("downtime_type") == "fault",
                       f"downtime_type={mine.get('downtime_type')}")

    # ══════════════ C-S8 报工不良 → NCR → 返工单 ══════════════
    print("\n── C-S8 报工后返工单生成 ──")
    # 建一张已下达的工单，报工时带报废数
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-S8-{tag}", "product_code": "P-001",
        "product_name": f"返工验证件{tag}", "planned_qty": 100,
        "wo_type": "production"})
    wo_id = data(r).get("id")
    if wo_id:
        c.post(f"{API}/work-orders/{wo_id}/release")
    report("C-S8-1 建工单并下达", bool(wo_id), f"wo_no=WO-S8-{tag}")

    if wo_id:
        r = c.post(f"{API}/work-reports", json={
            "work_order_id": wo_id, "output_qty": 90, "scrap_qty": 10,
            "defect_reason": "E2E 尺寸超差", "reporter_id": 2,
            "report_date": datetime.now().date().isoformat()})
        rp = data(r)
        ncr_id = rp.get("ncr_id")
        report("C-S8-2 报工带报废自动开制程 NCR",
               r.status_code == 200 and bool(ncr_id),
               f"ncr_id={ncr_id} {msg(r)[:60] if r.status_code != 200 else ''}")

        if ncr_id:
            # 处置前先记下已有返工工单，避免"命中历史数据"冒充本次结论
            def _rework_ids():
                rr = c.get(f"{API}/work-orders", params={"page_size": 100})
                items = (data(rr).get("items") if isinstance(data(rr), dict)
                         else data(rr)) or []
                return {w.get("id") for w in items if w.get("wo_type") == "rework"}
            before = _rework_ids()

            r = c.put(f"{API}/ncr/{ncr_id}/status", json={
                "to_status": "reviewing", "action": "review"})
            report("C-S8-3 NCR 可进入评审", r.status_code == 200,
                   f"status={r.status_code} {msg(r)[:60] if r.status_code != 200 else ''}")

            r = c.put(f"{API}/ncr/{ncr_id}/status", json={
                "to_status": "disposed", "disposition": "rework",
                "disposition_remark": "E2E 返工处置"})
            disp = data(r)
            report("C-S8-4 NCR 处置为返工", r.status_code == 200,
                   f"status={r.status_code} {msg(r)[:80] if r.status_code != 200 else ''}")

            after = _rework_ids()
            new_ids = after - before
            report("C-S8-5 处置后**新增**了返工工单（处置前 {len(before)} 张 → 后 {len(after)} 张）"
                   .replace("{len(before)}", str(len(before)))
                   .replace("{len(after)}", str(len(after))),
                   len(new_ids) == 1,
                   f"新增 id={sorted(new_ids)}")

            if len(new_ids) == 1:
                rw_id = sorted(new_ids)[0]
                rr = c.get(f"{API}/work-orders/{rw_id}")
                rw = data(rr)
                report("C-S8-6 返工单关联了原工单/原 NCR",
                       str(rw.get("remark") or "").find(str(ncr_id)) >= 0
                       or str(rw.get("remark") or "").find("NCR") >= 0,
                       f"wo_no={rw.get('wo_no')} remark={(rw.get('remark') or '')[:60]}")

    return summary()


def summary():
    print(f"\n{'=' * 62}")
    print(f"通 {len(OK)} / 断 {len(GAP)}" + (f" / 边界外 {len(BOUNDARY)}" if BOUNDARY else ""))
    if GAP:
        print("断点：")
        for g in GAP:
            print(f"  - {g}")
    if BOUNDARY:
        print("边界外（按产品边界不做，非缺陷）：")
        for b in BOUNDARY:
            print(f"  - {b}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
