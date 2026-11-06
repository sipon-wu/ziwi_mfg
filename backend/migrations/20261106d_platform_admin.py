#!/usr/bin/env python3
"""平台管理员与租户管理员分离（幂等）。

## 要解决的问题

`permission_guard` 里有一条硬编码：用户任一角色 `code == 'admin'` → 追加 `*`。
而 `admin` 在每个租户各有一份，于是**每个租户的管理员都拿到全局通配**：

    租户 A 的 admin  →  GET /api/v1/tenants  →  平台全部 123 个租户
                       含 contact_name / contact_phone / package_modules / license_status

这不是"`GET /tenants` 漏了租户过滤"——`tenants` 是租户主表，加过滤会让接口
只会返回自己一条，功能直接废掉。真正的问题是**租户级管理员与平台级管理员
从来没分开过**。

## 改法（三件事，缺一不可）

1. `core/permissions.py` 里定义 `PLATFORM_OPS_PERMISSIONS`（6 个能跨出租户边界
   的码），并让 `has_permission` 对这 6 个码**不吃任何通配**，只认精确授权。

2. 建 `platform_admin` 角色（`is_system=True` / `scope=ALL`），给它授这 6 个码。

3. ★ **删掉其他所有角色对这 6 个码的授权**。
   这一步最容易被漏掉：只做第 1 步的话，`role_permissions` 里那些显式授权
   仍然会通过 `required in perms` 命中 —— `*` 被堵死了，侧门还开着。
   本项目历史上 `sync_permissions` 给 admin 落过这些码（实测 staging 85 条
   `PLAT:tenant:read`），所以必须显式清理。

## 谁会拿到 platform_admin

`SEED_ACCOUNTS` 里两个是**实施/运维账号**，不是客户业务账号：

* `ah_admin`  —— staging 靶场运维主账号
* `mfg_admin` —— 种子超级账号，86 个 E2E 探针都靠它，且 4 个探针 + 2 个脚本
                依赖 `GET /tenants` 列全量去找刚建的租户

**不给它们等于当场打断回归**，而它们本来就在做运维的事。真正的客户租户管理员
不会被授这个角色 —— 角色实体存在于每个租户不构成漏洞，**授权给谁**才构成。

## 用法

    cd backend && ./.venv/Scripts/python.exe migrations/20261106d_platform_admin.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

ROLE_CODE = "platform_admin"
ROLE_NAME = "平台管理员"
ROLE_DESC = "跨租户的平台运营权限（开通/列出/修改租户、读 license、预置角色）。不属于客户业务角色。"

PLATFORM_OPS = [
    "PLAT:tenant:create",
    "PLAT:tenant:read",
    "PLAT:tenant:update",
    "PLAT:tenant:execute",
    "PLAT:tenant_license:read",
    "PLAT:tenant_preset_role:create",
]

SEED_ACCOUNTS = ("ah_admin", "mfg_admin")


async def apply() -> str:
    from sqlalchemy import text

    from app.core.database import get_engine

    engine = get_engine()
    lines: list[str] = []

    async with engine.begin() as conn:
        # ── 0. 表就位 ──────────────────────────────────────────
        need = {"permissions", "role_permissions", "roles", "user_roles", "tenants", "users"}
        have = set()
        for t in need:
            r = await conn.execute(text(
                "SELECT 1 FROM information_schema.tables WHERE table_name = :t"
                if conn.dialect.name == "postgresql"
                else "SELECT 1 FROM sqlite_master WHERE type='table' AND name = :t"
            ), {"t": t})
            if r.first():
                have.add(t)
        missing = need - have
        if missing:
            return f"  缺少表 {sorted(missing)}，跳过"

        # 自检：代码里的名单与本脚本必须一致，不一致就停下来（两份真源会漂）。
        # 这份名单同时决定"谁被堵死"，写错一个字就是漏一个越权口子。
        from app.core.permissions import PLATFORM_OPS_PERMISSIONS
        only_script = sorted(set(PLATFORM_OPS) - set(PLATFORM_OPS_PERMISSIONS))
        only_code = sorted(set(PLATFORM_OPS_PERMISSIONS) - set(PLATFORM_OPS))
        if only_script or only_code:
            return ("  [STOP] 本脚本的 PLATFORM_OPS 与 core/permissions.py::"
                    "PLATFORM_OPS_PERMISSIONS 不一致：\n"
                    f"    脚本多出 {only_script}\n"
                    f"    脚本缺少 {only_code}\n"
                    "    先让两处一致再跑 —— 名单漂了就等于漏了越权口子。")

        # ── 1. 取 6 个平台运营码的 id ──────────────────────────
        pid: dict[str, int] = {}
        for code in PLATFORM_OPS:
            row = (await conn.execute(
                text("SELECT id FROM permissions WHERE code = :c"), {"c": code}
            )).first()
            if row:
                pid[code] = int(row[0])
            else:
                lines.append(f"  ⚠ {code} 尚未建码（sync_permissions 没跑到？），本次跳过该码")

        if not pid:
            return "  6 个平台运营码一个都不存在，无可执行动作（先跑 sync_permissions）"

        # ── 2. 每个租户建 platform_admin 角色 ──────────────────
        tenant_ids = [r[0] for r in (await conn.execute(text(
            "SELECT DISTINCT tenant_id FROM roles ORDER BY tenant_id"
        ))).fetchall() if r[0]]
        created = 0
        for tid in tenant_ids:
            exists = (await conn.execute(text(
                "SELECT id FROM roles WHERE tenant_id = :t AND code = :c"
            ), {"t": tid, "c": ROLE_CODE})).first()
            if exists:
                continue
            await conn.execute(text(
                "INSERT INTO roles (tenant_id, name, code, description, is_system, scope) "
                "VALUES (:t, :n, :c, :d, :sys, :scope)"
            ), {"t": tid, "n": ROLE_NAME, "c": ROLE_CODE, "d": ROLE_DESC,
                "sys": True, "scope": "ALL"})
            created += 1
        lines.append(f"  platform_admin 角色：新建 {created} 个 / 已存在 "
                     f"{len(tenant_ids) - created} 个（租户数 {len(tenant_ids)}）")

        pa_role_ids = [int(r[0]) for r in (await conn.execute(text(
            "SELECT id FROM roles WHERE code = :c"
        ), {"c": ROLE_CODE})).fetchall()]

        if not pa_role_ids:
            return "\n".join(lines + ["  platform_admin 角色一个都没建出来，后续步骤跳过"])

        # ── 3. ★ 清理：删除其他角色对这 6 个码的授权 ────────────
        # 只做 has_permission 的改动是不够的：显式授权仍会通过 `required in perms`。
        id_list = ",".join(str(i) for i in pid.values())
        role_list = ",".join(str(i) for i in pa_role_ids)
        res = await conn.execute(text(
            f"DELETE FROM role_permissions "
            f"WHERE permission_id IN ({id_list}) AND role_id NOT IN ({role_list})"
        ))
        lines.append(f"  清理：删除非平台管理员角色对这 6 个码的授权 {res.rowcount} 条")

        # ── 4. 授权 platform_admin ─────────────────────────────
        granted = 0
        for rid in pa_role_ids:
            for code, pidv in pid.items():
                r = await conn.execute(text(
                    "INSERT INTO role_permissions (role_id, permission_id) "
                    "SELECT :rid, :pid WHERE NOT EXISTS ("
                    "  SELECT 1 FROM role_permissions x "
                    "  WHERE x.role_id = :rid AND x.permission_id = :pid)"
                ), {"rid": rid, "pid": pidv})
                granted += max(r.rowcount or 0, 0)
        lines.append(f"  授权：platform_admin × {len(pa_role_ids)} 个角色 × "
                     f"{len(pid)} 个码 → 新增 {granted} 条")

        # ── 5. 把角色授给运维/实施账号 ─────────────────────────
        bound = 0
        for uname in SEED_ACCOUNTS:
            urow = (await conn.execute(text(
                "SELECT id, tenant_id FROM users WHERE username = :u"
            ), {"u": uname})).first()
            if not urow:
                lines.append(f"  账号 {uname} 不存在，跳过")
                continue
            uid, utid = int(urow[0]), urow[1]
            rrow = (await conn.execute(text(
                "SELECT id FROM roles WHERE tenant_id = :t AND code = :c"
            ), {"t": utid, "c": ROLE_CODE})).first()
            if not rrow:
                lines.append(f"  账号 {uname} 所属租户 {utid} 无 platform_admin 角色，跳过")
                continue
            r = await conn.execute(text(
                "INSERT INTO user_roles (user_id, role_id, tenant_id) "
                "SELECT :uid, :rid, :tid WHERE NOT EXISTS ("
                "  SELECT 1 FROM user_roles x WHERE x.user_id = :uid AND x.role_id = :rid)"
            ), {"uid": uid, "rid": int(rrow[0]), "tid": utid})
            if (r.rowcount or 0) > 0:
                bound += 1
                lines.append(f"  绑定 {uname} → platform_admin")
        if not bound:
            lines.append(f"  账号绑定：{SEED_ACCOUNTS} 均已绑定或无匹配")

    return "\n".join(lines) if lines else "无需变更"


async def main():
    print("迁移：平台管理员与租户管理员分离")
    try:
        result = await apply()
    except Exception as e:  # 不阻断部署
        print(f"[WARN] 迁移未成功（不阻断）：{e}")
        return 0
    print(f"完成：\n{result}")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
