#!/usr/bin/env python3
"""key_user 权限种子数据脚本。

运行方式：
    python -m seed.seed_key_user_permissions

或在应用启动时通过 main.py 中的 seed 函数调用。
"""
import asyncio
import sys
import os

# 将项目根目录加入 Python 路径
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from app.core.database import init_db, get_session_factory
from app.repositories.role_repo import RoleRepository
from app.models.role import KEY_USER_ROLE_CODE, KEY_USER_PERMISSIONS


async def seed_key_user_permissions(tenant_id: str = "default"):
    """确保 key_user 的三个专属权限在 permissions 表中存在。

    Args:
        tenant_id: 租户 ID（仅用于创建角色时使用）
    """
    await init_db()
    factory = get_session_factory()

    async with factory() as session:
        repo = RoleRepository(session)
        repo.set_tenant_id(tenant_id)

        # 1. 确保三个 key_user 权限编码存在
        perm_ids = await repo.seed_permissions_if_not_exist(KEY_USER_PERMISSIONS)
        print(f"[seed] key_user 权限已就绪: {len(perm_ids)} 个权限")
        for p in KEY_USER_PERMISSIONS:
            print(f"  - {p['code']}: {p['name']}")

        # 2. 确保 key_user 角色存在
        existing_role = await repo.get_by_code(KEY_USER_ROLE_CODE)
        if existing_role:
            print(f"[seed] key_user 角色已存在 (id={existing_role['id']})")
            role_id = existing_role["id"]
        else:
            from app.models.role import Role
            await repo.create({
                "tenant_id": tenant_id,
                "name": "关键用户",
                "code": KEY_USER_ROLE_CODE,
                "description": "关键用户角色 — 可配置模块、审批范围、部门数据范围",
            })
            created = await repo.get_by_code(KEY_USER_ROLE_CODE)
            role_id = created["id"] if created else None
            print(f"[seed] key_user 角色已创建 (id={role_id})")

        # 3. 分配权限
        if role_id:
            await repo.bulk_assign_permissions(role_id, perm_ids)
            print(f"[seed] key_user 权限已分配完成")

        await session.commit()

    print("[seed] key_user 权限种子数据初始化完成")


if __name__ == "__main__":
    tenant_id = sys.argv[1] if len(sys.argv) > 1 else "default"
    asyncio.run(seed_key_user_permissions(tenant_id))
