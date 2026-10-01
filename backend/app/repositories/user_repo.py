from app.repositories.base import MultiTenantRepository
from typing import List, Dict, Any, Optional

class UserRepository(MultiTenantRepository):

    # 注意：cloud_uuid **不进**公共列清单 —— 它只被 cloud 登录分支（get_by_cloud_uuid）需要，
    # 且部分本地库（如 ziwi_alpha.db）尚未执行 add_cloud_uuid.sql 补列；
    # 放进公共清单会让本地子账号登录/列表路径直接报 "no such column: cloud_uuid"。
    _USER_COLUMNS = ("id, tenant_id, username, real_name, email, phone, avatar_url, "
                     "status, primary_org_id, last_login_at, created_at")

    async def list(self, page: int = 1, page_size: int = 20, keyword: str = None, status: str = None) -> dict:
        sql = f"SELECT {self._USER_COLUMNS} FROM users WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (username LIKE :kw OR real_name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        result = await self.query_page(sql, params, page, page_size)
        # 批量回填组织归属（避免 N+1：整页一次查询）
        await self._attach_org_ids(result.get("items") or [])
        return result

    async def _attach_org_ids(self, rows: List[Dict]) -> None:
        """为列表行回填 `org_id`（主组织）与 `org_ids`（全部归属组织）。"""
        user_ids = [r.get("id") for r in rows if r.get("id") is not None]
        if not user_ids:
            for row in rows:
                row.setdefault("org_id", row.get("primary_org_id"))
                row.setdefault("org_ids", [])
            return
        placeholders = ", ".join(f":uid{i}" for i in range(len(user_ids)))
        rows_data = await self.query(
            f"""SELECT user_id, org_id, is_primary FROM user_organizations
                WHERE user_id IN ({placeholders}) ORDER BY user_id, is_primary DESC""",
            {f"uid{i}": uid for i, uid in enumerate(user_ids)},
        )
        grouped: Dict[int, List[int]] = {uid: [] for uid in user_ids}
        for row in rows_data:
            uid = row.get("user_id")
            if uid in grouped:
                grouped[uid].append(row.get("org_id"))
        for row in rows:
            uid = row.get("id")
            ids = grouped.get(uid, [])
            row["org_id"] = row.get("primary_org_id") or (ids[0] if ids else None)
            row["org_ids"] = ids
            row["org_name"] = None  # 组织名称依赖 B3 的 organizations 表，本轮占位

    async def get(self, id: int) -> Optional[Dict]:
        user = await self.query_one(
            f"SELECT {self._USER_COLUMNS} FROM users WHERE id = :id",
            {"id": id}
        )
        if not user:
            return None
        await self._attach_org_ids([user])
        # 跨DB兼容：单独查询角色（避免 PostgreSQL 专属 array_agg）
        # 使用 execute() 直连 session 绕过 MultiTenantRepository 的自动 tenant_id 注入
        # （因为 JOIN 多表会导致 ambiguous column name）
        from sqlalchemy import text
        result = await self._session.execute(text(
            "SELECT r.name FROM roles r JOIN user_roles ur ON ur.role_id = r.id "
            "WHERE r.tenant_id = :tenant_id AND ur.user_id = :uid"
        ), {"tenant_id": self._tenant_id, "uid": id})
        roles = [row[0] for row in result.fetchall()]
        user["roles"] = roles if roles else []
        return user

    async def get_by_cloud_uuid(self, cloud_uuid: str) -> Optional[Dict]:
        """通过 cloud.ziwi.cn 的用户 UUID 查询本地用户。

        用于统一 JWT 认证流程：cloud JWT 验签通过后，用 sub (UUID)
        在 mfg 本地 users 表中查找对应记录。

        Args:
            cloud_uuid: cloud.ziwi.cn 用户 UUID（JWT sub claim）

        Returns:
            用户 dict（含 id, tenant_id, cloud_uuid, username 等），未找到返回 None
        """
        return await self.query_one(
            f"SELECT {self._USER_COLUMNS} FROM users WHERE cloud_uuid = :cloud_uuid",
            {"cloud_uuid": cloud_uuid}
        )

    async def get_with_password(self, username: str, tenant_id: str = None) -> Optional[Dict]:
        sql = "SELECT * FROM users WHERE username = :username"
        params = {"username": username}
        if tenant_id:
            sql += " AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        return await self.query_one(sql, params)

    async def get_with_password_by_id(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM users WHERE id = :id", {"id": id})

    @staticmethod
    def normalize_email(email: Optional[str]) -> Optional[str]:
        """B15: email 入库前统一小写归一（与 cloud 侧 email 大小写可能不同的对齐点）。"""
        if email is None:
            return None
        email = str(email).strip()
        return email.lower() or None

    async def create(self, data: dict) -> int:
        """创建用户并同步组织归属（B7/B8）。

        - email 统一小写归一（B15）
        - `org_id` / `primary_org_id` 写入 users.primary_org_id
        - 同时在 user_organizations 落主组织行（is_primary=1）；`org_ids` 中的其余组织为兼任（is_primary=0）

        Returns:
            新建用户的自增 ID
        """
        tenant_id = data["tenant_id"]
        email = self.normalize_email(data.get("email"))
        primary_org_id = data.get("org_id") or data.get("primary_org_id")
        extra_org_ids = [o for o in (data.get("org_ids") or []) if o and o != primary_org_id]

        user_id = await self._insert_user(tenant_id, data, email, primary_org_id)
        await self._write_org_links(user_id, tenant_id, primary_org_id, extra_org_ids)
        return user_id

    async def _insert_user(self, tenant_id: str, data: dict, email: Optional[str],
                           primary_org_id: Optional[int]) -> int:
        """INSERT users。

        `cloud_uuid` 仅在管理员手绑（B15）时带值才写入：部分本地库尚未执行
        `migrations/add_cloud_uuid.sql` 补列，无条件写该列会让普通建户直接 500。
        """
        params = {
            "tenant_id": tenant_id,
            "username": data["username"],
            "password_hash": data["password_hash"],
            "real_name": data.get("real_name"),
            "email": email,
            "phone": data.get("phone"),
            "primary_org_id": primary_org_id,
        }
        base_cols = ("tenant_id, username, password_hash, real_name, email, phone, primary_org_id")
        base_placeholders = (":tenant_id, :username, :password_hash, :real_name, "
                             ":email, :phone, :primary_org_id")
        cloud_uuid = data.get("cloud_uuid")
        if cloud_uuid:
            base_cols += ", cloud_uuid"
            base_placeholders += ", :cloud_uuid"
            params["cloud_uuid"] = cloud_uuid

        return await self.execute(
            f"""INSERT INTO users ({base_cols}, status)
               VALUES ({base_placeholders}, 'active')""",
            params,
        )

    async def _write_org_links(self, user_id: int, tenant_id: str, primary_org_id: Optional[int],
                               extra_org_ids: List[int]) -> None:
        """写入/刷新用户的组织归属关联行（删除组织树节点时应先摘除这里）。"""
        if primary_org_id:
            await self.execute(
                """INSERT INTO user_organizations (tenant_id, user_id, org_id, is_primary)
                   VALUES (:tenant_id, :user_id, :org_id, 1)
                   ON CONFLICT (tenant_id, user_id, org_id) DO UPDATE SET is_primary = 1""",
                {"tenant_id": tenant_id, "user_id": user_id, "org_id": primary_org_id}
            )
        for org_id in extra_org_ids:
            await self.execute(
                """INSERT INTO user_organizations (tenant_id, user_id, org_id, is_primary)
                   VALUES (:tenant_id, :user_id, :org_id, 0)
                   ON CONFLICT (tenant_id, user_id, org_id) DO UPDATE SET is_primary = 0""",
                {"tenant_id": tenant_id, "user_id": user_id, "org_id": org_id}
            )

    async def sync_user_orgs(self, user_id: int, primary_org_id: Optional[int],
                             extra_org_ids: Optional[List[int]] = None,
                             tenant_id: Optional[str] = None) -> dict:
        """B8/B9: 全量同步用户组织归属（主组织 + 兼任）。

        - 目标集合之外的旧关联行会被删除
        - `primary_org_id` 对应的行 is_primary=1，其余为 0
        - 删除 `is_primary=1` 的记录由服务层拦截（见 UserService）

        Returns:
            {"primary_org_id": int|None, "org_ids": [...], "removed": n}
        """
        scope_tenant = tenant_id or self._tenant_id
        if not scope_tenant:
            raise ValueError("缺少 tenant_id，无法同步用户组织归属")
        extra_org_ids = list(extra_org_ids or [])
        target_org_ids = [o for o in ([primary_org_id] + extra_org_ids) if o is not None]
        target_set = set(target_org_ids)

        if self._tenant_id and scope_tenant is None:
            scope_tenant = self._tenant_id

        deleted = 0
        if target_set:
            placeholders = ", ".join(f":oid{i}" for i in range(len(target_set)))
            params = {f"oid{i}": oid for i, oid in enumerate(target_set)}
            params.update({"user_id": user_id})
            if scope_tenant:
                params["tenant_id"] = scope_tenant
                deleted = await self.execute(
                    f"""DELETE FROM user_organizations
                        WHERE user_id = :user_id AND tenant_id = :tenant_id
                          AND org_id NOT IN ({placeholders})""",
                    params,
                )
            else:
                deleted = await self.execute(
                    f"""DELETE FROM user_organizations
                        WHERE user_id = :user_id AND org_id NOT IN ({placeholders})""",
                    params,
                )

        await self._write_org_links(user_id, scope_tenant or "", primary_org_id,
                                    [o for o in extra_org_ids if o != primary_org_id])

        existing = await self.query(
            "SELECT org_id FROM user_organizations WHERE user_id = :user_id ORDER BY org_id",
            {"user_id": user_id},
        )
        org_ids = [row["org_id"] for row in existing]
        return {"primary_org_id": primary_org_id, "org_ids": org_ids, "removed": deleted or 0}

    async def update(self, id: int, data: dict) -> int:
        # B15: email 更新同样做小写归一，避免同一账号因大小写产生两条记录
        if "email" in data:
            data["email"] = self.normalize_email(data.get("email"))
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE users SET {sets} WHERE id = :id", params)

    async def delete(self, id: int) -> int:
        return await self.execute("UPDATE users SET status = 'disabled' WHERE id = :id", {"id": id})

    async def update_last_login(self, id: int) -> int:
        from datetime import datetime, timezone
        return await self.execute("UPDATE users SET last_login_at = :now WHERE id = :id",
                                  {"now": datetime.now(timezone.utc), "id": id})
