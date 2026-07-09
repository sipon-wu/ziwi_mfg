from app.repositories.tenant_repo import TenantRepository
from typing import Optional

class TenantService:
    def __init__(self, tenant_repo: TenantRepository):
        self.tenant_repo = tenant_repo

    async def list(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.tenant_repo.list(page, page_size)

    async def get(self, id: int) -> Optional[dict]:
        return await self.tenant_repo.get(id)

    async def get_by_tenant_id(self, tenant_id: str) -> Optional[dict]:
        return await self.tenant_repo.get_by_tenant_id(tenant_id)

    async def create(self, data: dict) -> dict:
        count = await self.tenant_repo.create(data)
        return {"affected": count}

    async def update(self, id: int, data: dict) -> dict:
        count = await self.tenant_repo.update(id, data)
        return {"affected": count}

    async def delete(self, id: int) -> dict:
        count = await self.tenant_repo.delete(id)
        return {"affected": count}
