"""内置角色两层预置端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/tenant_role_preset_e2e.py

覆盖（BACKLOG C-77，2026-11-01 拍板「角色最基本可以预置，其它随模块预置」）：

    C-77-1  新建租户跑 preset-roles → 9 个内置角色全部就位，且 is_system=1
    C-77-2  内置角色带真实权限（以"部门负责人有 M01 读权"为例），不是空壳
    C-77-3  内置角色不可删除（409）—— 删掉后 seed 脚本只会报 unmatched，不会重建
    C-77-4  幂等：再跑一次不新建、不改已授权限
    C-77-5  随模块预置：只启用 M03 → 5 个角色（基础 3 + 检验员 + 质量工程师）
    C-77-6  基础角色与模块无关：只启用设备模块，部门负责人照样在
"""
import os
import sys
from datetime import datetime

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


def main():
    c = httpx.Client(timeout=30)
    r = c.post(f"{API}/auth/login", json={
        "username": USER, "password": PWD, "tenant_id": TENANT})
    if r.status_code != 200:
        print(f"[FATAL] 登录失败 {r.status_code}")
        return 1
    c.headers.update({"Authorization": f"Bearer {r.json()['access_token']}",
                      "X-Tenant-Id": TENANT})
    print(f"登录成功 tenant={TENANT}\n")

    tag = datetime.now().strftime("%m%d%H%M%S")

    def mk_tenant(suffix):
        """建租户并**回读真实 tenant_id** —— schema 不收 tenant_id，服务端生成 t_xxx。"""
        code = f"RP{suffix}{tag}"
        rr = c.post(f"{API}/tenants", json={
            "name": f"角色预置{suffix}{tag}", "code": code,
            "contact_name": "探针", "industry": "制造业"})
        assert rr.status_code == 200, f"建租户失败 {rr.status_code} {rr.text[:300]}"
        lst = c.get(f"{API}/tenants", params={"page": 1, "page_size": 100}).json()
        items = (lst.get("data") or {}).get("items") or []
        row = next((t for t in items if t.get("code") == code), None)
        assert row, f"建了租户 {code} 但列表里读不回"
        return row["tenant_id"]

    def preset(tenant_id, modules=None):
        params = {"modules": modules} if modules else None
        return c.post(f"{API}/tenants/{tenant_id}/preset-roles", params=params)

    # ── C-77-1 全预置 ──
    print("── C-77 基础角色 + 随模块预置 ──")
    tid = mk_tenant("full")
    r = preset(tid)
    ok = r.status_code == 200
    check("C-77-1 新租户预置角色成功", ok,
          f"HTTP {r.status_code} msg={err_msg(r)[:80]}")
    if not ok:
        return report()
    data = r.json()["data"]
    created = data.get("created") or []
    check("C-77-1 一次补齐 9 个内置角色（含 admin）",
          len(created) == 9,
          f"created={created}")
    check("C-77-1 三个基础角色始终在（admin/部门负责人/关键用户）",
          {"admin", "department_head", "key_user"} <= set(created),
          str(sorted(set(created))))
    check("C-77-1 授权模式全部命中（无 unmatched_patterns）",
          not data.get("unmatched_patterns"),
          f"unmatched={data.get('unmatched_patterns')}")

    granted = data.get("granted") or {}
    check("C-77-2 内置角色带真实权限（admin=全量、部门负责人>100 条）",
          granted.get("admin", 0) > 300 and granted.get("department_head", 0) > 100,
          f"admin={granted.get('admin')} dept_head={granted.get('department_head')}")
    check("C-77-2 检验员权限明显少于质量工程师（不是一刀切全给）",
          0 < granted.get("inspector", 0) < granted.get("quality_engineer", 0),
          f"inspector={granted.get('inspector')} qe={granted.get('quality_engineer')}")

    # ── C-77-3 内置角色不可删 ──
    # 用平台侧（mfg_demo 管理员）读不到别租户角色，这里切到该租户管理员身份：
    # 先初始化管理员 → 登录 → 删自己的内置角色。
    r = c.post(f"{API}/tenants/{tid}/init-admin", json={
        "username": f"ad_{tag}", "password": "Init@12345"})
    check("C-77-3 前置：新租户初始化管理员成功", r.status_code == 200,
          f"HTTP {r.status_code} msg={err_msg(r)[:80]}")
    n = httpx.Client(timeout=30)
    lr = n.post(f"{API}/auth/login", json={
        "username": f"ad_{tag}", "password": "Init@12345", "tenant_id": tid})
    check("C-77-3 新租户管理员可登录（角色链路没断）", lr.status_code == 200,
          f"HTTP {lr.status_code}")
    if lr.status_code != 200:
        return report()
    n.headers.update({"Authorization": f"Bearer {lr.json()['access_token']}",
                      "X-Tenant-Id": tid})

    # 初始密码必须先改（A-S1 契约 2），否则所有业务接口一律 403
    r = n.post(f"{API}/auth/change-password",
               json={"old_password": "Init@12345", "new_password": "Pass@12345"})
    check("C-77-3 新管理员改完初始密码（首登改密守卫生效）",
          r.status_code == 200, f"HTTP {r.status_code} msg={err_msg(r)[:60]}")

    rl = n.get(f"{API}/roles", params={"page": 1, "page_size": 50})
    items = (rl.json().get("data") or {}).get("items") or []
    by_code = {x.get("code"): x for x in items}
    check("C-77-3 新租户角色列表里能看到 9 个内置角色",
          len(items) >= 9, f"n={len(items)}")
    check("C-77-3 内置角色 is_system=1（界面据此隐藏删除按钮）",
          all(by_code.get(k, {}).get("is_system") for k in
              ("department_head", "inspector", "team_leader")),
          str({k: by_code.get(k, {}).get("is_system")
               for k in ("department_head", "inspector", "team_leader")}))

    rid = (by_code.get("inspector") or {}).get("id")
    if rid:
        r = n.delete(f"{API}/roles/{rid}")
        check("C-77-3 删内置角色被拒 409（删了不会自动重建）",
              r.status_code == 409 and "内置" in err_msg(r),
              f"HTTP {r.status_code} msg={err_msg(r)[:80]}")
    else:
        check("C-77-3 删内置角色被拒 409", False, "inspector 角色不存在")

    # ── C-77-4 幂等 ──
    r = preset(tid)
    data2 = r.json().get("data") or {}
    check("C-77-4 再跑一次不新建任何角色",
          r.status_code == 200 and not (data2.get("created") or []),
          f"created={data2.get('created')}")
    check("C-77-4 已存在角色全部跳过",
          len(data2.get("skipped") or []) == 9,
          f"skipped={len(data2.get('skipped') or [])}")

    # ── C-77-5 只启用品质模块 ──
    tid2 = mk_tenant("qc")
    r = preset(tid2, modules=["M03_QC", "M10_SPC"])
    d3 = r.json().get("data") or {}
    created3 = set(d3.get("created") or [])
    check("C-77-5 只启用品质模块 → 5 个角色（基础 3 + 检验员 + 质量工程师）",
          created3 == {"admin", "department_head", "key_user",
                       "inspector", "quality_engineer"},
          str(sorted(created3)))
    check("C-77-5 未买生产/设备模块 → 不出班组长/调度员/维保员",
          not ({"team_leader", "scheduler", "maintenance_tech"} & created3),
          str(sorted(created3)))

    # ── C-77-6 基础角色与模块无关 ──
    tid3 = mk_tenant("eq")
    r = preset(tid3, modules=["M06_EQUIPMENT"])
    created4 = set((r.json().get("data") or {}).get("created") or [])
    check("C-77-6 只启用设备模块：部门负责人照样预置（基础角色）",
          "department_head" in created4, str(sorted(created4)))
    check("C-77-6 只启用设备模块：维保员预置、检验员不预置",
          "maintenance_tech" in created4 and "inspector" not in created4,
          str(sorted(created4)))

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
