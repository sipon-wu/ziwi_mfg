#!/usr/bin/env python3
"""权限覆盖率只读审计 —— 切强制模式（PERMISSION_ENFORCE=true）前的体检。

**只读，不改任何数据、不改任何配置。** 回答一个问题：
> 现在把开关拨到强制模式，谁会突然进不去？

四条检查
--------
1. **路由码 vs 权限字典**：后端每条路由推导出的权限码，是否都在 ``permissions``
   表里。缺了的话，除了靠 ``*`` 通配的 admin，没人拿得到 —— 等于死功能。
2. **无人可用码**：某个权限码在所有角色里命中数为 0（不含 admin 的通配）。
   这类码切强制后必然 403，需要确认是有意收紧还是漏授。
3. **前端路由码 vs 后端码**：``router/index.ts`` 里 ``meta.perm`` 用的码，
   后端是否真的有对应接口。写了不存在的码 = 该页面除 admin 外永远进不去。
4. **角色 × 模块覆盖矩阵**：每个角色在每个模块上能覆盖多少条路由。

用法
----
    cd backend && ./.venv/Scripts/python.exe scripts/audit_permission_coverage.py
    ... --tenant mfg_demo --strict   # 有"无人可用码"时退出码非 0，可挂进 CI
"""
import argparse
import asyncio
import os
import re
import sys
from collections import defaultdict

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

ROUTER_TS = os.path.join(BACKEND_DIR, "..", "frontend", "src", "router", "index.ts")


def _load_route_codes():
    """后端：路由 → 权限码（走真实 app 的推导，不手写）。"""
    from app.core.permissions import build_permission_map
    from app.main import app

    return build_permission_map(app)


def _frontend_perms():
    """前端 router 里声明的 meta.perm（正则解析，够用且不引 TS 工具链）。"""
    path = os.path.abspath(ROUTER_TS)
    if not os.path.exists(path):
        return []
    src = open(path, encoding="utf-8").read()
    return sorted(set(re.findall(r"perm:\s*'([^']+)'", src)))


async def _roles_and_grants(tenant: str):
    """角色 → 授予的权限码列表（原始 pattern，含通配）。"""
    from sqlalchemy import text

    from app.core.database import get_db

    gen = get_db()
    session = await gen.__anext__()
    try:
        rows = (await session.execute(text(
            "SELECT r.id, r.code, r.name FROM roles r WHERE r.tenant_id = :t ORDER BY r.id"
        ), {"t": tenant})).fetchall()
        roles = [{"id": r[0], "code": r[1], "name": r[2]} for r in rows]

        grant_rows = (await session.execute(text(
            "SELECT rp.role_id, p.code FROM role_permissions rp "
            "JOIN permissions p ON p.id = rp.permission_id "
            "JOIN roles r ON r.id = rp.role_id WHERE r.tenant_id = :t"
        ), {"t": tenant})).fetchall()
        grants = defaultdict(list)
        for rid, code in grant_rows:
            grants[rid].append(code)

        dict_rows = (await session.execute(text(
            "SELECT code FROM permissions"
        ))).fetchall()
        permission_dict = {r[0] for r in dict_rows}
        return roles, grants, permission_dict
    finally:
        try:
            await gen.__anext__()
        except StopAsyncIteration:
            pass


def _can(granted, required: str) -> bool:
    from app.core.permissions import has_permission
    return has_permission(granted, required)


