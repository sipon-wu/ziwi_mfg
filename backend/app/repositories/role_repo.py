from app.repositories.base import MultiTenantRepository
from typing import List, Dict, Any, Optional

class RoleRepository(MultiTenantRepository):
    
    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.query_page(
            """SELECT r.id, r.tenant_id, r.name, r.code, r.description, r.is_system, r.created_at,
               COUNT(ur.user_id) AS user_count
               FROM roles r
               LEFT JOIN user_roles ur ON ur.role_id = r.id
               GROUP BY r.id
               ORDER BY r.created_at DESC""",
            page=page, page_size=page_size
        )
    
    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id, tenant_id, name, code, description, is_system, created_at FROM roles WHERE id = :id",
            {"id": id}
        )
    
    async def create(self, data: dict) -> int:
        return await self.execute(
            "INSERT INTO roles (tenant_id, name, code, description) VALUES (:tenant_id, :name, :code, :description)",
            data
        )
    
    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE roles SET {sets} WHERE id = :id", params)
    
    async def delete(self, id: int) -> int:
        return await self.execute("DELETE FROM roles WHERE id = :id AND is_system = false", {"id": id})
    
    async def get_permissions(self, role_id: int) -> List[Dict]:
        return await self.query(
            """SELECT p.id, p.code, p.name, p.module, p.resource_type, p.action, p.description
               FROM permissions p
               JOIN role_permissions rp ON rp.permission_id = p.id
               WHERE rp.role_id = :role_id
               ORDER BY p.module, p.code""",
            {"role_id": role_id}
        )
    
    async def assign_permissions(self, role_id: int, permission_ids: List[int]) -> None:
        # 先清除旧权限
        await self.execute("DELETE FROM role_permissions WHERE role_id = :role_id", {"role_id": role_id})
        # 再插入新权限
        for pid in permission_ids:
            await self.execute(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :pid)",
                {"role_id": role_id, "pid": pid}
            )
    
    async def get_users(self, role_id: int) -> List[Dict]:
        return await self.query(
            """SELECT u.id, u.username, u.real_name, u.status
               FROM users u
               JOIN user_roles ur ON ur.user_id = u.id
               WHERE ur.role_id = :role_id""",
            {"role_id": role_id}
        )
    
    async def add_user(self, role_id: int, user_id: int, tenant_id: str) -> int:
        return await self.execute(
            "INSERT INTO user_roles (user_id, role_id, tenant_id) VALUES (:uid, :rid, :tid) ON CONFLICT DO NOTHING",
            {"uid": user_id, "rid": role_id, "tid": tenant_id}
        )

    async def bulk_assign_permissions(self, role_id: int, permission_ids: List[int]) -> None:
        """批量分配权限（清空旧权限后一次性插入新权限）。"""
        # 先清除旧权限
        await self.execute("DELETE FROM role_permissions WHERE role_id = :role_id", {"role_id": role_id})
        # 批量插入新权限（逐行插入以保证 SQLite 兼容）
        for pid in permission_ids:
            await self.execute(
                "INSERT INTO role_permissions (role_id, permission_id) VALUES (:role_id, :pid)",
                {"role_id": role_id, "pid": pid},
            )

    async def get_by_code(self, code: str) -> Optional[Dict]:
        """按角色编码查询角色。"""
        return await self.query_one(
            "SELECT id, tenant_id, name, code, description, is_system FROM roles WHERE code = :code",
            {"code": code},
        )

    async def find_permission_ids_by_codes(self, codes: List[str]) -> List[int]:
        """根据权限编码列表批量查询权限 ID。"""
        if not codes:
            return []
        rows = await self.query(
            f"SELECT id FROM permissions WHERE code IN ({','.join(f':c{i}' for i in range(len(codes)))})",
            {f"c{i}": code for i, code in enumerate(codes)},
        )
        return [r["id"] for r in rows]

    async def get_user_roles(self, user_id: int) -> List[Dict]:
        """查询用户关联的角色列表。"""
        from sqlalchemy import text
        result = await self._session.execute(text(
            """SELECT r.id, r.tenant_id, r.name, r.code, r.description, r.is_system, r.created_at
               FROM roles r
               JOIN user_roles ur ON ur.role_id = r.id
               WHERE r.tenant_id = :tenant_id AND ur.user_id = :user_id
               ORDER BY r.created_at DESC"""
        ), {"tenant_id": self._tenant_id, "user_id": user_id})
        return [dict(row._mapping) for row in result]

    async def get_user_permissions(self, user_id: int) -> List[str]:
        """查询用户通过角色获得的所有权限编码。"""
        from sqlalchemy import text
        rows = await self._session.execute(text(
            """SELECT DISTINCT p.code
               FROM permissions p
               JOIN role_permissions rp ON rp.permission_id = p.id
               JOIN user_roles ur ON ur.role_id = rp.role_id
               WHERE ur.user_id = :user_id
               ORDER BY p.code"""
        ), {"user_id": user_id})
        return [r[0] for r in rows.fetchall()]

    async def seed_permissions_if_not_exist(self, permissions: List[dict]) -> List[int]:
        """插入权限种子数据（如果编码不存在则创建），返回所有匹配权限的 ID 列表。"""
        ids = []
        for perm in permissions:
            existing = await self.query_one(
                "SELECT id FROM permissions WHERE code = :code", {"code": perm["code"]}
            )
            if existing:
                ids.append(existing["id"])
            else:
                await self.execute(
                    "INSERT INTO permissions (code, name, module, resource_type, action, description) "
                    "VALUES (:code, :name, :module, :resource_type, :action, :description)",
                    perm,
                )
                # 重新查询获取自增 ID
                row = await self.query_one(
                    "SELECT id FROM permissions WHERE code = :code", {"code": perm["code"]}
                )
                if row:
                    ids.append(row["id"])
        return ids
