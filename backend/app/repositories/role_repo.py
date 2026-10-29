from app.repositories.base import MultiTenantRepository
from typing import List, Dict, Any, Optional

from sqlalchemy import text


class RoleRepository(MultiTenantRepository):

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        # ⚠️ 不要在这里用「相关子查询」统计 permission_count：
        # query_page 会把整条 SQL 包进 `SELECT COUNT(*) FROM (<sql>)`，而
        # `_inject_tenant_where_select` 用的是"第一个 FROM <标识符>"正则——
        # 它会命中子查询里的 `FROM role_permissions rp`，于是给子查询注入
        # `rp.tenant_id`（该表没有此列）→ 列表接口 500。
        # 改用 LEFT JOIN + COUNT(DISTINCT) 等价实现。
        return await self.query_page(
            """SELECT r.id, r.tenant_id, r.name, r.code, r.description, r.is_system, r.scope, r.created_at,
               COUNT(DISTINCT ur.user_id) AS user_count,
               COUNT(DISTINCT rp.permission_id) AS permission_count
               FROM roles r
               LEFT JOIN user_roles ur ON ur.role_id = r.id
               LEFT JOIN role_permissions rp ON rp.role_id = r.id
               GROUP BY r.id
               ORDER BY r.created_at DESC""",
            page=page, page_size=page_size
        )

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            "SELECT id, tenant_id, name, code, description, is_system, scope, created_at FROM roles WHERE id = :id",
            {"id": id}
        )

    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO roles (tenant_id, name, code, description, scope)
               VALUES (:tenant_id, :name, :code, :description, COALESCE(:scope, 'ALL'))""",
            data
        )

    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE roles SET {sets} WHERE id = :id", params)

    async def delete(self, id: int) -> int:
        """删除角色（同时清掉关联表）。

        ⚠️ 必须**显式**删关联表：SQLite 默认 ``PRAGMA foreign_keys=OFF``，
        声明上的 ``ON DELETE CASCADE`` 根本不执行 —— 删角色会留下孤儿
        ``role_permissions`` 行；而 SQLite 的 AUTOINCREMENT 在最大行被删后
        会复用 rowid，于是"新建的角色莫名其妙带着上一个角色的权限"（实测踩过）。
        PG 上外键会级联，这两条 DELETE 只是多做一次幂等清理，无副作用。
        ``role_permissions`` 无 tenant_id 列，故走裸 session。
        """
        await self._session.execute(
            text("DELETE FROM role_permissions WHERE role_id = :r"), {"r": id}
        )
        await self._session.execute(
            text("DELETE FROM user_roles WHERE role_id = :r"), {"r": id}
        )
        # 不能写 `is_system = false`：存量行的 is_system 多为 NULL，
        # `NULL = false` 求值为 NULL → WHERE 不成立 → 静默删 0 行（实测踩过）。
        return await self.execute(
            "DELETE FROM roles WHERE id = :id AND (is_system IS NULL OR is_system = false)",
            {"id": id},
        )

    async def set_scope(self, role_id: int, scope: str) -> int:
        """B12: 更新角色的数据作用域（UPDATE 由基类自动注入 tenant_id 过滤）。"""
        return await self.execute(
            "UPDATE roles SET scope = :scope WHERE id = :id",
            {"id": role_id, "scope": scope}
        )

    async def get_permissions(self, role_id: int) -> List[Dict]:
        """角色已授权的权限明细（含 id / code / module / action）。

        必须用裸 session 而非 ``query()``：``query()`` 会把 tenant_id 过滤注入
        主表（此处是 permissions），而 permissions 是**全局字典表、没有 tenant_id 列**，
        注入后直接 SQL 报错（改造前该端点 500 就是这个原因）。
        租户隔离由入参 role_id 的归属保证（调用方已从 roles 表取到该角色）。
        """
        result = await self._session.execute(text(
            """SELECT p.id, p.code, p.name, p.module, p.resource_type, p.action, p.description
               FROM permissions p
               JOIN role_permissions rp ON rp.permission_id = p.id
               WHERE rp.role_id = :role_id
               ORDER BY p.module, p.resource_type, p.action"""
        ), {"role_id": role_id})
        return [dict(row._mapping) for row in result.fetchall()]

    async def list_all_permissions(self) -> List[Dict]:
        """全量权限目录（供角色权限勾选界面）。

        同 ``get_permissions``：permissions 无 tenant_id，必须走裸 session。
        """
        result = await self._session.execute(text(
            """SELECT id, code, name, module, resource_type, action, description
               FROM permissions
               ORDER BY module, resource_type, action"""
        ))
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_permission_codes(self, role_id: int) -> List[str]:
        """B13: 返回角色已授权的权限**编码**数组（roles 不进 JWT，本地体系）。

        用裸 session 而非 query()：query() 会把 tenant_id 过滤注入到主表
        （permissions），而 permissions 表没有 tenant_id 列会直接报错。
        这里显式 JOIN roles 限定租户，保证隔离语义且不依赖注入。
        """
        from sqlalchemy import text
        params = {"role_id": role_id}
        tenant_filter = ""
        if self._tenant_id:
            tenant_filter = " AND r.tenant_id = :tenant_id"
            params["tenant_id"] = self._tenant_id
        rows = await self._session.execute(text(
            f"""SELECT DISTINCT p.code
                FROM permissions p
                JOIN role_permissions rp ON rp.permission_id = p.id
                JOIN roles r ON r.id = rp.role_id
                WHERE rp.role_id = :role_id{tenant_filter}
                ORDER BY p.code"""  # noqa: E712
        ), params)
        return [row[0] for row in rows.fetchall()]

    async def _replace_role_permissions(self, role_id: int, permission_ids: List[int]) -> int:
        """清空并用给定 id 重建 role_permissions，返回写入条数。

        ⚠️ **必须走裸 session**：``role_permissions`` 表**没有 tenant_id 列**，
        而基类 ``execute()`` 会给 UPDATE/DELETE 自动注入 ``tenant_id = :_tenant_id``
        → 直接报 ``no such column: tenant_id``（改造前该端点 500 就是这个原因）。
        租户隔离不靠这里，而靠调用方先校验 role_id 属于当前租户
        （见 ``RoleService.assign_permissions``）。
        """
        await self._session.execute(
            text("DELETE FROM role_permissions WHERE role_id = :role_id"),
            {"role_id": role_id},
        )
        if permission_ids:
            # 一次 executemany，避免 332 次往返
            await self._session.execute(
                text("INSERT INTO role_permissions (role_id, permission_id) "
                     "VALUES (:role_id, :pid)"),
                [{"role_id": role_id, "pid": pid} for pid in permission_ids],
            )
        return len(permission_ids)

    async def assign_permissions(self, role_id: int, permission_ids: List[int]) -> None:
        await self._replace_role_permissions(role_id, permission_ids)

    async def get_users(self, role_id: int) -> List[Dict]:
        """角色成员列表（B3 组织树落地后已 JOIN 回填 org_name / org_code）。"""
        return await self.query(
            """SELECT u.id, u.username, u.real_name, u.status, u.primary_org_id,
                      o.name AS org_name, o.code AS org_code
               FROM users u
               LEFT JOIN organizations o ON o.id = u.primary_org_id
               JOIN user_roles ur ON ur.role_id = :role_id
               WHERE ur.role_id = :role_id
               ORDER BY u.id""",
            {"role_id": role_id}
        )

    async def remove_user(self, role_id: int, user_id: int) -> int:
        """移出角色成员（UPDATE/DELETE 由基类自动注入 tenant_id 过滤）。"""
        return await self.execute(
            "DELETE FROM user_roles WHERE role_id = :rid AND user_id = :uid",
            {"rid": role_id, "uid": user_id},
        )


    async def add_user(self, role_id: int, user_id: int, tenant_id: str) -> int:
        return await self.execute(
            "INSERT INTO user_roles (user_id, role_id, tenant_id) VALUES (:uid, :rid, :tid) ON CONFLICT DO NOTHING",
            {"uid": user_id, "rid": role_id, "tid": tenant_id}
        )

    async def bulk_assign_permissions(self, role_id: int, permission_ids: List[int]) -> None:
        """批量分配权限（清空旧权限后一次性插入新权限）。

        保留该名字是为兼容 key_user 授权链路；实现与 assign_permissions 相同。
        """
        await self._replace_role_permissions(role_id, permission_ids)

    async def get_by_code(self, code: str) -> Optional[Dict]:
        """按角色编码查询角色。"""
        return await self.query_one(
            "SELECT id, tenant_id, name, code, description, is_system, scope FROM roles WHERE code = :code",
            {"code": code},
        )

    async def find_permission_ids_by_codes(self, codes: List[str]) -> List[int]:
        """根据权限编码列表批量查询权限 ID（B13：POST /roles 传 codes → ids）。"""
        if not codes:
            return []
        rows = await self.query(
            f"SELECT id FROM permissions WHERE code IN ({','.join(f':c{i}' for i in range(len(codes)))})",
            {f"c{i}": code for i, code in enumerate(codes)},
        )
        return [r["id"] for r in rows]

    async def find_permissions_by_codes(self, codes: List[str]) -> List[Dict]:
        """按权限码批量取 ``{id, code}``，供按编码授权时**回报拼错/失效的码**。

        同样走裸 session —— permissions 无 tenant_id 列。
        """
        if not codes:
            return []
        result = await self._session.execute(
            text(
                f"SELECT id, code FROM permissions WHERE code IN "
                f"({','.join(f':c{i}' for i in range(len(codes)))})"
            ),
            {f"c{i}": code for i, code in enumerate(codes)},
        )
        return [dict(row._mapping) for row in result.fetchall()]

    async def get_user_roles(self, user_id: int) -> List[Dict]:
        """查询用户关联的角色列表。"""
        from sqlalchemy import text
        result = await self._session.execute(text(
            """SELECT r.id, r.tenant_id, r.name, r.code, r.description, r.is_system, r.scope, r.created_at
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
