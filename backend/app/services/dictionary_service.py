from app.repositories.dictionary_repo import DictionaryRepository
from typing import Optional


class DictionaryService:
    def __init__(self, repo: DictionaryRepository):
        self.repo = repo

    async def list_dicts(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.repo.list_dicts(page, page_size)

    async def get_dict(self, id: int) -> Optional[dict]:
        return await self.repo.get_dict(id)

    async def create_dict(self, data: dict) -> dict:
        count = await self.repo.create_dict(data)
        return {"affected": count}

    async def update_dict(self, id: int, data: dict) -> dict:
        count = await self.repo.update_dict(id, data)
        return {"affected": count}

    async def get_dict_items(self, code: str) -> list:
        d = await self.repo.get_dict_by_code(code)
        if not d:
            return []
        return await self.repo.list_items(d["id"])

    async def create_item(self, data: dict) -> dict:
        count = await self.repo.create_item(data)
        return {"affected": count}

    async def update_item(self, id: int, data: dict) -> dict:
        count = await self.repo.update_item(id, data)
        return {"affected": count}

    async def delete_item(self, id: int) -> int:
        return await self.repo.delete_item(id)
