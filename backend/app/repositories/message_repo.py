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
        # is_read 必须显式写 false。模型的 `default=False` 只在 ORM 侧生效，
        # 原生 SQL 不给值就是 NULL → `unread_count` 的 `is_read = false` 永远
        # 匹配不上（NULL 参与比较恒为 UNKNOWN），消息中心角标恒为 0。
        payload = {"is_read": False, **data}
        return await self.execute("INSERT INTO messages (tenant_id, msg_type, title, content, sender_id, receiver_id, biz_type, biz_id, is_read) VALUES (:tenant_id, :msg_type, :title, :content, :sender_id, :receiver_id, :biz_type, :biz_id, :is_read)", payload)

    async def mark_read(self, id: int) -> int:
        from datetime import datetime, timezone
        return await self.execute("UPDATE messages SET is_read = true, read_at = :now WHERE id = :id", {"now": datetime.now(timezone.utc), "id": id})

    async def unread_count(self, receiver_id: int) -> int:
        from sqlalchemy import text
        # 历史行可能是 NULL（send 曾经不写 is_read）—— `is_read = false` 对 NULL
        # 求值为 NULL，这些消息会永远算作"已读"。必须显式把 NULL 当未读。
        result = await self._session.execute(
            text("SELECT COUNT(*) FROM messages WHERE receiver_id = :rid "
                 "AND (is_read IS NULL OR is_read = false)"),
            {"rid": receiver_id})
        return result.scalar() or 0
