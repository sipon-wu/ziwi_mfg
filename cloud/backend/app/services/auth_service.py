import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User
from app.schemas.user import UserRegisterRequest, UserResponse
from app.core.security import hash_password, verify_password


class AuthService:
    def __init__(self, db: AsyncSession):
        self.db = db

    async def register(self, req: UserRegisterRequest) -> UserResponse:
        existing = await self.db.execute(select(User).where(User.email == req.email))
        if existing.scalar_one_or_none():
            raise ValueError("Email already registered")

        user = User(
            id=uuid.uuid4(),
            email=req.email,
            password_hash=hash_password(req.password),
            display_name=req.display_name,
            tenant_id=req.tenant_id,
        )
        self.db.add(user)
        await self.db.commit()
        await self.db.refresh(user)
        return UserResponse.model_validate(user)

    async def authenticate(self, email: str, password: str) -> User:
        result = await self.db.execute(select(User).where(User.email == email))
        user = result.scalar_one_or_none()
        if not user or not verify_password(password, user.password_hash):
            raise ValueError("Invalid email or password")
        if not user.is_active:
            raise ValueError("Account is disabled")
        return user

    async def get_user_by_id(self, user_id: uuid.UUID) -> User | None:
        result = await self.db.execute(select(User).where(User.id == user_id))
        return result.scalar_one_or_none()
