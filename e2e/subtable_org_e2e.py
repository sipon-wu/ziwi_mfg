"""子表组织归属 · 端到端验证（真实 HTTP + 真实 DB）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/subtable_org_e2e.py

## 要证明的事

切强制模式（commit a20b2ef）后，权限边界是真的了，但**数据范围只覆盖 5 张主表**。
三张高频子表完全不过滤：

    work_reports / inspection_result / inventory_transactions

后果不是"看不到"而是**全看到** —— 带 DEPT / DEPT_CHILD 范围的角色在这三张表上
拿到全公司数据。页面有数据、排序正常、就是多了，不点开对比根本发现不了。

所以这里用两个账号做**差分验证**（这是唯一能证明"过滤生效"的方式，
只看"有数据"证明不了任何事）：

    admin（ALL 范围）      → 基线
    demo_ws1_leader（DEPT_CHILD @ 一号车间） → 必须严格小于基线

## 断言清单

    S1  两个账号都能登录，范围解析符合预期
    S2  ws1 主任在报工/库存流水列表上看到 0 条（存量数据都在公司根节点）
    S3  ws1 主任建工单 → 下达 → 报工，报工行 org_id 落一号车间（不是 NULL）
    S4  ws1 主任看报工列表 = 1 条（只有他自己那条）→ **过滤生效**
    S5  admin 看报工列表 = 基线 + 1 → **没误伤**
    S6  ws1 主任读根节点检验单的明细 → 空；admin 读同一张 → 非空
        （inspection_result 继承父单组织，子表不能比父单更宽）
    S7  ws1 主任看不到自己建的工单以外的东西：工单列表也严格小于 admin
"""
import os
import sys
from datetime import date, datetime

import httpx

API = os.environ.get("API_BASE", "http://127.0.0.1:8000/api/v1")
TENANT = os.environ.get("E2E_TENANT", "AH-THR")

ADMIN = ("mfg_admin", "admin123")
SCOPED = ("demo_ws1_leader", "admin123")

PASS, FAIL = [], []


def check(name, ok, detail=""):
    (PASS if ok else FAIL).append(name)
    print(f"  [{'PASS' if ok else 'FAIL'}] {name}" + (f" · {detail}" if detail else ""))


def body(r):
    try:
        return r.json()
    except Exception:
        return {}


def data_of(r):
    d = body(r)
    return d.get("data") if isinstance(d.get("data"), dict) else {}


def total_of(r):
    """列表接口的 total；非 200 返 -1 让断言直接失败而不是静默通过。"""
    if r.status_code != 200:
        return -1
    d = body(r).get("data")
    if isinstance(d, dict):
        return d.get("total", len(d.get("items") or []))
    return -1


def login(username, password):
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": username, "password": password, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {username}: {r.status_code} {r.text[:200]}")
        return None, None
    token = r.json().get("access_token")
    c.headers.update({"Authorization": f"Bearer {token}", "X-Tenant-Id": TENANT})
    return c, token


def me(c):
    r = c.get(f"{API}/auth/me")
    raw = body(r)
    return (raw.get("data") or raw) if isinstance(raw, dict) else {}


