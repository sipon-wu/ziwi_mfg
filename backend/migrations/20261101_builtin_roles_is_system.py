#!/usr/bin/env python3
"""内置角色回填 `is_system=1`（幂等，C-77）。

背景
----
2026-11-01 拍板「角色最基本可以预置，其它随模块预置」。落地上有两个问题要一起解：

1. **新租户**：开通时只建 admin，其余 8 个业务角色从来没有 —— 客户面对空角色
   列表，最后都拿 admin 账号跑业务，权限体系名存实亡。已在
   `TenantService.preset_roles` 补上（基础角色随开通、模块角色随模块启用）。
2. **存量租户**：那 8 个角色是 `seeds/mfg1_e2e_seed_data.py`（测试数据脚本）
   建的，`is_system` 落 NULL → `RoleService.delete` 的"系统内置角色不可删除"
   守卫对它们**不生效**，客户在界面上能把「品质检验员」删掉。而
   `seed_permissions.py` 按 code 授权，删掉后重跑只会报 `unmatched_roles`，
   **不会重建** —— 于是这个岗位从此永久缺失，只能手工补。

本迁移只做第 2 件事：把 `builtin_roles.BUILTIN_ROLE_CODES` 覆盖的角色行
`is_system` 置 1。**不建角色、不动权限**（那两件由 `preset_roles` 负责，
且必须由租户自己触发，迁移不应替客户决定要不要某个岗位）。

注意 `is_system` 存量多为 NULL，判空必须写 `IS NULL OR = 0`：
`is_system = false` 在 NULL 上求值为 NULL，WHERE 不成立，会**静默更新 0 行**。

用法
----
    cd backend && ./.venv/Scripts/python.exe migrations/20261101_builtin_roles_is_system.py
"""
import asyncio
import os
import sys

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)


async def apply() -> bool:
    from sqlalchemy import text

    from app.constants.builtin_roles import BUILTIN_ROLE_CODES
    from app.core.database import get_engine

    engine = get_engine()
    placeholders = ", ".join(f":c{i}" for i in range(len(BUILTIN_ROLE_CODES)))
    params = {f"c{i}": c for i, c in enumerate(BUILTIN_ROLE_CODES)}

    async with engine.begin() as conn:
        before = (await conn.execute(text(
            f"SELECT COUNT(*) FROM roles WHERE code IN ({placeholders}) "
            f"AND (is_system IS NULL OR is_system = 0)"), params)).scalar()
        if not before:
            print("[skip] 内置角色 is_system 均已就位，无需回填")
            return False
        await conn.execute(text(
            f"UPDATE roles SET is_system = 1 "
            f"WHERE code IN ({placeholders}) AND (is_system IS NULL OR is_system = 0)"),
            params)
        after = (await conn.execute(text(
            f"SELECT COUNT(*) FROM roles WHERE code IN ({placeholders}) "
            f"AND (is_system IS NULL OR is_system = 0)"), params)).scalar()
        print(f"[ok] 内置角色 is_system 回填：{before} → {after}（应为 0）")
    return True


if __name__ == "__main__":
    changed = asyncio.run(apply())
    print("完成" if changed else "无需变更")
    sys.exit(0)
