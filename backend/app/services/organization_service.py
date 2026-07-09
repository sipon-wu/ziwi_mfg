from app.repositories.organization_repo import OrganizationRepository
from typing import Optional, List, Dict


class OrganizationService:
    def __init__(self, repo: OrganizationRepository):
        self.repo = repo

    async def list_teams(self, page: int = 1, page_size: int = 20) -> dict:
        return await self.repo.list_teams(page, page_size)

    async def create_team(self, data: dict) -> dict:
        return {"id": await self.repo.create_team(data)}

    async def list_employees(self, page: int = 1, page_size: int = 20, team_id: int = None) -> dict:
        return await self.repo.list_employees(page, page_size, team_id)

    async def create_employee(self, data: dict) -> dict:
        return {"id": await self.repo.create_employee(data)}

    async def update_employee(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_employee(id, data)}

    async def delete_employee(self, id: int) -> int:
        return await self.repo.delete_employee(id)
