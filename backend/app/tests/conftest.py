"""Shared fixtures for quality API tests."""

import pytest
import httpx
from unittest.mock import AsyncMock, MagicMock
from sqlalchemy.ext.asyncio import AsyncSession
from httpx import ASGITransport

from app.main import app
from app.core.database import get_db
from app.core.dependencies import get_current_user


MOCK_USER = {
    "id": 1,
    "username": "testuser",
    "real_name": "测试用户",
    "tenant_id": "default",
    "role_id": 1,
    "is_active": True,
}


async def _mock_get_db():
    """Override get_db with a mock session so no real DB is needed."""
    mock_session = AsyncMock(spec=AsyncSession)
    yield mock_session


async def _mock_get_current_user():
    """Override get_current_user with a mock user for all tests."""
    return MOCK_USER


@pytest.fixture(autouse=True)
def override_dependencies():
    """Replace get_db and get_current_user with mocks for all tests."""
    app.dependency_overrides[get_db] = _mock_get_db
    app.dependency_overrides[get_current_user] = _mock_get_current_user
    yield
    app.dependency_overrides.clear()


@pytest.fixture
async def async_client():
    """Provide an httpx AsyncClient pointed at the FastAPI app (no lifespan)."""
    transport = ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        yield client
