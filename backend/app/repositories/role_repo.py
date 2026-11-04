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
        """新建角色。

        ★两处兜底（与 C-56「在唯一入口兜住，而不是每个调用点各补一次」同一做法）：
        - `scope`：INSERT 里有 ``COALESCE(:scope, 'ALL')``，调用方不传就会
          ``A value is required for bind parameter 'scope'``。与其要求每个调用点
          都记得传，不如在这里兜 —— 不传即走默认 'ALL'。
        - `is_system`：模型声明 ``default=False``，但列清单里没有它 → 永远落 NULL。
          **这正是「固定列 INSERT 漏写带默认值的列」的第七次复发**
          （C-34/C-48/C-50/C-56×2/C-57 之后）。改为：调用方显式给了才写。
        """
        params = dict(data)
        params.setdefault("scope", None)
        cols = "tenant_id, name, code, description, scope"
        vals = ":tenant_id, :name, :code, :description, COALESCE(:scope, 'ALL')"
        if "is_system" in params:
            cols += ", is_system"
            # ★兜底值必须是 false 而非 0：roles.is_system 在 PG 上是 BOOLEAN，
            # COALESCE 要求两侧类型可统一，写 0 会直接
            # DatatypeMismatchError: column "is_system" is of type boolean but
            # expression is of type integer —— C-77 预置角色在 staging 上因此全挂
            # （本地 SQLite 无类型检查，一路绿）。SQLite >= 3.23 同样接受 false。
            vals += ", COALESCE(:is_system, false)"
        return await self.execute(
            f"INSERT INTO roles ({cols}) VALUES ({vals})", params)

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
        """角色成员列表（B3 组织树落地后已 JOIN 回填 org_name / org_code）。

        ⚠️ JOIN 条件必须带 ``ur.user_id = u.id``：只写 ``ur.role_id = :role_id``
        会让 ``users`` 与 ``user_roles`` 做**笛卡尔积** —— 角色有 1 名成员、
        租户有 11 个用户时，接口返回 11 行"全员都是成员"。界面表现为
        "随便一个角色点开都显示全部用户"，且不报错。
        """
        return await self.query(
            """SELECT u.id, u.username, u.real_name, u.status, u.primary_org_id,
                      o.name AS org_name, o.code AS org_code
               FROM users u
               LEFT JOIN organizations o ON o.id = u.primary_org_id
               JOIN user_roles ur ON ur.user_id = u.id AND ur.role_id = :role_id
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
        """按角色编码查询角色（**当前租户上下文内**）。"""
        return await self.query_one(
            "SELECT id, tenant_id, name, code, description, is_system, scope FROM roles WHERE code = :code",
            {"code": code},
        )

    async def get_by_code_in_tenant(self, code: str, tenant_id: str) -> Optional[Dict]:
        """按 (编码, 租户) 精确查角色 —— 绕开多租户自动注入（A-S1）。

        ★为什么不能直接用 `get_by_code`：本类继承 MultiTenantRepository，SELECT 会自动
        拼上**当前登录用户的** tenant_id。而"为新租户初始化管理员"时，操作者登录在
        mfg_demo、目标是另一个新租户 —— 用 get_by_code 会把新租户的管理员绑到
        **mfg_demo 的 admin 角色**上（实测 role_id=2 属于 mfg_demo）。

        后果比"绑错一个角色"严重得多：两个租户从此**共用同一行角色定义** ——
        改 mfg_demo 的 admin 权限会跨租户影响所有新租户的管理员，反之亦然。
        跨租户写必须用 `self._session.execute` 直连（与 UserRepository.get 查角色同一范式）。
        """
        from sqlalchemy import text
        result = await self._session.execute(
            text("SELECT id, tenant_id, name, code, description, is_system, scope "
                 "FROM roles WHERE code = :code AND tenant_id = :tid"),
            {"code": code, "tid": tenant_id},
        )
        row = result.mappings().first()
        return dict(row) if row else None

    async def count_users(self, role_id: int) -> int:
        """角色下挂了多少个用户。

        删除角色前必须查一次：``delete()`` 会连 ``user_roles`` 一起清掉，
        不拦就等于"删一个角色，悄悄摘掉一批人的权限"，且没有任何报错。
        """
        row = await self.query_one(
            "SELECT COUNT(*) AS n FROM user_roles WHERE role_id = :r", {"r": role_id}
        )
        return int((row or {}).get("n") or 0)

    async def find_permission_ids_by_codes(self, codes: List[str]) -> List[int]:
        """根据权限编码列表批量查询权限 ID（B13：POST /roles 传 codes → ids）。

        ★ 必须走裸 session：``permissions`` 是**全局字典表、没有 tenant_id 列**，
        走基类 ``query`` 会被注入 ``permissions.tenant_id`` → SQLite/PG 同样报
        ``no such column`` → 整个 ``POST /roles``（带权限码建角色）500。
        同文件 ``find_permissions_by_codes`` 早就是这个写法，这里是改造时漏掉
        的一处，2026-11-04 由契约闸 C 类查出（闸不认识"谁是全局表"，
        只认识"这张表有没有 tenant_id 列"，正好就是这条判据）。
        """
        if not codes:
            return []
        result = await self._session.execute(
            text(
                f"SELECT id FROM permissions WHERE code IN "
                f"({','.join(f':c{i}' for i in range(len(codes)))})"
            ),
            {f"c{i}": code for i, code in enumerate(codes)},
        )
        return [row[0] for row in result.fetchall()]

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
        """插入权限种子数据（如果编码不存在则创建），返回所有匹配权限的 ID 列表。

        ⚠️ **必须走裸 session**：``permissions`` 表**没有 tenant_id 列**（权限码是
        平台级字典，不是租户数据）。基类的 ``query_one`` 会给 SELECT 注入
        ``permissions.tenant_id = :_tenant_id`` → ``no such column`` →
        ``POST /roles/key-user-permissions`` 100% 500。
        与 ``_replace_role_permissions`` 同一个坑，同类第三次。
        """
        ids = []
        for perm in permissions:
            existing = await self._session.execute(
                text("SELECT id FROM permissions WHERE code = :code"),
                {"code": perm["code"]},
            )
            row = existing.first()
            if row:
                ids.append(row[0])
            else:
                await self.execute(
                    "INSERT INTO permissions (code, name, module, resource_type, action, description) "
                    "VALUES (:code, :name, :module, :resource_type, :action, :description)",
                    perm,
                )
                # 重新查询获取自增 ID
                again = await self._session.execute(
                    text("SELECT id FROM permissions WHERE code = :code"),
                    {"code": perm["code"]},
                )
                row2 = again.first()
                if row2:
                    ids.append(row2[0])
        return ids
