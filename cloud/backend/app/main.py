from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import settings
from app.core.rsa_key_manager import RSAKeyManager
from app.core.jwt_service import JWTService
from app.core.database import engine
from app.models import Base
from app.api import api_router

key_manager: RSAKeyManager | None = None
jwt_service: JWTService | None = None


def get_key_manager() -> RSAKeyManager:
    assert key_manager is not None, "key_manager not initialized"
    return key_manager


def get_jwt_service() -> JWTService:
    assert jwt_service is not None, "jwt_service not initialized"
    return jwt_service


@asynccontextmanager
async def lifespan(app: FastAPI):
    global key_manager, jwt_service
    km = RSAKeyManager(keys_dir=settings.key_dir)
    key_manager = km
    jwt_service = JWTService(km)
    # Phase 1 fallback: create tables on startup (alembic/versions is empty).
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="cloud.ziwi.cn IdP", version="0.1.0", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins.split(",") if settings.cors_origins != "*" else ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(api_router)


@app.get("/health")
async def health():
    return {"status": "ok"}
