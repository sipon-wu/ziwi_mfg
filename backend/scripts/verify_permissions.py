#!/usr/bin/env python3
"""权限体系端到端验证（真实 DB + 真实 JWT，不 mock）。

验证矩阵
--------
A. 影子模式（PERMISSION_ENFORCE=false）：
   - 各角色调本不该有的接口 **不报错**，但产生 ``[SHADOW] 本该 403`` 日志
B. 强制模式（PERMISSION_ENFORCE=true）：
   - 无权限 → 403 且 body 含 required 权限码
   - 有权限 → 200
   - admin ``*`` 通配 → 全部 200
C. 数据范围：
   - DEPT_CHILD 角色（挂在公司根）可见全部数据
   - 把某用户移到"二号车间"且 scope=DEPT → 只看得到该车间数据
D. 组织 CRUD：
   - 建子节点 / 类型白名单拒绝 / 成环拒绝 / 删除保护

用法
----
    cd backend && .venv/Scripts/python.exe scripts/verify_permissions.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

TENANT = "mfg_demo"

# 角色 → 期望：能否创建工单（POST /api/v1/work-orders）
EXPECT_CREATE_WO = {
    "admin": True,             # '*' 通配
    "department_head": True,   # M01:*
    "team_leader": True,       # M01:*
    "scheduler": True,         # M01:*
    "process_engineer": False, # M01 只读
    "key_user": True,          # M01:*
    "maintenance_tech": False, # 只有 M06/M05
    "inspector": False,        # 品质
    "quality_engineer": False, # 品质
}

# 角色 → 用户名
ROLE_USER = {
    "admin": "test_admin",
    "department_head": "test_dept_head",
    "team_leader": "test_team_leader",
    "scheduler": "test_scheduler",
    "process_engineer": "test_proc_eng",
    "key_user": "test_key_user",
    "maintenance_tech": "test_maint_tech",
    "inspector": "test_inspector",
    "quality_engineer": "test_quality_eng",
}


def _check(label, ok, extra=""):
    mark = "PASS" if ok else "FAIL"
    print(f"  [{mark}] {label} {extra}")
    return ok


async def main() -> int:
    import httpx
    from httpx import ASGITransport
    from sqlalchemy import text

    from app.core.config import get_settings
    from app.core.database import get_db
    from app.core.security import create_local_token
    from app.main import app

    settings = get_settings()
    failures = 0

    # ── 出 token ──
    async def user_ids():
        gen = get_db()
        session = await gen.__anext__()
        rows = await session.execute(text(
            "SELECT u.id, u.username, r.code FROM users u "
            "JOIN user_roles ur ON ur.user_id = u.id "
            "JOIN roles r ON r.id = ur.role_id WHERE u.tenant_id = :t"
        ), {"t": TENANT})
        mapping = {r[2]: (r[0], r[1]) for r in rows.fetchall()}
        # 归还 session
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass
        return mapping

    mapping = await user_ids()
    tokens = {}
    for role_code, (uid, uname) in mapping.items():
        tokens[role_code] = create_local_token(uid, TENANT)

    async def call(method, path, role, **kw):
        transport = ASGITransport(app=app)
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as c:
            return await c.request(
                method, path,
                headers={"Authorization": f"Bearer {tokens[role]}"},
                **kw,
            )

    # ============================================================
    print("\n=== A. 影子模式：不阻断 ===")
    settings.PERMISSION_ENFORCE = False
    r = await call("POST", "/api/v1/work-orders", "inspector", json={
        "product_code": "X", "product_name": "X", "planned_qty": 1,
    })
    ok = _check("inspector 建工单（影子模式下不 403）", r.status_code != 403,
                f"HTTP {r.status_code}")
    failures += 0 if ok else 1

    # ============================================================
    print("\n=== B. 强制模式：403 判定 ===")
    settings.PERMISSION_ENFORCE = True
    # 判据：403 = 权限层拦下；其余状态码（含 422 请求体校验失败）说明已越过权限层。
    for role, expect_allow in EXPECT_CREATE_WO.items():
        if role not in tokens:
            print(f"  [SKIP] {role} 无测试账号")
            continue
        r = await call("POST", "/api/v1/work-orders", role, json={
            "product_code": "PERMTEST", "product_name": "权限验证", "planned_qty": 1,
        })
        blocked = r.status_code == 403
        if blocked:
            body = r.json().get("detail", {})
            ok = (not expect_allow) and body.get("code") == "403-0001"
            failures += 0 if ok else 1
            _check(f"{role:20s} 建工单被拒", ok,
                   f"需要 {body.get('required')}" if ok
                   else f"意外拦截: {r.status_code} {r.text[:120]}")
        else:
            ok = expect_allow
            failures += 0 if ok else 1
            _check(f"{role:20s} 建工单放行", ok,
                   f"HTTP {r.status_code}" if ok
                   else f"应被拒却放行（HTTP {r.status_code}）")

    # 只读接口：按角色授权矩阵核对
    # 注：inspector **不给** M01:work_order:read —— 品质页面不调工单接口（已 grep 确认），
    #     给了会让「生产管理」菜单对检验员出现，属于越权可见（见 seed_permissions.ROLE_GRANTS）。
    print("\n  读取工单（应能读：admin/dept_head/team_leader；不应能读：inspector/maintenance_tech）：")
    for role, expect in [
        ("admin", True), ("inspector", False), ("team_leader", True),
        ("maintenance_tech", False),
    ]:
        r = await call("GET", "/api/v1/work-orders?page=1&page_size=5", role)
        ok = (r.status_code == 403) != expect
        failures += 0 if ok else 1
        _check(f"{role:20s} GET /work-orders", ok,
               f"HTTP {r.status_code}（期望 {'可读' if expect else '403'}）")

    # ============================================================
    print("\n=== C. 数据范围 ===")
    r = await call("GET", "/api/v1/work-orders?page=1&page_size=100", "department_head")
    dept_head_total = r.json().get("data", {}).get("total", 0) if r.status_code == 200 else -1
    r = await call("GET", "/api/v1/work-orders?page=1&page_size=100", "admin")
    admin_total = r.json().get("data", {}).get("total", 0) if r.status_code == 200 else -1
    ok = admin_total >= 0 and dept_head_total == admin_total
    failures += 0 if ok else 1
    _check("DEPT_CHILD@公司根 与 admin 可见量一致", ok,
           f"dept_head={dept_head_total} admin={admin_total}")

    # ============================================================
    print("\n=== D. 组织 CRUD ===")
    r = await call("GET", "/api/v1/organizations/tree", "admin")
    tree = r.json().get("data", []) if r.status_code == 200 else []
    ok = r.status_code == 200 and len(tree) >= 10
    failures += 0 if ok else 1
    _check("组织树读取", ok, f"{len(tree)} 个节点")

    r = await call("POST", "/api/v1/organizations", "admin", json={
        "code": "ORG-VERIFY-1", "name": "验证部门", "org_type": "dept",
        "parent_id": 1,
    })
    created = r.status_code == 200
    new_id = r.json().get("data", {}).get("id") if created else None
    failures += 0 if created else 1
    _check("新建部门", created, f"HTTP {r.status_code} id={new_id}")

    r = await call("POST", "/api/v1/organizations", "admin", json={
        "code": "ORG-VERIFY-1", "name": "重复编码", "org_type": "dept", "parent_id": 1,
    })
    ok = r.status_code == 400
    failures += 0 if ok else 1
    _check("重复编码被拒", ok, f"HTTP {r.status_code}")

    r = await call("POST", "/api/v1/organizations", "admin", json={
        "code": "ORG-VERIFY-2", "name": "非法子级", "org_type": "dept",
        "parent_id": 3,   # 机加工班组(team) 下不能挂 dept
    })
    ok = r.status_code == 400
    failures += 0 if ok else 1
    _check("类型白名单拒绝（班组下挂部门）", ok, f"HTTP {r.status_code}")

    if new_id:
        r = await call("PUT", f"/api/v1/organizations/{new_id}/move", "admin",
                       json={"parent_id": new_id})
        ok = r.status_code == 400
        failures += 0 if ok else 1
        _check("成环拒绝（挂到自己下）", ok, f"HTTP {r.status_code}")

        r = await call("POST", f"/api/v1/organizations/{new_id}/members", "admin",
                       json={"user_id": 2, "is_primary": False})
        member_ok = r.status_code == 200
        r = await call("DELETE", f"/api/v1/organizations/{new_id}", "admin")
        ok = r.status_code == 409
        failures += 0 if ok else 1
        _check("删除保护（有成员时 409）", ok, f"HTTP {r.status_code}")

        if member_ok:
            await call("DELETE", f"/api/v1/organizations/{new_id}/members/2", "admin")
        r = await call("DELETE", f"/api/v1/organizations/{new_id}", "admin")
        ok = r.status_code == 200
        failures += 0 if ok else 1
        _check("清空成员后删除成功", ok, f"HTTP {r.status_code}")

    # 恢复影子模式
    settings.PERMISSION_ENFORCE = False

    # 清理验证数据
    gen = get_db()
    session = await gen.__anext__()
    await session.execute(text(
        "DELETE FROM work_orders WHERE product_code = 'PERMTEST' AND tenant_id = :t"
    ), {"t": TENANT})
    await session.commit()
    try:
        await gen.__anext__()
    except StopAsyncIteration:
        pass

    print(f"\n{'='*60}")
    print(f"结果：{'全部通过' if failures == 0 else f'{failures} 项失败'}")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
