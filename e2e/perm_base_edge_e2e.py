"""平台底座（组织/角色/用户/权限）边界场景端到端验证（真实 HTTP）。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/perm_base_edge_e2e.py

覆盖场景（``docs/scenario-inventory-2026-10-29.md`` A 区，BACKLOG C-74）：

    A-E1  删除有下级的组织节点 → 409 并点名子组织数；子节点清了才能删
    A-E2  删除仍被用户引用的角色 → 409 并点名成员数；成员移出后才能删
    A-E3  权限变更即时生效 → 同一 token，改权限前 200、清空后立刻 403
          （权限是每请求现查，不是登录时烤进 token）
    A-E4  停用名下有在办单据的用户 → 409 列出「工单 N 张」等明细；
          force=true 可强制停用并写审计留痕
    A-B1  用户无任何角色 → 能登录、/auth/me 正常、业务接口 403 且指明缺哪个权限
    A-B2  角色权限为空 → 同上（不能 500，也不能默默放行）
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

    def login(username, password):
        cli = httpx.Client(timeout=25)
        r = cli.post(f"{API}/auth/login", json={
            "username": username, "password": password, "tenant_id": TENANT})
        if r.status_code == 200:
            cli.headers.update({
                "Authorization": f"Bearer {r.json()['access_token']}",
                "X-Tenant-Id": TENANT})
        return r, cli

    # ══════════════════════════════════════════════════════
    # A-E1 删除有下级的组织节点
    # ══════════════════════════════════════════════════════
    print("── A-E1 组织树删除边界 ──")
    r = c.post(f"{API}/organizations", json={
        "name": f"父组织{tag}", "code": f"ORG-P-{tag}", "org_type": "company"})
    parent = (r.json().get("data") or {}).get("id")
    r = c.post(f"{API}/organizations", json={
        "name": f"子组织{tag}", "code": f"ORG-C-{tag}",
        "org_type": "dept", "parent_id": parent})
    child = (r.json().get("data") or {}).get("id")
    check("A-E1 前置：父子组织建好",
          r.status_code == 200 and parent and child, f"parent={parent} child={child}")

    r = c.delete(f"{API}/organizations/{parent}")
    check("A-E1 删有子节点的组织 → 409 且点名子组织数",
          r.status_code == 409 and "1 个子组织" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:60]}")
    r = c.get(f"{API}/organizations/{parent}")
    check("A-E1 被拒后父组织仍在（没被级联删掉）",
          r.status_code == 200, f"HTTP {r.status_code}")

    c.delete(f"{API}/organizations/{child}")
    r = c.delete(f"{API}/organizations/{parent}")
    check("A-E1 子节点清掉后可删父节点",
          r.status_code == 200, f"HTTP {r.status_code} {err_msg(r)[:60]}")

    # ══════════════════════════════════════════════════════
    # A-E2 删除仍有成员的角色
    # ══════════════════════════════════════════════════════
    print("\n── A-E2 角色删除边界 ──")
    r = c.post(f"{API}/roles", json={
        "name": f"临时角色{tag}", "code": f"role_tmp_{tag}"})
    role = (r.json().get("data") or {}).get("id")
    r = c.post(f"{API}/users", json={
        "username": f"tmpu{tag}", "password": "Test@12345",
        "real_name": f"临时用户{tag}", "role_ids": [role]})
    uid = (r.json().get("data") or {}).get("id")
    check("A-E2 前置：角色与成员建好",
          r.status_code == 200 and role and uid, f"role={role} user={uid}")

    r = c.delete(f"{API}/roles/{role}")
    check("A-E2 删仍有成员的角色 → 409 且点名成员数",
          r.status_code == 409 and "1 名成员" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:60]}")

    c.put(f"{API}/users/{uid}", json={"role_ids": []})
    r = c.delete(f"{API}/roles/{role}")
    check("A-E2 成员移出后可删角色",
          r.status_code == 200, f"HTTP {r.status_code} {err_msg(r)[:60]}")

    # ══════════════════════════════════════════════════════
    # A-E3 权限变更即时生效
    # ══════════════════════════════════════════════════════
    print("\n── A-E3 权限变更即时生效 ──")
    r = c.post(f"{API}/roles", json={
        "name": f"只读角色{tag}", "code": f"role_ro_{tag}"})
    ro_role = (r.json().get("data") or {}).get("id")
    c.put(f"{API}/roles/{ro_role}/permissions",
          json={"permission_codes": ["M00:product:read"]})
    r = c.post(f"{API}/users", json={
        "username": f"rouser{tag}", "password": "Test@12345",
        "real_name": f"只读用户{tag}", "role_ids": [ro_role]})
    ro_uid = (r.json().get("data") or {}).get("id")

    lr, cli = login(f"rouser{tag}", "Test@12345")
    check("A-E3 前置：受限用户可登录", lr.status_code == 200, f"HTTP {lr.status_code}")
    r = cli.get(f"{API}/products", params={"page": 1, "page_size": 5})
    check("A-E3 有该权限时可读产品", r.status_code == 200, f"HTTP {r.status_code}")

    # 关键：**不重新登录**，同一个 token
    c.put(f"{API}/roles/{ro_role}/permissions", json={"permission_codes": []})
    r = cli.get(f"{API}/products", params={"page": 1, "page_size": 5})
    check("A-E3 清空权限后同一 token 立刻 403（不靠 token 过期）",
          r.status_code == 403 and "M00:product:read" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:60]}")

    # 反向：加回权限也应立刻生效
    c.put(f"{API}/roles/{ro_role}/permissions",
          json={"permission_codes": ["M00:product:read"]})
    r = cli.get(f"{API}/products", params={"page": 1, "page_size": 5})
    check("A-E3 权限加回后同一 token 立刻恢复 200",
          r.status_code == 200, f"HTTP {r.status_code}")

    # ══════════════════════════════════════════════════════
    # A-E4 停用名下有在办单据的用户
    # ══════════════════════════════════════════════════════
    print("\n── A-E4 停用有在办单据的用户 ──")
    r = c.post(f"{API}/users", json={
        "username": f"busyu{tag}", "password": "Test@12345",
        "real_name": f"在办用户{tag}"})
    busy_uid = (r.json().get("data") or {}).get("id")
    r = c.post(f"{API}/work-orders", json={
        "wo_no": f"WO-A4-{tag}", "product_code": f"P-A4-{tag}",
        "product_name": f"产品A4{tag}", "planned_qty": 5,
        "assignee_id": busy_uid})
    wo_id = (r.json().get("data") or {}).get("id")
    check("A-E4 前置：建一张派给他的工单", r.status_code == 200, f"wo={wo_id}")
    c.post(f"{API}/work-orders/{wo_id}/release",
           json={"force_release": True, "force_reason": "A-E4 探针"})

    r = c.put(f"{API}/users/{busy_uid}", json={"status": "inactive"})
    check("A-E4 有在办工单 → 停用被拒 409 且点名工单数",
          r.status_code == 409 and "工单" in err_msg(r) and "1 张" in err_msg(r),
          f"HTTP {r.status_code} msg={err_msg(r)[:90]}")
    r = c.get(f"{API}/users/{busy_uid}")
    check("A-E4 被拒后用户仍是启用状态",
          (r.json().get("data") or {}).get("status") == "active",
          f"status={(r.json().get('data') or {}).get('status')}")

    # 换个状态值同样拦（disabled / locked 都属停用类）
    r = c.put(f"{API}/users/{busy_uid}", json={"status": "disabled"})
    check("A-E4 disabled 同样被拦（不只认 inactive）",
          r.status_code == 409, f"HTTP {r.status_code}")

    r = c.put(f"{API}/users/{busy_uid}",
              json={"status": "inactive", "force": True})
    forced = (r.json().get("data") or {}).get("forced_open_documents") or []
    check("A-E4 force=true 可强制停用并回带在办单据清单",
          r.status_code == 200 and forced and forced[0].get("type") == "工单",
          f"HTTP {r.status_code} forced={forced}")
    r = c.get(f"{API}/audit-logs", params={"action": "user.force_disable",
                                           "page_size": 5})
    check("A-E4 强制停用写审计留痕",
          r.status_code == 200 and len(r.json().get("data", {}).get("items", [])) >= 1,
          f"hits={len(r.json().get('data', {}).get('items', []))}")

    # 无在办单据的正常停用
    r = c.post(f"{API}/users", json={
        "username": f"idleu{tag}", "password": "Test@12345",
        "real_name": f"空闲用户{tag}"})
    idle_uid = (r.json().get("data") or {}).get("id")
    r = c.put(f"{API}/users/{idle_uid}", json={"status": "inactive"})
    check("A-E4 无在办单据 → 正常停用不受影响",
          r.status_code == 200, f"HTTP {r.status_code} {err_msg(r)[:60]}")

    # ══════════════════════════════════════════════════════
    # A-B1 用户无任何角色
    # ══════════════════════════════════════════════════════
    print("\n── A-B1 无角色用户登录 ──")
    c.post(f"{API}/users", json={
        "username": f"norole{tag}", "password": "Test@12345",
        "real_name": f"无角色{tag}"})
    lr, n = login(f"norole{tag}", "Test@12345")
    check("A-B1 无角色也能登录（不是登录就炸）",
          lr.status_code == 200, f"HTTP {lr.status_code}")
    r = n.get(f"{API}/auth/me")
    me = r.json().get("data") or {}
    check("A-B1 /auth/me 正常返回（菜单可据此渲染成空）",
          r.status_code == 200 and me.get("username") == f"norole{tag}",
          f"HTTP {r.status_code} username={me.get('username')}")
    r = n.get(f"{API}/products", params={"page": 1, "page_size": 5})
    check("A-B1 业务接口 403 且指明缺哪个权限（不是 500/不是放行）",
          r.status_code == 403 and (r.json().get("detail") or {}).get("required"),
          f"HTTP {r.status_code} required={(r.json().get('detail') or {}).get('required')}")

    # ══════════════════════════════════════════════════════
    # A-B2 角色权限为空
    # ══════════════════════════════════════════════════════
    print("\n── A-B2 角色权限为空 ──")
    r = c.post(f"{API}/roles", json={
        "name": f"空权限角色{tag}", "code": f"role_empty_{tag}"})
    empty_role = (r.json().get("data") or {}).get("id")
    c.put(f"{API}/roles/{empty_role}/permissions", json={"permission_codes": []})
    r = c.post(f"{API}/users", json={
        "username": f"emptyu{tag}", "password": "Test@12345",
        "real_name": f"空权限用户{tag}", "role_ids": [empty_role]})
    empty_uid = (r.json().get("data") or {}).get("id")

    lr, e = login(f"emptyu{tag}", "Test@12345")
    check("A-B2 空权限角色成员可登录", lr.status_code == 200, f"HTTP {lr.status_code}")
    r = c.get(f"{API}/roles/{empty_role}/permissions")
    check("A-B2 角色权限确为空（前置条件成立）",
          r.status_code == 200 and not (r.json().get("data") or []),
          f"perms={r.json().get('data')}")
    r = e.get(f"{API}/work-orders", params={"page": 1, "page_size": 5})
    check("A-B2 空权限越权 → 403 且指明缺哪个权限",
          r.status_code == 403 and (r.json().get("detail") or {}).get("required"),
          f"HTTP {r.status_code} required={(r.json().get('detail') or {}).get('required')}")

    print("\n" + "=" * 56)
    print(f"PASS {len(PASS)} / FAIL {len(FAIL)}")
    if FAIL:
        for f in FAIL:
            print(f"  FAILED: {f}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
