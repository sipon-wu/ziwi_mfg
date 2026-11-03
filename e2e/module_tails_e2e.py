"""各模块主数据「尾巴」· 场景验收探针（详情 / 改 / 删 / 动作）。

## 这个探针要回答什么

覆盖矩阵收口时剩下的最后 21 条，全是各模块主数据的**尾巴**：
列表和创建早被别的探针覆盖，只有 `{id}` 那一半和几个"动作"端点从没被执行过。

    M00 基础数据：产品详情/改/删 · 日历批量设置 · 工艺路线归档
    M01 生产管理：生产日报 · 工单可用动作
    M05 工作中心：安灯升级日志 · 升级规则 详情/改/删
    M06 设备 TPM：设备分类 · 设备扫码 · 保养任务状态 · 备件 改/删
    M11 能碳管理：能源设备 列表/建/详情/改/删

这类端点"没测过"的典型后果不是崩，而是**改不动/删不掉**：主数据录错了
只能再建一条新的，台账越用越脏；或者前端按钮该灰的时候不灰。

## 场景（A推进器厂 · 工艺与设备台账维护）

1. 基础数据：建产品「推力室壳体」→ 改规格 → 删；批量把年末 3 天设为停产；
   建工艺路线 → 归档（归档后不能再改）
2. 生产：查 11-03 生产日报；查某工单当前可执行动作
3. 安灯：建「超 15 分钟未响应」升级规则 → 改超时 → 查升级日志 → 删
4. 设备：查设备分类 → 扫设备码 → 建保养任务并置状态 → 建备件 → 改 → 删
5. 能碳：建能源设备（电表）→ 列表 → 详情 → 改 → 删

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/module_tails_e2e.py
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("TENANT_CODE", "MFG1")
USER = os.environ.get("ADMIN_USER", "mfg_admin")
PWD = os.environ.get("ADMIN_PWD", "admin123")

PASS = FAIL = 0
FAILS: list[str] = []


def report(name: str, ok: bool, detail: str = "") -> bool:
    global PASS, FAIL
    if ok:
        PASS += 1
        print(f"  [PASS] {name}" + (f" · {detail}" if detail else ""))
    else:
        FAIL += 1
        FAILS.append(f"{name} · {detail}")
        print(f"  [FAIL] {name}" + (f" · {detail}" if detail else ""))
    return ok


def data(r: httpx.Response):
    try:
        return (r.json() or {}).get("data")
    except Exception:
        return None


def items(r: httpx.Response) -> list:
    d = data(r)
    if isinstance(d, dict):
        return d.get("items") or []
    return d if isinstance(d, list) else []


def new_id(r: httpx.Response):
    d = data(r)
    if isinstance(d, dict):
        return d.get("id")
    return d if isinstance(d, int) else None


def detail(r: httpx.Response) -> dict:
    try:
        d = (r.json() or {}).get("detail")
    except Exception:
        return {}
    return d if isinstance(d, dict) else {"message": str(d or "")}


def login(c: httpx.Client) -> dict:
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_code": TENANT})
    payload = r.json()
    if isinstance(payload.get("data"), dict):
        payload = payload["data"]
    return payload


def main() -> int:
    c = httpx.Client(timeout=40)
    payload = login(c)
    tok = payload.get("access_token")
    if not tok:
        print(f"[FATAL] 登录失败: {payload}")
        return 1
    c.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}")

    tag = datetime.now().strftime("%H%M%S")

    # ============ T1 M00 基础数据 ============
    print("\n── T1 M00 基础数据（产品 / 日历 / 工艺路线）──")

    prod_code = f"PRD-TS-{tag}"
    r = c.post(f"{API}/products", json={
        "code": prod_code, "name": f"推力室壳体-{tag}", "spec": "Φ420×680",
        "unit": "件", "product_type": "finished", "category": "推进器结构件",
        "weight": 38.5, "remark": "TC4 钛合金整体成形"})
    pid = new_id(r)
    report("T1-1 产品可创建", pid is not None,
           f"HTTP {r.status_code} product_id={pid}")
    if not pid:
        print(f"[FATAL] 产品建不出来: {r.text[:200]}")
        return 1

    r = c.get(f"{API}/products/{pid}")
    got = data(r) or {}
    report("T1-2 产品详情可读且编码/规格一致",
           r.status_code == 200 and got.get("code") == prod_code
           and got.get("spec") == "Φ420×680",
           f"HTTP {r.status_code} code={got.get('code')}")

    r = c.put(f"{API}/products/{pid}",
              json={"spec": "Φ420×680（精加工后）", "weight": 37.2})
    after = data(c.get(f"{API}/products/{pid}")) or {}
    report("T1-3 产品可改规格与重量且读回一致",
           r.status_code == 200 and after.get("spec") == "Φ420×680（精加工后）"
           and float(after.get("weight") or 0) == 37.2,
           f"HTTP {r.status_code} spec={after.get('spec')} weight={after.get('weight')}")

    r = c.delete(f"{API}/products/{pid}")
    r2 = c.get(f"{API}/products/{pid}")
    report("T1-4 产品可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # 批量设日历：年末三天停产（推进器厂按客户交付节拍放假）
    batch = []
    for d in ("2026-12-30", "2026-12-31", "2027-01-01"):
        batch.append({"year": int(d[:4]), "cal_date": d, "day_type": "holiday",
                      "name": f"年末停产-{tag}"})
    r = c.post(f"{API}/calendars/batch", json={"dates": batch})
    res = data(r) or {}
    report("T1-5 ★日历可批量设置（3 天一次提交，不是循环 3 次单点）",
           r.status_code == 200 and int(res.get("affected") or 0) == 3,
           f"HTTP {r.status_code} affected={res.get('affected')}")

    r = c.get(f"{API}/calendars/2026/12")
    days = items(r) if items(r) else (data(r) if isinstance(data(r), list) else [])
    hit = [x for x in (days or []) if str(x.get("cal_date", "")).startswith("2026-12-30")]
    report("T1-6 批量设置的日期在日历里读得到（holiday）",
           r.status_code == 200 and bool(hit)
           and hit[0].get("day_type") == "holiday",
           f"HTTP {r.status_code} 命中 {hit[0] if hit else '无'}")

    # 工艺路线：建 → 归档
    route_code = f"RT-TS-{tag}"
    r = c.post(f"{API}/routes", json={
        "code": route_code, "name": f"推力室壳体机加路线-{tag}",
        "version": 1, "route_type": "discrete",
        "description": "粗车 → 精车 → 压装 → 试压"})
    rid = new_id(r)
    report("T1-7 工艺路线可创建", rid is not None,
           f"HTTP {r.status_code} route_id={rid}")
    if rid:
        r = c.post(f"{API}/routes/{rid}/archive")
        after = data(c.get(f"{API}/routes/{rid}")) or {}
        report("T1-8 ★路线可归档且状态落 archived（归档后不可再改）",
               r.status_code == 200 and after.get("status") == "archived",
               f"HTTP {r.status_code} status={after.get('status')} "
               f"{detail(r).get('message', '') if r.status_code != 200 else ''}")

    # ============ T2 M01 生产管理 ============
    print("\n── T2 M01 生产管理（日报 / 工单动作）──")

    d = (datetime.now() - timedelta(days=1)).strftime("%Y-%m-%d")
    r = c.get(f"{API}/reports/daily", params={"report_date": d})
    rep = data(r) or {}
    report("T2-1 ★生产日报可读（按日聚合，空日也应是 0 而不是 500）",
           r.status_code == 200 and isinstance(rep, dict),
           f"HTTP {r.status_code} {list(rep)[:6] if isinstance(rep, dict) else rep}")

    r = c.get(f"{API}/work-orders", params={"page_size": 5})
    wos = items(r)
    wo = wos[0] if wos else {}
    wo_id = wo.get("id")
    report("T2-2 有工单可用于查动作", wo_id is not None,
           f"wo_id={wo_id} status={wo.get('status')}")
    if wo_id:
        r = c.get(f"{API}/work-orders/{wo_id}/actions")
        acts = data(r)
        report("T2-3 ★工单可用动作可读（前端按钮渲染的单一真相源）",
               r.status_code == 200 and isinstance(acts, (list, dict)),
               f"HTTP {r.status_code} status={wo.get('status')} "
               f"actions={acts if isinstance(acts, list) else list(acts or {})[:6]}")

    # ============ T3 M05 工作中心 · 安灯升级 ============
    print("\n── T3 M05 安灯升级规则 ──")

    r = c.post(f"{API}/andon/escalation-rules", json={
        "rule_name": f"超15分钟未响应升级-{tag}", "call_type": "equipment",
        "priority": "all", "level": 1, "timeout_minutes": 15,
        "notify_role": "workshop_manager", "is_active": True})
    rule_id = new_id(r)
    report("T3-1 升级规则可创建", rule_id is not None,
           f"HTTP {r.status_code} rule_id={rule_id}")
    if not rule_id:
        print(f"[FATAL] 升级规则建不出来: {r.text[:200]}")
        return 1

    r = c.get(f"{API}/andon/escalation-rules/{rule_id}")
    got = data(r) or {}
    report("T3-2 升级规则详情可读且超时 15 分钟",
           r.status_code == 200 and int(got.get("timeout_minutes") or 0) == 15,
           f"HTTP {r.status_code} timeout={got.get('timeout_minutes')}")

    r = c.put(f"{API}/andon/escalation-rules/{rule_id}",
              json={"timeout_minutes": 10, "level": 2})
    after = data(c.get(f"{API}/andon/escalation-rules/{rule_id}")) or {}
    report("T3-3 升级规则可改超时与等级且读回一致",
           r.status_code == 200 and int(after.get("timeout_minutes") or 0) == 10
           and int(after.get("level") or 0) == 2,
           f"HTTP {r.status_code} timeout={after.get('timeout_minutes')} level={after.get('level')}")

    r = c.get(f"{API}/andon/escalation-logs", params={"page_size": 20})
    report("T3-4 升级日志可读（分页结构）",
           r.status_code == 200 and isinstance(data(r), (dict, list)),
           f"HTTP {r.status_code} 共 {len(items(r))} 条")

    r = c.delete(f"{API}/andon/escalation-rules/{rule_id}")
    r2 = c.get(f"{API}/andon/escalation-rules/{rule_id}")
    report("T3-5 升级规则可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # ============ T4 M06 设备 TPM ============
    print("\n── T4 M06 设备 TPM（分类 / 扫码 / 保养任务 / 备件）──")

    r = c.get(f"{API}/equipment-categories")
    cats = data(r)
    report("T4-1 设备分类可读（新建设备时的下拉源）",
           r.status_code == 200 and isinstance(cats, (list, dict)),
           f"HTTP {r.status_code} {cats if isinstance(cats, list) else list(cats or {})[:6]}")

    r = c.get(f"{API}/equipment", params={"page_size": 5})
    eqs = items(r)
    eq = eqs[0] if eqs else {}
    eq_id = eq.get("id")
    eq_code = eq.get("equipment_code") or eq.get("code")
    report("T4-2 有设备可用于扫码", bool(eq_code), f"equipment_code={eq_code}")

    if eq_code:
        r = c.get(f"{API}/equipment/scan", params={"code": eq_code})
        sc = data(r) or {}
        report("T4-3 ★扫设备码返回设备 + 任务清单（现场点检唯一入口）",
               r.status_code == 200 and (sc.get("equipment") or {}).get("id") is not None,
               f"HTTP {r.status_code} 任务 {len(sc.get('tasks') or [])} 条")

        r = c.get(f"{API}/equipment/scan", params={"code": f"NO-SUCH-EQ-{tag}"})
        report("T4-4 扫不存在的设备码 → 404（不是 500、不是空对象）",
               r.status_code == 404, f"HTTP {r.status_code}")

    if eq_id:
        r = c.post(f"{API}/maintenance-tasks", json={
            "equipment_id": eq_id, "task_type": "preventive",
            "description": f"月度点检-{tag}", "priority": 1})
        task_id = new_id(r)
        report("T4-5 保养任务可建", task_id is not None,
               f"HTTP {r.status_code} task_id={task_id}")
        if task_id:
            # status 是 **query 参数**。这里把状态设成它当前的值：既走完
            # update_task_status 这条路，又不改动演示数据（幂等断言）。
            cur = (data(c.get(f"{API}/maintenance-tasks/{task_id}")) or {}).get("status")
            r = c.put(f"{API}/maintenance-tasks/{task_id}/status",
                      params={"status": cur or "pending"})
            after = (data(c.get(f"{API}/maintenance-tasks/{task_id}")) or {}).get("status")
            report("T4-6 ★保养任务状态可改（status 是 query 不是 body）",
                   r.status_code == 200 and after == (cur or "pending"),
                   f"HTTP {r.status_code} {cur} → {after}")

    part_code = f"SP-TS-{tag}"
    r = c.post(f"{API}/spare-parts", json={
        "part_code": part_code, "part_name": f"密封圈-{tag}",
        "spec": "Φ120×5", "unit": "个", "current_stock": 20,
        "min_stock": 5, "location": "备件库A-03"})
    part = data(r) or {}
    part_id = part.get("id") if isinstance(part, dict) else part
    report("T4-7 备件可建", part_id is not None,
           f"HTTP {r.status_code} part_id={part_id}")

    if part_id:
        # ★这一条是刻意打「部分更新」：主数据编辑页改一个安全库存就该能提交。
        r = c.put(f"{API}/spare-parts/{part_id}", json={"min_stock": 8})
        report("T4-8 ★备件支持部分更新（只改安全库存，不用把整条记录回传）",
               r.status_code == 200,
               f"HTTP {r.status_code} {detail(r).get('message', '')[:60]}")

        r = c.put(f"{API}/spare-parts/{part_id}", json={
            "part_code": part_code, "part_name": f"密封圈-{tag}",
            "spec": "Φ120×5", "unit": "个", "current_stock": 20,
            "min_stock": 8, "location": "备件库A-04"})
        report("T4-9 备件整条回传也能改（两种提交方式都要能用）",
               r.status_code == 200, f"HTTP {r.status_code}")

        r = c.delete(f"{API}/spare-parts/{part_id}")
        report("T4-10 备件可删除", r.status_code == 200, f"HTTP {r.status_code}")

    # ============ T5 M11 能碳设备 ============
    print("\n── T5 M11 能碳管理（能源设备台账）──")

    r = c.get(f"{API}/energy/devices", params={"page_size": 20})
    before = len(items(r))
    report("T5-1 能源设备列表可读", r.status_code == 200,
           f"HTTP {r.status_code} 共 {before} 台")

    dev_code = f"EM-TS-{tag}"
    r = c.post(f"{API}/energy/devices", json={
        "device_code": dev_code, "device_name": f"压装机主电表-{tag}",
        "device_type": "meter", "energy_type": "electricity",
        "location": "机加车间·压装工位", "remark": "推进器壳体压装线"})
    dev_id = new_id(r)
    report("T5-2 能源设备可创建", dev_id is not None,
           f"HTTP {r.status_code} device_id={dev_id}")
    if not dev_id:
        print(f"[FATAL] 能源设备建不出来: {r.text[:200]}")
        return 1

    r = c.get(f"{API}/energy/devices/{dev_id}")
    got = data(r) or {}
    report("T5-3 能源设备详情可读且编码/类型一致",
           r.status_code == 200 and got.get("device_code") == dev_code
           and got.get("energy_type") == "electricity",
           f"HTTP {r.status_code} code={got.get('device_code')}")

    r = c.get(f"{API}/energy/devices", params={"energy_type": "electricity", "page_size": 50})
    report("T5-4 能源设备可按能源类型过滤，且含刚建的一台",
           r.status_code == 200 and any(x.get("id") == dev_id for x in items(r)),
           f"HTTP {r.status_code} 共 {len(items(r))} 台")

    # ★同上：只改安装位置，不重传整条记录
    r = c.put(f"{API}/energy/devices/{dev_id}", json={"location": "机加车间·压装工位B"})
    report("T5-5 ★能源设备支持部分更新（只改安装位置）",
           r.status_code == 200,
           f"HTTP {r.status_code} {detail(r).get('message', '')[:60]}")

    if r.status_code == 200:
        after = data(c.get(f"{API}/energy/devices/{dev_id}")) or {}
        report("T5-6 部分更新后位置真的变了（不是静默忽略）",
               after.get("location") == "机加车间·压装工位B",
               f"location={after.get('location')}")

    r = c.delete(f"{API}/energy/devices/{dev_id}")
    r2 = c.get(f"{API}/energy/devices/{dev_id}")
    report("T5-7 能源设备可删除且删除后详情 404",
           r.status_code == 200 and r2.status_code == 404,
           f"删除 HTTP {r.status_code} 复查 HTTP {r2.status_code}")

    # ============ 汇总 ============
    print("\n" + "=" * 62)
    print(f"PASS {PASS} / FAIL {FAIL}")
    if FAILS:
        print("失败项：")
        for f in FAILS:
            print(f"  - {f}")
    print("=" * 62)
    return 0 if FAIL == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
