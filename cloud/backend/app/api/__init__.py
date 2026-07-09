from fastapi import APIRouter

from app.api.auth import router as auth_router
from app.api.public_key import router as public_key_router
from app.api.user import router as user_router

api_router = APIRouter()
api_router.include_router(auth_router)
api_router.include_router(public_key_router)
api_router.include_router(user_router)
