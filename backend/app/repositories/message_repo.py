from app.repositories.base import MultiTenantRepository
from typing import Optional, Dict, List

class MessageRepository(MultiTenantRepository):
    async def list_messages(self, receiver_id: int, page: int = 1, page_size: int = 20, unread_only: bool = False) -> dict:
        sql = "SELECT id, tenant_id, msg_type, title, content, sender_id, receiver_id, is_read, read_at, biz_type, biz_id, created_at FROM messages WHERE receiver_id = :rid"
        params = {"rid": receiver_id}
        if unread_only: sql += " AND is_read = false"
        sql += " ORDER BY created_at DESC"
        return await self.query_page(sql, params, page, page_size)

    async def send(self, data: dict) -> int:
        return await self.execute("INSERT INTO messages (tenant_id, msg_type, title, content, sender_id, receiver_id, biz_type, biz_id) VALUES (:tenant_id, :msg_type, :title, :content, :sender_id, :receiver_id, :biz_type, :biz_id)", data)

    async def mark_read(self, id: int) -> int:
        from datetime import datetime, timezone
        return await self.execute("UPDATE messages SET is_read = true, read_at = :now WHERE id = :id", {"now": datetime.now(timezone.utc), "id": id})

    async def unread_count(self, receiver_id: int) -> int:
        from sqlalchemy import text
        result = await self._session.execute(text("SELECT COUNT(*) FROM messages WHERE receiver_id = :rid AND is_read = false"), {"rid": receiver_id})
        return result.scalar() or 0
