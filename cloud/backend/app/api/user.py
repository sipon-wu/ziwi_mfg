import uuid

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.jwt_service import JWTService
from app.services.user_service import UserService
from app.schemas.user import UserResponse
from app.api.deps import require_token

router = APIRouter(prefix="/api/v1/users", tags=["users"])


def _get_jwt_service() -> JWTService:
    from app.main import get_jwt_service
    return get_jwt_service()


@router.get("/{user_id}")
async def get_user(user_id: uuid.UUID, db: AsyncSession = Depends(get_db), token: str = Depends(require_token)):
    jwt_svc = _get_jwt_service()
    try:
        jwt_svc.verify_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "Invalid token"})

    service = UserService(db)
    user = await service.get_by_id(user_id)
    if not user:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "User not found"})
    return {"data": UserResponse.model_validate(user).model_dump(mode="json")}


@router.patch("/{user_id}/products")
async def update_products(
    user_id: uuid.UUID,
    body: dict,
    db: AsyncSession = Depends(get_db),
    token: str = Depends(require_token),
):
    jwt_svc = _get_jwt_service()
    try:
        jwt_svc.verify_token(token)
    except ValueError:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "Invalid token"})

    service = UserService(db)
    try:
        result = await service.update_products(user_id, body.get("products", []))
        return {"data": result.model_dump(mode="json")}
    except ValueError as e:
        raise HTTPException(status_code=404, detail={"code": "NOT_FOUND", "message": str(e)})
