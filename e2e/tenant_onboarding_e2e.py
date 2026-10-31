"""A-S1「开通租户 → 初始化管理员 → 首登改密」真实 HTTP 探针。

跑法（须后端已在 127.0.0.1:8000 运行）::

    cd backend && ./.venv/Scripts/python.exe ../e2e/tenant_onboarding_e2e.py

为什么非要跑真链而不是只看代码：清单把 A-S1 标成 ⚠️，理由是"建 tenants /
users / roles，写审计"。**实跑之前我判断不了它到底通不通** —— 而清单里
标 ⚠️ 的项已经被证伪过两次（C-S8 标 ⚠️ 其实早通、E-S1 标 ⚠️ 其实早通），
反过来也有标 ✅ 的整条链根本没工作过（C-56 E-S4）。所以判据只能是跑出来的数字。

本探针要证明的四件事：
1. 开通租户后**能建出管理员账号**（此前 POST /tenants 只插一行、不建账号）
2. 管理员**能用初始密码登录**，且登录响应带上 must_change_password=true
3. **未改密时写操作被拦、读操作放行**（首登改密是真的"强制"，不是提示）
4. **改密之后立刻能写**（改密后无需重新登录 —— 标志放在库里而非 JWT 里的收益）

★第 5 项刻意做成 [GAP] 而不是 [OK]：A-S1 要求的"写审计"**无处可写** ——
库里没有任何审计表（116 张表里没有 audit/操作日志类表）。这个缺口登记在
台账里等拍板，不在本探针里假装它是通的。
"""
from datetime import datetime

import httpx

