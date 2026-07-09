from app.repositories.approval_repo import ApprovalRepository
from typing import Optional, List, Dict


class ApprovalService:
    def __init__(self, repo: ApprovalRepository):
        self.repo = repo

    async def list_templates(self) -> list:
        return await self.repo.list_templates()

    async def create_template(self, data: dict) -> dict:
        return {"id": await self.repo.create_template(data)}

    async def list_instances(self, page: int, page_size: int, applicant_id: int = None) -> dict:
        return await self.repo.list_instances(page, page_size, applicant_id)

    async def create_instance(self, data: dict) -> dict:
        return {"id": await self.repo.create_instance(data)}

    async def get_instance(self, id: int) -> Optional[dict]:
        return await self.repo.get_instance(id)

    async def list_nodes(self, approval_id: int) -> list:
        return await self.repo.list_nodes(approval_id)

    async def create_node(self, data: dict) -> dict:
        return {"id": await self.repo.create_node(data)}

    async def update_node(self, id: int, data: dict) -> dict:
        return {"affected": await self.repo.update_node(id, data)}

    async def update_instance_status(self, id: int, status: str) -> dict:
        return {"affected": await self.repo.update_instance_status(id, status)}
