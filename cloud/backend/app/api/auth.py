from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.jwt_service import JWTService
from app.services.auth_service import AuthService
from app.schemas.user import UserRegisterRequest, UserResponse
from app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest
from app.config import settings
from app.services.user_service import UserService
from app.api.deps import require_token

router = APIRouter(prefix="/api/v1/auth", tags=["auth"])


def _get_jwt_service() -> JWTService:
    from app.main import get_jwt_service
    return get_jwt_service()


@router.post("/register", status_code=201)
async def register(req: UserRegisterRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user = await service.register(req)
        return {"data": user.model_dump(mode="json")}
    except ValueError as e:
        msg = str(e)
        if "already registered" in msg:
            raise HTTPException(status_code=409, detail={"code": "EMAIL_EXISTS", "message": msg})
        raise HTTPException(status_code=400, detail={"code": "REGISTER_FAILED", "message": msg})


@router.post("/login")
async def login(req: LoginRequest, db: AsyncSession = Depends(get_db)):
    service = AuthService(db)
    try:
        user = await service.authenticate(req.email, req.password)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={"code": "AUTH_FAILED", "message": str(e)})

    jwt_svc = _get_jwt_service()
    access_token = jwt_svc.create_access_token(
        sub=str(user.id), email=user.email, tenant_id=user.tenant_id, products=user.products
    )
    refresh_token = jwt_svc.create_refresh_token(sub=str(user.id))
    return {
        "data": TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_expire_minutes * 60,
        ).model_dump()
    }


@router.post("/refresh")
async def refresh(req: RefreshRequest):
    jwt_svc = _get_jwt_service()
    try:
        payload = jwt_svc.verify_token(req.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": str(e)})

    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "Not a refresh token"})

    new_token = jwt_svc.create_access_token(sub=payload["sub"], email=payload.get("email", ""))
    return {
        "data": TokenResponse(
            access_token=new_token,
            refresh_token=req.refresh_token,
            expires_in=settings.jwt_access_expire_minutes * 60,
        ).model_dump()
    }


@router.get("/me")
async def me(db: AsyncSession = Depends(get_db), token: str = Depends(require_token)):
    jwt_svc = _get_jwt_service()
    try:
        payload = jwt_svc.verify_token(token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": str(e)})

    service = UserService(db)
    user = await service.get_by_email(payload.get("email", ""))
    if not user:
        raise HTTPException(status_code=404, detail={"code": "USER_NOT_FOUND", "message": "User not found"})
    return {"data": UserResponse.model_validate(user).model_dump(mode="json")}