from scenario_sweep_e2e import (API, TENANT, USER, PWD,
                                ok, gap, report, body, data, msg, summary)


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
    print("A-S1 开通租户 → 初始化管理员 → 首登改密")
    print("=" * 62)

    # ── A-S1-1 开通租户 ──
    tname = f"探针租户{tag}"
    r = c.post(f"{API}/tenants", json={
        "name": tname, "code": f"E2E{tag}", "contact_name": "探针",
        "contact_phone": "13800000000", "industry": "制造业", "region": "华东"})
    report("A-S1-1 开通租户", r.status_code in (200, 201), f"HTTP {r.status_code} {msg(r)[:60]}")
    if r.status_code not in (200, 201):
        summary()
        return 0

    # 租户编码是服务端生成的（schema 不收 tenant_id），必须回读
    r = c.get(f"{API}/tenants", params={"page": 1, "page_size": 100})
    items = (data(r) or {}).get("items") or []
    new_t = next((t for t in items if t.get("code") == f"E2E{tag}"), None)
    report("A-S1-2 新租户可读回", new_t is not None,
           f"tenant_id={new_t.get('tenant_id') if new_t else '未找到'}")
    if not new_t:
        summary()
        return 0
    tid = new_t["tenant_id"]

    # ── A-S1-3 初始化管理员 ──
    init_pwd = "Init@2026x"
    admin_user = f"adm{tag}"
    r = c.post(f"{API}/tenants/{tid}/init-admin", json={
        "username": admin_user, "password": init_pwd, "real_name": "探针管理员"})
    ok_init = report("A-S1-3 初始化管理员", r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:80]}")
    if r.status_code != 200:
        summary()
        return 0
    d = data(r)
    report("A-S1-4 建号同时绑了 admin 角色", bool(d.get("role_id")),
           f"user_id={d.get('user_id')} role_id={d.get('role_id')}")
    # 注：角色**归属**的跨租户校验无法用操作者(mfg_demo)的会话读 —— 多租户隔离
    # 本来就不该让他看到别的租户的角色（GET /roles/11 返回空是正确的）。
    # 归属已由查库确认（role 11 tenant_id=t_xxx is_system=1），这里改用
    # 新管理员自己的身份验证"角色确实继承下来了"，见下方 A-S1-8b。
    report("A-S1-5 初始密码置了首登改密标志", d.get("must_change_password") is True,
           f"must_change_password={d.get('must_change_password')}")

    # ── A-S1-6 重复初始化必须被拒（安全契约）──
    r = c.post(f"{API}/tenants/{tid}/init-admin", json={
        "username": f"other{tag}", "password": init_pwd})
    report("A-S1-6 重复初始化被拒（防密码重置后门）",
           r.status_code == 409, f"HTTP {r.status_code} {msg(r)[:60]}")

    # ── A-S1-7 用初始密码登录 ──
    c2 = httpx.Client(timeout=30)
    r = c2.post(f"{API}/auth/login", json={
        "username": admin_user, "password": init_pwd, "tenant_id": tid})
    ok_login = report("A-S1-7 管理员可用初始密码登录", r.status_code == 200,
                      f"HTTP {r.status_code} {msg(r)[:60]}")
    if r.status_code != 200:
        summary()
        return 0
    tok = body(r)["access_token"]
    flag = body(r).get("must_change_password")
    report("A-S1-8 登录响应回传首登改密标志", flag is True, f"must_change_password={flag}")
    c2.headers.update({"Authorization": f"Bearer {tok}", "X-Tenant-Id": tid})

    # ── A-S1-8b 新管理员确实继承了 admin 角色 ──
    r = c2.get(f"{API}/auth/me")
    me = data(r) or {}
    my_roles = [x.get("code") or x.get("name") for x in (me.get("roles") or [])]
    report("A-S1-8b ★新管理员继承了 admin 角色（角色真的绑上了）",
           "admin" in my_roles, f"tenant_id={me.get('tenant_id')} roles={my_roles}")

    # ── A-S1-9 未改密：写被拦 ──
    r = c2.post(f"{API}/wms/materials", json={
        "code": f"M-E2E-{tag}", "name": "探针物料",
        "unit": "PCS", "material_type": "raw"})
    blocked = r.status_code == 403 and "PWD-CHANGE-REQUIRED" in r.text
    report("A-S1-9 ★未改密时写操作被拦（强制而非提示）", blocked,
           f"HTTP {r.status_code} {msg(r)[:70]}")

    # ── A-S1-10 未改密：读放行 ──
    r = c2.get(f"{API}/auth/me")
    report("A-S1-10 未改密时读操作放行（不能把人关在门外）", r.status_code == 200,
           f"HTTP {r.status_code}")

    # ── A-S1-11 改密 ──
    new_pwd = "New@2026y"
    r = c2.post(f"{API}/auth/change-password",
                json={"old_password": init_pwd, "new_password": new_pwd})
    report("A-S1-11 改密成功", r.status_code == 200, f"HTTP {r.status_code} {msg(r)[:60]}")

    # ── A-S1-12 改密后立刻可写（不重新登录）──
    r = c2.post(f"{API}/wms/materials", json={
        "code": f"M-E2E-{tag}", "name": "探针物料",
        "unit": "PCS", "material_type": "raw"})
    report("A-S1-12 ★改密后无需重登即可写（标志在库不在 JWT）",
           r.status_code in (200, 201), f"HTTP {r.status_code} {msg(r)[:70]}")

    # ── A-S1-13 新密码可登录、且标志已清 ──
    c3 = httpx.Client(timeout=30)
    r = c3.post(f"{API}/auth/login", json={
        "username": admin_user, "password": new_pwd, "tenant_id": tid})
    report("A-S1-13 新密码可登录", r.status_code == 200, f"HTTP {r.status_code}")
    if r.status_code == 200:
        report("A-S1-14 改密后标志已清除", body(r).get("must_change_password") is False,
               f"must_change_password={body(r).get('must_change_password')}")

    # ── A-S1-15 审计无处可写（刻意记为 GAP，不假装通）──
    gap("A-S1-15 写审计：库里没有任何审计表（116 张表无 audit/操作日志类），"
        "需先建通用审计表才能闭环 —— 记台账待拍板，不在本轮顺手建")

    summary()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
