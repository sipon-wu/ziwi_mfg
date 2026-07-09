from typing import AsyncGenerator

import pytest
import pytest_asyncio
from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine

from app.main import app
from app.core.database import get_db
from app.models.user import Base, User

TEST_DATABASE_URL = "sqlite+aiosqlite://"


@pytest_asyncio.fixture
async def engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def db_session(engine) -> AsyncGenerator[AsyncSession, None]:
    conn = await engine.connect()
    trans = await conn.begin()
    session = AsyncSession(bind=conn, expire_on_commit=False)

    await session.begin_nested()

    yield session

    await session.close()
    await trans.rollback()
    await conn.close()


@pytest_asyncio.fixture
async def client(db_session: AsyncSession) -> AsyncGenerator[AsyncClient, None]:
    from app.core.rsa_key_manager import RSAKeyManager
    from app.core.jwt_service import JWTService
    import app.main as m

    if m.key_manager is None:
        km = RSAKeyManager(keys_dir="test_keys")
        m.key_manager = km
        m.jwt_service = JWTService(km)

    async def _get_test_db():
        yield db_session

    app.dependency_overrides[get_db] = _get_test_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()
