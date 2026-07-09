from app.repositories.role_repo import RoleRepository
from app.models.role import KEY_USER_ROLE_CODE, KEY_USER_PERMISSIONS
from typing import Optional


class RoleService:
    def __init__(self, role_repo: RoleRepository):
        self.role_repo = role_repo

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.role_repo.list(page, page_size)

    async def get(self, id: int) -> Optional[dict]:
        return await self.role_repo.get(id)

    async def create(self, data: dict) -> dict:
        count = await self.role_repo.create(data)
        return {"affected": count}

    async def update(self, id: int, data: dict) -> dict:
        count = await self.role_repo.update(id, data)
        return {"affected": count}

    async def delete(self, id: int) -> dict:
        count = await self.role_repo.delete(id)
        return {"affected": count}

    async def get_permissions(self, role_id: int) -> list:
        return await self.role_repo.get_permissions(role_id)

    async def assign_permissions(self, role_id: int, permission_ids: list) -> dict:
        await self.role_repo.assign_permissions(role_id, permission_ids)
        return {"affected": len(permission_ids)}

    async def get_users(self, role_id: int) -> list:
        return await self.role_repo.get_users(role_id)

    async def add_user(self, role_id: int, user_id: int, tenant_id: str) -> dict:
        count = await self.role_repo.add_user(role_id, user_id, tenant_id)
        return {"affected": count}

    async def assign_key_user_permissions(self, role_id: int) -> dict:
        """为角色分配 key_user 的三个专用权限。

        1. 确保三个 key_user 权限编码在 permissions 表中存在（种子自动创建）
        2. 清空角色旧权限
        3. 分配三个 key_user 权限 + 可选的额外模块权限

        Args:
            role_id: 角色 ID

        Returns:
            dict: 分配结果，包含分配的权限编码列表
        """
        # 确保 key_user 权限种子数据存在
        perm_ids = await self.role_repo.seed_permissions_if_not_exist(KEY_USER_PERMISSIONS)
        # 清空旧权限后分配新权限
        await self.role_repo.bulk_assign_permissions(role_id, perm_ids)
        return {"affected": len(perm_ids), "permission_codes": [p["code"] for p in KEY_USER_PERMISSIONS]}

    async def create_key_user_role(self, tenant_id: str, role_name: str = None) -> dict:
        """创建 key_user 角色并分配专属权限。

        Args:
            tenant_id: 租户 ID
            role_name: 角色显示名称（默认"关键用户"）

        Returns:
            dict: 包含角色创建结果和权限分配结果
        """
        # 检查 key_user 角色是否已存在
        existing = await self.role_repo.get_by_code(KEY_USER_ROLE_CODE)
        if existing:
            role_id = existing["id"]
        else:
            result = await self.role_repo.create({
                "tenant_id": tenant_id,
                "name": role_name or "关键用户",
                "code": KEY_USER_ROLE_CODE,
                "description": "关键用户角色 — 可配置模块、审批范围、部门数据范围",
            })
            # 重新查询获取 ID
            created = await self.role_repo.get_by_code(KEY_USER_ROLE_CODE)
            role_id = created["id"] if created else None

        if role_id:
            await self.assign_key_user_permissions(role_id)

        return {"role_id": role_id, "role_code": KEY_USER_ROLE_CODE}
