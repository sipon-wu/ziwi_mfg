from app.repositories.tpm_repo import TpmRepository
from typing import Optional, Dict


class TpmService:
    def __init__(self, repo: TpmRepository):
        self.repo = repo

    async def list_categories(self) -> list:
        return await self.repo.list_categories()

    async def create_category(self, data: dict) -> dict:
        return {"id": await self.repo.create_category(data)}

    async def list_equipment(self, page: int, page_size: int, keyword: str = None, status: str = None) -> dict:
        return await self.repo.list_equipment(page, page_size, keyword, status)

    async def create_equipment(self, data: dict) -> dict:
        return {"id": await self.repo.create_equipment(data)}

    async def get_equipment(self, id: int) -> Optional[dict]:
        return await self.repo.get_equipment(id)

    async def update_equipment(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_equipment(id, data)}

    async def delete_equipment(self, id: int) -> dict:
        return {"affected": await self.repo.delete_equipment(id)}

    async def list_tasks(self, page: int, page_size: int, status: str = None) -> dict:
        return await self.repo.list_tasks(page, page_size, status)

    async def create_task(self, data: dict) -> dict:
        return {"id": await self.repo.create_task(data)}

    async def get_task(self, id: int) -> Optional[dict]:
        return await self.repo.get_task(id)

    async def update_task_status(self, id: int, status: str) -> dict:
        return {"affected": await self.repo.update_task_status(id, status)}

    async def delete_task(self, id: int) -> dict:
        return {"affected": await self.repo.delete_task(id)}

    async def list_plans(self, page: int, page_size: int) -> dict:
        return await self.repo.list_plans(page, page_size)

    async def create_plan(self, data: dict) -> dict:
        return {"id": await self.repo.create_plan(data)}

    async def list_spare_parts(self, page: int, page_size: int) -> dict:
        return await self.repo.list_spare_parts(page, page_size)

    async def create_spare_part(self, data: dict) -> dict:
        return {"id": await self.repo.create_spare_part(data)}

    async def update_spare_part(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_spare_part(id, data)}

    async def delete_spare_part(self, id: int) -> dict:
        return {"affected": await self.repo.delete_spare_part(id)}