def main():
    print(f"API={API} tenant={TENANT}\n")

    # ── S1 登录 + 范围解析 ──
    print("── S1 两个账号登录 ──")
    admin, _ = login(*ADMIN)
    scoped, scoped_token = login(*SCOPED)
    if not admin or not scoped:
        print("[FATAL] 账号登录失败，无法继续（先确认 seed_organizations.py 已跑过）")
        return 1

    me_admin, me_scoped = me(admin), me(scoped)
    check("S1 admin 登录成功", bool(me_admin.get("username")),
          f"username={me_admin.get('username')} org_id={me_admin.get('org_id')}")
    check("S1 demo_ws1_leader 登录成功", bool(me_scoped.get("username")),
          f"username={me_scoped.get('username')} org_id={me_scoped.get('org_id')}")
    check("S1 演示账号挂在真实部门（不是公司根 1）",
          me_scoped.get("org_id") not in (None, 1),
          f"org_id={me_scoped.get('org_id')}（应为 一号车间=2）")

    # ── S2 基线：报工 / 库存流水 ──
    # 断言全部写成**相对基线**（scoped < admin、增量各 +1），不写死绝对值。
    # 写死 0/1 的代价是脚本只能跑一次，第二次就假失败 —— 那等于没有回归测试。
    print("── S2 基线差分 ──")
    base_reports = total_of(admin.get(f"{API}/work-reports", params={"page_size": 1}))
    scoped_reports = total_of(scoped.get(f"{API}/work-reports", params={"page_size": 1}))
    check("S2 admin 能看到报工（列表非空）", base_reports > 0, f"total={base_reports}")
    check("S2 ws1 主任可见报工数严格小于 admin（数据范围生效）",
          0 <= scoped_reports < base_reports,
          f"scoped={scoped_reports} < admin={base_reports}"
          f"（改造前两边都是 {base_reports}）")

    base_tx = total_of(admin.get(f"{API}/wms/inventory-transactions", params={"page_size": 1}))
    scoped_tx = total_of(scoped.get(f"{API}/wms/inventory-transactions", params={"page_size": 1}))
    check("S2 admin 能看到库存流水", base_tx > 0, f"total={base_tx}")
    check("S2 ws1 主任可见库存流水数严格小于 admin", 0 <= scoped_tx < base_tx,
          f"scoped={scoped_tx} < admin={base_tx}")

    base_wo = total_of(admin.get(f"{API}/work-orders", params={"page_size": 1}))
    scoped_wo = total_of(scoped.get(f"{API}/work-orders", params={"page_size": 1}))
    check("S2 工单（主表，改造前已过滤）同样严格小于 admin", scoped_wo < base_wo,
          f"scoped={scoped_wo} admin={base_wo}")

    # ── S3 造数据：ws1 主任自己建工单 + 报工 ──
    print("── S3 一号车间主任建单报工（验证写入归属）──")
    tag = datetime.now().strftime("%m%d%H%M%S")
    wo_no = f"WO-ORG-{tag}"
    r = scoped.post(f"{API}/work-orders", json={
        "wo_no": wo_no, "product_code": f"PRO-ORG-{tag}",
        "product_name": f"组织归属验证件{tag}", "planned_qty": 10,
    })
    wo_id = data_of(r).get("id")
    check("S3 ws1 主任能建工单", r.status_code == 200 and bool(wo_id),
          f"HTTP {r.status_code} id={wo_id} {'' if wo_id else r.text[:160]}")

    report_ok = False
    if wo_id:
        r = scoped.post(f"{API}/work-orders/{wo_id}/release", json={})
        check("S3 工单下达成功", r.status_code == 200, f"HTTP {r.status_code}")
        r = scoped.post(f"{API}/work-reports", json={
            "work_order_id": wo_id, "report_date": str(date.today()),
            "output_qty": 10, "labor_hours": 2.0})
        report_ok = r.status_code == 200
        check("S3 报工成功", report_ok, f"HTTP {r.status_code} {'' if report_ok else r.text[:160]}")

    # ── S4 / S5 差分再次对比 ──
    print("── S4/S5 新增数据后重新差分（增量断言，可重复跑）──")
    scoped_after = total_of(scoped.get(f"{API}/work-reports", params={"page_size": 50}))
    admin_after = total_of(admin.get(f"{API}/work-reports", params={"page_size": 50}))
    check("S4 ws1 主任的可见数恰好 +1（自己的报工看得见）",
          scoped_after == scoped_reports + 1,
          f"{scoped_reports} → {scoped_after}（若为 0 增量说明写入没落 org_id）")
    check("S5 admin 的报工数恰好 +1（没有误伤）", admin_after == base_reports + 1,
          f"{base_reports} → {admin_after}")

    # 直接回读接口确认落的是「一号车间」而不是 NULL/根节点。
    # ★不能读本地 SQLite：探针打的是 staging（API_BASE=https://mfg1.ziwi.cn），
    #   报工行落在 staging 的 PostgreSQL 里，本地 sqlite 一行都没有 ——
    #   原写法让 org_id=[] 恒报"归属没生效"，把做对了的事显示成缺陷。
    try:
        rr = admin.get(f"{API}/work-reports",
                       params={"work_order_id": wo_id, "page_size": 50})
        reps = (data_of(rr) or {}).get("items") or []
        orgs = [x.get("org_id") for x in reps]
        # ★不能写死「一号车间=2」：组织 id 是各环境自增的，staging 上
        #   一号车间不是 2。基准取报工人自己的 org_id（/auth/me），
        #   断言"子表归属 = 报工人的组织"，这才是要验证的东西。
        want_org = me_scoped.get("org_id")
        check("S3 报工行 org_id 非 NULL（写入归属生效）",
              bool(reps) and all(o is not None for o in orgs), f"org_id={orgs}")
        check("S3 报工行 org_id = 报工人所属组织",
              bool(reps) and want_org is not None and all(o == want_org for o in orgs),
              f"org_id={orgs} 期望={want_org}（报工人组织，不是工单归属）")
    except Exception as exc:
        check("S3 回读校验报工归属", False, f"回读失败：{exc}")

    # ── S6 inspection_result 继承父单组织 ──
    print("── S6 检验明细：子表不能比父单更宽 ──")
    r = admin.get(f"{API}/inspection-orders", params={"page_size": 100})
    orders = (data_of(r) or {}).get("items") or []
    # 必须挑一张**真的有明细**的单：库里大量检验单只有单头没有明细，
    # 拿空单去对比会得到"两边都空"，那种"通过"什么都证明不了。
    target, n_admin = None, 0
    for o in orders:
        if o.get("org_id") not in (None, 1):
            continue                      # 只看根节点的单（存量数据都在根节点）
        rr = admin.get(f"{API}/inspection-orders/{o['id']}/results")
        if rr.status_code == 200:
            n = len(body(rr).get("data") or [])
            if n > 0:
                target, n_admin = o, n
                break
    if not target:
        # 库里扫不到「有明细的根节点单」时**自己造一张**，而不是判失败。
        # staging 的存量检验单几乎都是只有单头没有明细（历史上明细录不进去，
        # 见 C-40），拿数据现状当缺陷会把这条验证永久卡死。
        # 用 admin 建单 → 落在根组织；再录一条明细，就有了可对比的父单。
        rc = admin.post(f"{API}/inspection-orders",
                        json={"order_type": "iqc", "material_id": 1,
                              "remark": f"org-scope 探针 {tag}"})
        oid = data_of(rc).get("id")
        if rc.status_code == 200 and oid:
            admin.post(f"{API}/inspection-orders/{oid}/results/batch",
                       json={"results": [{"item_name": f"外观{tag}", "result": "PASS",
                                          "measured_value": 1.0, "unit": "项"}]})
            rr = admin.get(f"{API}/inspection-orders/{oid}/results")
            n = len(body(rr).get("data") or []) if rr.status_code == 200 else 0
            if n > 0:
                target, n_admin = {"id": oid, "order_no": f"probe-{oid}"}, n
    if not target:
        check("S6 存在「有明细的根节点检验单」可用于对比", False,
              f"扫了 {len(orders)} 张单都没有明细，自建也没成功")
    else:
        oid = target["id"]
        r_scoped = scoped.get(f"{API}/inspection-orders/{oid}/results")
        n_scoped = len(body(r_scoped).get("data") or []) if r_scoped.status_code == 200 else -1
        check("S6 admin 能读到该检验单明细", n_admin > 0,
              f"order={oid} ({target.get('order_no')}) 明细 {n_admin} 条")
        check("S6 ws1 主任读同一张单的明细为空（不能比父单更宽）",
              r_scoped.status_code in (403, 404) or n_scoped == 0,
              f"HTTP {r_scoped.status_code} 明细 {n_scoped} 条")

    # ── 汇总 ──
    print(f"\n===== 合计 {len(PASS) + len(FAIL)} 项：PASS {len(PASS)} / FAIL {len(FAIL)} =====")
    if FAIL:
        print("失败项：")
        for name in FAIL:
            print(f"  - {name}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
