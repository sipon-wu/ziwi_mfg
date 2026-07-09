from app.repositories.message_repo import MessageRepository
from typing import Optional


class MessageService:
    def __init__(self, repo: MessageRepository):
        self.repo = repo

    async def list_messages(self, receiver_id: int, page: int = 1, page_size: int = 20, unread_only: bool = False) -> dict:
        return await self.repo.list_messages(receiver_id, page, page_size, unread_only)

    async def send(self, data: dict) -> dict:
        return {"id": await self.repo.send(data)}

    async def mark_read(self, id: int) -> dict:
        return {"affected": await self.repo.mark_read(id)}

    async def unread_count(self, receiver_id: int) -> dict:
        return {"count": await self.repo.unread_count(receiver_id)}