async def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tenant", default="mfg_demo")
    ap.add_argument("--strict", action="store_true",
                    help="存在无人可用的权限码时返回非 0")
    args = ap.parse_args()

    perm_map = _load_route_codes()
    required_codes = sorted(set(perm_map.values()))
    roles, grants, perm_dict = await _roles_and_grants(args.tenant)
    fe_perms = _frontend_perms()

    print(f"租户 {args.tenant}｜角色 {len(roles)} 个｜路由 {len(perm_map)} 条｜"
          f"不同权限码 {len(required_codes)} 个｜权限字典 {len(perm_dict)} 条")

    # failed = 硬阻塞（有它就一定不能切）；warned = 提醒（可能是有意为之）
    # 之前两者混用，导致『43 个 PLAT 平台管理码只给 admin』这种**有意设计**
    # 被当成阻塞项，结论永远打印"暂不建议切强制模式"—— 狼来了几次之后就没人看了。
    failed = False
    warned = False

    # ── 1. 路由码是否都在权限字典里 ──
    print("\n=== 1. 路由权限码 vs 权限字典 ===")
    missing = [c for c in required_codes if c not in perm_dict]
    if missing:
        failed = True
        print(f"  [FAIL] {len(missing)} 个码不在 permissions 表里（除 admin 外无人可用）：")
        by_mod = defaultdict(list)
        for c in missing:
            by_mod[c.split(":")[0]].append(c)
        for mod in sorted(by_mod):
            print(f"    {mod}: {', '.join(by_mod[mod])}")
    else:
        print(f"  [PASS] {len(required_codes)} 个路由权限码全部已在权限字典中")

    # ── 2. 无人可用码（不含 admin 通配） ──
    print("\n=== 2. 无人可用的权限码（去掉 admin 的通配后） ===")
    non_admin = [r for r in roles if r["code"] != "admin"]
    dead = []
    for code in required_codes:
        hit = [r["code"] for r in non_admin if _can(grants.get(r["id"], []), code)]
        if not hit:
            dead.append((code, len([p for p, c in perm_map.items() if c == code])))
    if dead:
        warned = True
        print(f"  [WARN] {len(dead)} 个码没有任何非 admin 角色命中 —— 切强制后这些接口只对 admin 开放：")
        by_mod = defaultdict(list)
        for code, n in dead:
            by_mod[code.split(":")[0]].append(f"{code}({n} 条路由)")
        for mod in sorted(by_mod):
            print(f"    {mod}: {', '.join(by_mod[mod])}")
    else:
        print("  [PASS] 每个路由权限码都至少有一个非 admin 角色命中")

    # ── 3. 前端路由码是否在后端存在 ──
    print("\n=== 3. 前端 meta.perm vs 后端权限码 ===")
    if not fe_perms:
        print("  [SKIP] 未找到前端 router 文件")
    else:
        orphan = [p for p in fe_perms if not any(
            _can([p], c) or _can([c], p) or c == p for c in required_codes)]
        if orphan:
            failed = True
            print(f"  [FAIL] {len(orphan)} 个前端页面的 perm 后端没有任何对应路由 —— "
                  f"该页面除 admin 外永远进不去：")
            for p in orphan:
                print(f"    {p}")
        else:
            print(f"  [PASS] 前端 {len(fe_perms)} 个页面权限码后端全部存在")

    # ── 4. 角色 × 模块覆盖矩阵 ──
    print("\n=== 4. 角色 × 模块 路由覆盖（可访问路由数 / 总数） ===")
    modules = sorted({c.split(":")[0] for c in required_codes})
    header = "角色".ljust(18) + "".join(m.ljust(9) for m in modules)
    print("  " + header)
    for r in roles:
        g = grants.get(r["id"], [])
        if r["code"] == "admin":
            g = list(g) + ["*"]
        cells = []
        for m in modules:
            total = [c for c in required_codes if c.startswith(m + ":")]
            ok = [c for c in total if _can(g, c)]
            cells.append(f"{len(ok)}/{len(total)}".ljust(9))
        print("  " + r["code"].ljust(18) + "".join(cells))
        print(f"  {'':18}" + "".join(m.ljust(9) for m in modules))

    # ── 结论 ──
    print("\n" + "=" * 70)
    if failed:
        print("结论：**有阻塞项，不能切强制模式**（见上面 [FAIL]）。")
        print("      灰度只能推迟问题，不会解决问题：/work-orders/、/judge 这类")
        print("      参数化路由一旦漏登记，强制模式下是**裸奔**而不是 403。")
    elif warned:
        print("结论：**无阻塞项**，可以保持强制模式。")
        print("      上面 [WARN] 的无人可用码若确属平台管理类（PLAT:*），有意只给")
        print("      admin 即可；若不属，则是某个角色少了能力，需要补授权。")
    else:
        print("结论：覆盖检查全部通过，强制模式可以全量生效。")
    return 1 if (failed and args.strict) else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
