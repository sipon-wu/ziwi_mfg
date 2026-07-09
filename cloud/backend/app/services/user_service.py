import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserResponse


class UserService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def get_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()

    async def get_by_email(self, email: str) -> User | None:
        result = await self.db.execute(select(User).where(User.email == email))
        return result.scalar_one_or_none()

    async def update_products(self, user_id: uuid.UUID, products: list) -> UserResponse:
        user = await self.get_by_id(user_id)
        if not user:
            raise ValueError("User not found")
        user.products = products
        await self.db.commit()
        await self.db.refresh(user)
        return UserResponse.model_validate(user)
