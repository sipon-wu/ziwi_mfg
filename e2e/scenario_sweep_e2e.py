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
TENANT = os.environ.get("E2E_TENANT", "mfg_demo")
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
    report("F-S7-1 排放明细可读", r.status_code == 200 and bool(rows), f"{len(rows)} 条")

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

    return summary()


def summary():
    print(f"\n{'=' * 62}")
    print(f"通 {len(OK)} / 断 {len(GAP)}")
    if GAP:
        print("断点：")
        for g in GAP:
            print(f"  - {g}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
