from app.repositories.role_repo import RoleRepository
from app.models.role import KEY_USER_ROLE_CODE, KEY_USER_PERMISSIONS, ROLE_SCOPES, ROLE_SCOPE_DEFAULT
from app.constants.modules import MODULE_NAMES, MODULE_PLAT
from app.constants.permission_labels import action_label, action_sort_key, resource_label
from typing import Dict, List, Optional


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
        role = await self.role_repo.get(id)
        if not role:
            raise ValueError("角色不存在")
        if role.get("is_system"):
            raise ValueError("系统内置角色不可删除")
        count = await self.role_repo.delete(id)
        return {"affected": count}

    async def get_permissions(self, role_id: int) -> list:
        return await self.role_repo.get_permissions(role_id)

    async def get_permission_catalog(self) -> dict:
        """全量权限目录，按 模块 → 资源 → 动作 三层聚合（供勾选界面）。

        返回结构::

            {"total": 331,
             "modules": [
               {"module": "M01", "module_name": "生产管理",
                "resources": [
                  {"resource": "work_order", "resource_name": "工单",
                   "permissions": [{"id": 12, "code": "M01:work_order:read",
                                    "action": "read", "action_name": "查看"}, ...]}
                ]}]}

        排序：业务模块 M00..M30 在前（按编码），PLAT 平台底座垫底；
        动作按 查看→新建→修改→审批→执行→导出→删除 排列，符合"从只读到可写"的直觉。
        """
        rows = await self.role_repo.list_all_permissions()

        buckets: Dict[str, dict] = {}
        for row in rows:
            module = row.get("module") or MODULE_PLAT
            resource = row.get("resource_type") or "misc"
            action = row.get("action") or ""

            bucket = buckets.setdefault(module, {
                "module": module,
                "module_name": MODULE_NAMES.get(module, module),
                "resources": {},
            })
            res = bucket["resources"].setdefault(resource, {
                "resource": resource,
                "resource_name": resource_label(resource),
                "permissions": [],
            })
            res["permissions"].append({
                "id": row["id"],
                "code": row["code"],
                "action": action,
                "action_name": action_label(action),
            })

        def module_key(code: str):
            # PLAT 垫底：业务模块按 M00/M01/... 字典序即可
            return (1, "") if code == MODULE_PLAT else (0, code)

        modules = []
        for code in sorted(buckets, key=module_key):
            bucket = buckets[code]
            resources = sorted(bucket["resources"].values(), key=lambda r: r["resource"])
            for res in resources:
                res["permissions"].sort(key=lambda p: (action_sort_key(p["action"]), p["code"]))
            modules.append({
                "module": bucket["module"],
                "module_name": bucket["module_name"],
                "resources": resources,
            })

        return {"total": len(rows), "modules": modules}

    async def assign_permissions(
        self,
        role_id: int,
        permission_ids: Optional[List[int]] = None,
        permission_codes: Optional[List[str]] = None,
    ) -> dict:
        """覆盖式授权：先清空再用给定的 id 集合重建。

        - ``permission_codes`` 优先（前端拿到的就是编码，避免前端自己维护 code→id 映射）
        - 传空列表 = 清空该角色全部权限（合法操作，不等于"未传"）
        - 两者都没传 → ValueError（避免一次误调用把角色权限清空）

        Returns:
            {"affected": n, "unknown_codes": [...]}
            ``unknown_codes`` 非空说明前端传了库里不存在的码（拼错或端点已删），
            由调用方决定是否报错提示。
        """
        # 先确认 role 属于当前租户：role_permissions 无 tenant_id 列，
        # 隔离只能靠这一步把关（否则可越权改写其它租户的角色授权）。
        if not await self.role_repo.get(role_id):
            raise ValueError("角色不存在")

        if permission_codes is not None:
            rows = await self.role_repo.find_permissions_by_codes(list(permission_codes))
            resolved = {r["code"]: r["id"] for r in rows}
            unknown = sorted({c for c in permission_codes if c not in resolved})
            ids = [resolved[c] for c in permission_codes if c in resolved]
        elif permission_ids is not None:
            ids = [int(i) for i in permission_ids]
            unknown = []
        else:
            raise ValueError("permission_ids 与 permission_codes 必须二选一")

        # 去重保序（同一权限重复勾选不应重复插入）
        seen = set()
        unique_ids = [i for i in ids if not (i in seen or seen.add(i))]

        await self.role_repo.assign_permissions(role_id, unique_ids)
        return {"affected": len(unique_ids), "unknown_codes": unknown}

    async def get_users(self, role_id: int) -> list:
        return await self.role_repo.get_users(role_id)

    async def add_user(self, role_id: int, user_id: int, tenant_id: str) -> dict:
        count = await self.role_repo.add_user(role_id, user_id, tenant_id)
        return {"affected": count}

    async def remove_user(self, role_id: int, user_id: int) -> dict:
        count = await self.role_repo.remove_user(role_id, user_id)
        if not count:
            raise ValueError("该用户不在此角色中")
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
