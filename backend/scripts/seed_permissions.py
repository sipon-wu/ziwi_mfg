#!/usr/bin/env python3
"""权限字典 + 角色权限种子（S1）。

做两件事
--------
1. **填 permissions 表**：从 ``build_permission_map(app)`` 自动推导出的权限码
   写入 ``permissions``（幂等 upsert by code）。当前该表 0 行。
2. **填 role_permissions**：按 ``ROLE_GRANTS`` 为本租户的角色授予权限。

角色授权的取值原则
------------------
**"行为不变"优先**：以现有前端硬编码（``router/index.ts`` 的 ``R_*`` 常量 +
``config/menu-permissions.ts``）为基准翻译，保证切换后用户看到的菜单与能进的页面不减少。
因此后端默认开启**影子模式**（``PERMISSION_ENFORCE=false``）：只记录"本该 403 但放行"，
不阻断。等影子日志确认为空后再切强制模式。

⚠️ 已知取舍（需产品拍板收紧）
------------------------------
以下模块在**当前前端路由上没有任何角色限制**（任何登录用户可访问），
本种子按"行为不变"原则保留这种开放性，但把写操作收敛到更合理的角色：

| 模块 | 现状 | 本种子 |
|:--|:--|:--|
| M00 基础数据 | 全开 | 读全开；写给 admin/dept_head/process_engineer/key_user |
| M04 仓储 WMS | 全开 | 读全开；写给 admin/dept_head/team_leader/scheduler/key_user |
| M05 安灯 | 全开 | 读全开；写给 admin/dept_head/team_leader/key_user/scheduler |

如需完全等价"全开"，把对应行的 ``_READ_ALL`` 改成 ``*`` 即可。

用法
----
    python backend/scripts/seed_permissions.py            # 全部租户
    python backend/scripts/seed_permissions.py mfg_demo   # 指定租户
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ── 角色授权模式与内置角色清单已迁至 app/constants/builtin_roles.py ──
# 为什么迁走：预置角色（租户开通 / 模块启用时补齐）与种子脚本必须用**同一份**
# 权限清单 —— 两处各写一份必然漂移（改一处忘另一处，表现为某个角色少一块功能，
# 而症状是"切强制模式后某个按钮 403"，根因极难反查）。
# 本脚本现在只负责"把清单写进库"，清单本身在常量模块里。
from app.constants.builtin_roles import (  # noqa: E402
    OPEN_MODULE_READ,
    PLATFORM_BASELINE,
    ROLE_GRANTS,
    resolve_pattern,
)


async def seed(only_tenant: str = None) -> dict:
    from sqlalchemy import text

    from app.core.database import get_engine
    from app.core.permissions import all_permission_codes, build_permission_map
    from app.main import app  # 触发路由注册，才能构建映射

    build_permission_map(app)
    codes = all_permission_codes()

    engine = get_engine()
    stats = {"permissions_upserted": 0, "tenants": 0, "role_grants": {}, "unmatched_roles": {}}

    async with engine.begin() as conn:
        # ── 1. 权限字典 upsert ──
        for code in codes:
            parts = code.split(":")
            module = parts[0] if len(parts) > 0 else "PLAT"
            resource = parts[1] if len(parts) > 1 else ""
            action = parts[2] if len(parts) > 2 else ""

            existing = await conn.execute(
                text("SELECT id FROM permissions WHERE code = :c"), {"c": code}
            )
            row = existing.fetchone()
            if row:
                await conn.execute(
                    text("""UPDATE permissions SET name = :n, module = :m,
                            resource_type = :r, action = :a WHERE code = :c"""),
                    {"n": f"{module} {resource} {action}", "m": module,
                     "r": resource, "a": action, "c": code},
                )
            else:
                await conn.execute(
                    text("""INSERT INTO permissions (code, name, module, resource_type, action)
                            VALUES (:c, :n, :m, :r, :a)"""),
                    {"c": code, "n": f"{module} {resource} {action}", "m": module,
                     "r": resource, "a": action},
                )
            stats["permissions_upserted"] += 1

        # 通配权限（'*' / 'M01:*' / '*:read' 等）不入 permissions 表——
        # 它们是"匹配模式"而非真实权限点，由 has_permission() 解释。
        # 但 admin 的 '*' 需要落库吗？不需要：guard 里对 admin 角色特殊处理。

        # ── 1b. 清理失效权限码 ──
        # 推导规则变更（如单数化修正）会产出新 code，旧 code 会变成孤儿并继续
        # 挂在 role_permissions 上。这里删除"不在当前映射中"的权限行
        # （role_permissions 有 ON DELETE CASCADE，会一并清掉关联）。
        valid = set(codes)
        existing_rows = await conn.execute(text("SELECT id, code FROM permissions"))
        stale_ids = [r[0] for r in existing_rows.fetchall() if r[1] not in valid]
        if stale_ids:
            for sid in stale_ids:
                await conn.execute(text("DELETE FROM permissions WHERE id = :i"), {"i": sid})
            stats["stale_removed"] = len(stale_ids)

        # ── 2. 按租户授予角色权限 ──
        if only_tenant:
            tenant_rows = [(only_tenant,)]
        else:
            res = await conn.execute(text("SELECT DISTINCT tenant_id FROM roles"))
            tenant_rows = [(r[0],) for r in res.fetchall()]

        # 预取权限码 → id
        perm_rows = await conn.execute(text("SELECT id, code FROM permissions"))
        code_to_id = {r[1]: r[0] for r in perm_rows.fetchall()}

        for (tenant_id,) in tenant_rows:
            stats["tenants"] += 1
            roles = await conn.execute(
                text("SELECT id, code FROM roles WHERE tenant_id = :t"), {"t": tenant_id}
            )
            for role_id, role_code in roles.fetchall():
                patterns = ROLE_GRANTS.get(role_code)
                if patterns is None:
                    stats["unmatched_roles"].setdefault(tenant_id, []).append(role_code)
                    continue

                # 把模式展开成真实权限码集合
                target_codes = set()
                for pattern in patterns:
                    resolved = resolve_pattern(pattern, set(code_to_id))
                    if not resolved:
                        # 精确码不存在 / 前缀没命中任何码：拼错或该端点已删除。
                        # 这里必须报出来 —— 否则切强制模式后会表现为"某个按钮 403"，
                        # 而根因是授权模式写错了（2026-10-30 就踩过：'PLAT:copilot_*'）。
                        stats["role_grants"].setdefault("_unresolved", []).append(pattern)
                    target_codes.update(resolved)

                # 重置该角色的权限（幂等）
                await conn.execute(
                    text("DELETE FROM role_permissions WHERE role_id = :r"), {"r": role_id}
                )
                for c in sorted(target_codes):
                    await conn.execute(
                        text("""INSERT INTO role_permissions (role_id, permission_id)
                                VALUES (:r, :p)"""),
                        {"r": role_id, "p": code_to_id[c]},
                    )
                stats["role_grants"][f"{tenant_id}/{role_code}"] = len(target_codes)

    await engine.dispose()
    return stats


def main() -> int:
    only = sys.argv[1] if len(sys.argv) > 1 else None
    stats = asyncio.run(seed(only))
    print(f"[done] 权限字典 {stats['permissions_upserted']} 条；租户 {stats['tenants']} 个")
    print("[roles] 各角色授予的权限点数：")
    for k, v in sorted(stats["role_grants"].items()):
        if k == "_unresolved":
            continue
        print(f"   {k:32s} {v}")
    if stats["role_grants"].get("_unresolved"):
        print("[warn] 未解析的权限模式:", sorted(set(stats["role_grants"]["_unresolved"])))
    if stats["unmatched_roles"]:
        print("[warn] 无授权规则的角色（租户内自定义角色，需手工配置）:")
        for t, rs in stats["unmatched_roles"].items():
            print(f"   {t}: {rs}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
