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
import re
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

# ── 当前前端"完全放开"的模块（路由无 roles 限制）──
# 这些模块所有登录用户都看得见，故所有角色至少要有只读权限，
# 否则切换强制模式后"菜单还在、点进去 403"。
OPEN_MODULE_READ = ["M00:*:read", "M04:*:read", "M05:*:read"]

# ── 角色 → 权限模式列表 ──
# 支持四种写法：
#   '*'                全部
#   'M01:*'            整个模块
#   'M01:work_order:*' 某资源全部动作
#   'M03:*:read'       模块内只读
ROLE_GRANTS = {
    "admin": ["*"],

    # 部门负责人：生产 / 排产 / BOM / 设备 / 品质 / 能碳 / 采集 / 系统 / 试产 / 实验室 / NCR
    # 依据：R_PROD R_SCHEDULE R_BOMS R_EQUIP R_QUALITY R_ENERGY R_DC R_SYSTEM R_TRIAL
    #       + menu: andon.escalation_rules / trial / lab
    # PLAT:role_permission:read —— 角色权限配置页的**只读**查看（含权限目录），可看不可改
    "department_head": OPEN_MODULE_READ + [
        "M01:*", "M02:*", "M03:*", "M06:*", "M10:*",
        "M11:*", "M12:*", "M15:*", "M16:*", "M30:*",
        "PLAT:organization:*", "PLAT:user:read", "PLAT:role:read",
        "PLAT:role_permission:read",
    ],

    # 班组长：生产（工单/报工/排产）+ 设备 + 安灯处理
    # 依据：R_PROD R_EQUIP + 安灯主菜单全开
    "team_leader": OPEN_MODULE_READ + [
        "M01:*", "M06:*", "M05:*",
    ],

    # 生产调度员：工单 + 排产（不看 BOM / 品质 / 设备写操作）
    # 依据：R_PROD R_SCHEDULE
    "scheduler": OPEN_MODULE_READ + [
        "M01:*", "M06:*:read",
    ],

    # 工艺工程师：BOM + FMEA + 试产（生产只读，不排产）
    # 依据：R_PROD R_BOMS R_FMEA R_TRIAL + menu: lab
    "process_engineer": OPEN_MODULE_READ + [
        "M01:*:read", "M02:*", "M10:fmea*:*", "M16:*", "M15:*",
    ],

    # 关键用户：生产 + 品质 + 能碳 + 采集 + 系统配置
    # 依据：R_PROD R_QUALITY R_ENERGY R_DC R_SYSTEM
    # PLAT:role_permission / role_scope / role_user —— 系统管理下的角色权限配置页三件套
    #   （`PLAT:role:*` 只覆盖 /roles 本身，不覆盖 /roles/{id}/permissions 这类子资源）
    "key_user": OPEN_MODULE_READ + [
        "M01:*", "M03:*", "M05:*", "M11:*", "M12:*",
        "PLAT:user:*", "PLAT:role:*",
        "PLAT:role_permission:*", "PLAT:role_scope:*", "PLAT:role_user:*",
        "PLAT:organization:*", "PLAT:dictionary:*",
    ],

    # 设备维保员：设备 + 安灯
    # 依据：R_EQUIP
    "maintenance_tech": OPEN_MODULE_READ + [
        "M06:*", "M05:*",
    ],

    # 品质检验员：检验 / NCR / 实验室
    # 依据：R_QUALITY + menu: lab（含 lab_standards）
    # 注：不给 M01:work_order:read —— 品质页面不调工单接口（已 grep 确认），
    #     给了会让「生产管理」菜单对检验员出现，属于越权可见。
    "inspector": OPEN_MODULE_READ + [
        "M03:inspection_order:*", "M03:inspection_result:*",
        "M03:inspection_item:*", "M03:inspection_standard:*", "M03:qc_point:read",
        "M30:*", "M15:*",
    ],

    # 品质工程师：品质全量 + SPC/FMEA/PPAP + NCR + 实验室
    # 依据：R_QUALITY R_SPC R_PPAP R_FMEA + menu: lab
    "quality_engineer": OPEN_MODULE_READ + [
        "M03:*", "M10:*", "M30:*", "M15:*",
    ],
}


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
                    if pattern == "*":
                        target_codes.update(code_to_id.keys())
                    elif pattern.startswith("*:"):
                        # '*:read' → 全平台该动作（必须先于 endswith(':*') 判断，
                        # 否则 '*:read' 会掉进精确匹配分支而解析失败）
                        act = pattern.split(":", 1)[1]
                        target_codes.update(
                            c for c in code_to_id if c.endswith(f":{act}")
                        )
                    elif pattern.endswith(":*"):
                        prefix = pattern[:-1]  # 'M01:' / 'M01:work_order:'
                        target_codes.update(
                            c for c in code_to_id if c.startswith(prefix)
                        )
                    elif re.match(r"^[A-Za-z0-9_]+:\*:[a-z_]+$", pattern):
                        # 'M03:*:read' → 模块内某动作（该模块只读）
                        mod, _, act = pattern.split(":")
                        target_codes.update(
                            c for c in code_to_id
                            if c.startswith(f"{mod}:") and c.endswith(f":{act}")
                        )
                    else:
                        if pattern in code_to_id:
                            target_codes.add(pattern)
                        else:
                            # 精确码不存在：说明拼错或该端点已删除，记录下来
                            stats["role_grants"].setdefault("_unresolved", []).append(pattern)

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
