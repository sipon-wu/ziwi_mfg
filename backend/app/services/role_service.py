from app.repositories.role_repo import RoleRepository
from app.models.role import KEY_USER_ROLE_CODE, KEY_USER_PERMISSIONS, ROLE_SCOPES, ROLE_SCOPE_DEFAULT
from typing import Optional


class RoleService:
    def __init__(self, role_repo: RoleRepository):
        self.role_repo = role_repo

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        data = await self.role_repo.list(page, page_size)
        for item in data.get("items") or []:
            # 存量行的 roles.scope 可能是 NULL（迁移补列未回填），
            # 用 `or` 而非 setdefault：setdefault 在 key 已存在（值为 None）时不生效，
            # 会导致列表接口返回 null、而详情接口返回 ALL 的不一致。
            item["scope"] = item.get("scope") or ROLE_SCOPE_DEFAULT
        return data

    async def get(self, id: int) -> Optional[dict]:
        """B13: 返回角色详情 + 权限**编码**数组 + 数据作用域。"""
        role = await self.role_repo.get(id)
        if not role:
            return None
        permission_codes = await self.role_repo.get_permission_codes(id)
        role["permissions"] = permission_codes
        role["scope"] = role.get("scope") or ROLE_SCOPE_DEFAULT
        return role

    async def create(self, data: dict) -> dict:
        """B13: 支持同时传入 `permissions`(权限编码数组) 与 `scope`。"""
        permission_codes = data.pop("permissions", None) or []
        data["scope"] = self._normalize_scope(data.get("scope"))
        count = await self.role_repo.create(data)
        role_id = count  # INSERT ... RETURNING id

        if permission_codes:
            permission_ids = await self.role_repo.find_permission_ids_by_codes(list(permission_codes))
            if permission_ids:
                await self.role_repo.assign_permissions(role_id, permission_ids)
        return {"affected": count, "id": role_id, "scope": data.get("scope")}

    @staticmethod
    def _normalize_scope(scope: Optional[str]) -> str:
        """校验并归一化数据作用域，非法值回落到默认 ALL。"""
        if not scope:
            return ROLE_SCOPE_DEFAULT
        scope = str(scope).upper()
        if scope not in ROLE_SCOPES:
            return ROLE_SCOPE_DEFAULT
        return scope

    async def update(self, id: int, data: dict) -> dict:
        if "scope" in data:
            data["scope"] = self._normalize_scope(data.get("scope"))
        count = await self.role_repo.update(id, data)
        return {"affected": count, "scope": data.get("scope")}

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
                "scope": ROLE_SCOPE_DEFAULT,
                "description": "关键用户角色 — 可配置模块、审批范围、部门数据范围",
            })
            # 重新查询获取 ID
            created = await self.role_repo.get_by_code(KEY_USER_ROLE_CODE)
            role_id = created["id"] if created else None

        if role_id:
            await self.assign_key_user_permissions(role_id)

        return {"role_id": role_id, "role_code": KEY_USER_ROLE_CODE}

    async def set_scope(self, role_id: int, scope: str) -> dict:
        """B12: 设置角色的数据作用域（SELF/DEPT/DEPT_CHILD/ALL）。

        Raises:
            ValueError: scope 取值非法
        """
        scope = self._normalize_scope_value(scope)
        count = await self.role_repo.set_scope(role_id, scope)
        if not count:
            raise ValueError("角色不存在")
        return {"affected": count, "scope": scope}

    @staticmethod
    def _normalize_scope_value(scope: str) -> str:
        """校验 scope 是否为四值之一（供 set_scope 抛错用）。"""
        normalized = str(scope or "").upper()
        if normalized not in ROLE_SCOPES:
            raise ValueError(f"非法的数据作用域: {scope}，可选值 SELF/DEPT/DEPT_CHILD/ALL")
        return normalized
