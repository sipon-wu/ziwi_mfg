"""Integration Gateway — API Key 仓储（IG MVP）。

继承 MultiTenantRepository，自动获得 UPDATE/DELETE 行级租户隔离。
认证定位（get_by_prefix）走裸 session.execute 绕过 tenant 注入 —— 因为认证时
只有 key 前缀、尚无 tenant_id，必须由前缀反查租户。
"""
from typing import Any, Dict, List, Optional

from sqlalchemy import text

from app.repositories.base import MultiTenantRepository


class ApiKeyRepository(MultiTenantRepository):
    _COLUMNS = (
        "id, tenant_id, key_name, key_prefix, permissions, allowed_ips, "
        "webhook_url, is_active, expires_at, last_used_at, created_by, created_at"
    )

    async def create(self, data: dict) -> int:
        """写入一条 API Key（data 须含 key_prefix / key_hash / key_name / tenant_id）。"""
        cols = ", ".join(data.keys())
        placeholders = ", ".join(f":{k}" for k in data.keys())
        return await self.execute(
            f"INSERT INTO api_keys ({cols}) VALUES ({placeholders})",
            data,
        )

    async def list(self, page: int = 1, page_size: int = 20, keyword: str = None) -> dict:
        """列出当前租户的密钥（不含 key_hash）。"""
        sql = f"SELECT {self._COLUMNS} FROM api_keys WHERE 1=1"
        params: Dict[str, Any] = {}
        if keyword:
            sql += " AND key_name LIKE :kw"
            params["kw"] = f"%{keyword}%"
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def get(self, id: int) -> Optional[Dict]:
        return await self.query_one(
            f"SELECT {self._COLUMNS} FROM api_keys WHERE id = :id",
            {"id": id},
        )

    async def get_by_prefix(self, key_prefix: str) -> Optional[Dict]:
        """按前缀定位密钥（含 key_hash），用于认证。

        注意：裸 session.execute，绕过 MultiTenantRepository 的 tenant 注入 ——
        认证时尚未确定 tenant_id，必须由前缀反查。
        """
        result = await self._session.execute(
            text(
                "SELECT id, tenant_id, key_name, key_prefix, key_hash, permissions, "
                "allowed_ips, is_active, expires_at, webhook_url "
                "FROM api_keys WHERE key_prefix = :prefix LIMIT 1"
            ),
            {"prefix": key_prefix},
        )
        row = result.first()
        return dict(row._mapping) if row else None

    async def revoke(self, id: int) -> int:
        """吊销密钥（软删除：is_active=false），自动附加 tenant 过滤。"""
        return await self.execute(
            "UPDATE api_keys SET is_active = false WHERE id = :id",
            {"id": id},
        )

    async def update_last_used(self, id: int) -> int:
        from datetime import datetime, timezone
        return await self.execute(
            "UPDATE api_keys SET last_used_at = :now WHERE id = :id",
            {"now": datetime.now(timezone.utc), "id": id},
        )
