from app.repositories.user_repo import UserRepository
from app.repositories.role_repo import RoleRepository
from app.core.security import hash_password
from typing import Optional

class UserService:
    def __init__(self, user_repo: UserRepository, role_repo: RoleRepository):
        self.user_repo = user_repo
        self.role_repo = role_repo

    async def list(self, page: int = 1, page_size: int = 20, keyword: str = None, status: str = None) -> dict:
        return await self.user_repo.list(page, page_size, keyword, status)

    async def get(self, id: int) -> Optional[dict]:
        return await self.user_repo.get(id)

    async def create(self, data: dict) -> dict:
        data["password_hash"] = hash_password(data.pop("password"))
        count = await self.user_repo.create(data)
        return {"affected": count, "id": data.get("id")}

    async def update(self, id: int, data: dict) -> dict:
        if "password" in data:
            data["password_hash"] = hash_password(data.pop("password"))
        count = await self.user_repo.update(id, data)
        return {"affected": count}

    async def delete(self, id: int) -> dict:
        count = await self.user_repo.delete(id)
        return {"affected": count}
