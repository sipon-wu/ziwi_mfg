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
        # create 走 INSERT ... RETURNING id，返回值即新用户 PK
        user_id = await self.user_repo.create(data)
        return {"affected": 1, "id": user_id}

    async def update(self, id: int, data: dict) -> dict:
        # B9: 组织归属字段不参与 users 表通用 SET（由 user_organizations 单独维护）
        org_id = data.pop("org_id", None)
        org_ids = data.pop("org_ids", None)
        if "password" in data:
            data["password_hash"] = hash_password(data.pop("password"))

        # 空 SET 会生成 "UPDATE users SET  WHERE ..." 这种非法 SQL，纯组织变更时必须跳过
        count = await self.user_repo.update(id, data) if data else 0

        result = {"affected": count}
        if org_id is not None or org_ids is not None:
            sync = await self.user_repo.sync_user_orgs(id, org_id, org_ids)
            # users.primary_org_id 与 user_organizations 保持一致
            if sync.get("primary_org_id") is not None or org_id is None:
                primary = await self.user_repo.update(id, {"primary_org_id": sync["primary_org_id"]})
                result["affected"] = (result["affected"] or 0) + (primary or 0)
            result["org"] = sync
        return result

    async def delete(self, id: int) -> dict:
        count = await self.user_repo.delete(id)
        return {"affected": count}
