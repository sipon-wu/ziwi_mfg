from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _get_key_manager():
    from app.main import get_key_manager
    return get_key_manager()


@router.get("/public-key")
async def get_public_key():
    km = _get_key_manager()
    return {"data": {"keys": km.get_public_jwks()}}
