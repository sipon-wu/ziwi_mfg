from app.repositories.base import MultiTenantRepository
from typing import List, Dict, Any, Optional

class UserRepository(MultiTenantRepository):
    
    async def list(self, page: int = 1, page_size: int = 20, keyword: str = None, status: str = None) -> dict:
        sql = "SELECT id, tenant_id, username, real_name, email, phone, avatar_url, status, last_login_at, created_at FROM users WHERE 1=1"
        params = {}
        if keyword:
            sql += " AND (username LIKE :kw OR real_name LIKE :kw)"
            params["kw"] = f"%{keyword}%"
        if status:
            sql += " AND status = :status"
            params["status"] = status
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)
    
    async def get(self, id: int) -> Optional[Dict]:
        user = await self.query_one(
            "SELECT id, tenant_id, username, real_name, email, phone, avatar_url, status, last_login_at, created_at FROM users WHERE id = :id",
            {"id": id}
        )
        if not user:
            return None
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
    
    async def get_with_password(self, username: str, tenant_id: str = None) -> Optional[Dict]:
        sql = "SELECT * FROM users WHERE username = :username"
        params = {"username": username}
        if tenant_id:
            sql += " AND tenant_id = :tenant_id"
            params["tenant_id"] = tenant_id
        return await self.query_one(sql, params)
    
    async def get_with_password_by_id(self, id: int) -> Optional[Dict]:
        return await self.query_one("SELECT * FROM users WHERE id = :id", {"id": id})
    
    async def create(self, data: dict) -> int:
        return await self.execute(
            """INSERT INTO users (tenant_id, username, password_hash, real_name, email, phone, status)
               VALUES (:tenant_id, :username, :password_hash, :real_name, :email, :phone, 'active')""",
            {"tenant_id": data["tenant_id"], "username": data["username"],
             "password_hash": data["password_hash"], "real_name": data.get("real_name"),
             "email": data.get("email"), "phone": data.get("phone")}
        )
    
    async def update(self, id: int, data: dict) -> int:
        sets = self._build_set_clause(data)
        params = {**data, "id": id}
        return await self.execute(f"UPDATE users SET {sets} WHERE id = :id", params)
    
    async def delete(self, id: int) -> int:
        return await self.execute("UPDATE users SET status = 'disabled' WHERE id = :id", {"id": id})
    
    async def update_last_login(self, id: int) -> int:
        from datetime import datetime, timezone
        return await self.execute("UPDATE users SET last_login_at = :now WHERE id = :id",
                                  {"now": datetime.now(timezone.utc), "id": id})
