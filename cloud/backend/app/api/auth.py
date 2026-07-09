"""Authentication endpoints – login, register, refresh, me."""

import uuid
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import update, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_db
from app.core.jwt_service import JWTService
from app.services.auth_service import AuthService
from app.schemas.user import UserRegisterRequest, UserResponse
from app.schemas.auth import LoginRequest, TokenResponse, RefreshRequest
from app.config import settings
from app.services.user_service import UserService
from app.models.token import RefreshTokenRecord
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

    # ── refresh token rotation: create tracking record ──
    family_id = str(uuid.uuid4())
    jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    record = RefreshTokenRecord(
        jti=jti,
        user_id=user.id,
        family_id=family_id,
        status="active",
        issued_at=now,
        expires_at=now + timedelta(days=settings.jwt_refresh_expire_days),
    )
    db.add(record)
    await db.commit()

    refresh_token = jwt_svc.create_refresh_token(sub=str(user.id), jti=jti, family_id=family_id)

    return {
        "data": TokenResponse(
            access_token=access_token,
            refresh_token=refresh_token,
            expires_in=settings.jwt_access_expire_minutes * 60,
        ).model_dump()
    }


@router.post("/refresh")
async def refresh(req: RefreshRequest, db: AsyncSession = Depends(get_db)):
    """Refresh token rotation with replay detection (RFC 9700).

    Normal flow:
        1. Verify the inbound refresh_token.
        2. Atomically mark its ``jti`` as ``used``.
        3. Issue a new refresh_token (same family, new jti) and access_token.

    Replay detection:
        If a token already marked ``used`` is presented again, the **entire
        family** is revoked — forcing the legitimate holder to re-authenticate.
    """
    jwt_svc = _get_jwt_service()

    # ── 1. verify signature & expiry ──
    try:
        payload = jwt_svc.verify_token(req.refresh_token)
    except ValueError as e:
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": str(e)})

    # ── 2. validate token type ──
    if payload.get("type") != "refresh":
        raise HTTPException(status_code=401, detail={"code": "INVALID_TOKEN", "message": "Not a refresh token"})

    jti: str | None = payload.get("jti")
    family_id: str | None = payload.get("family_id")
    sub: str | None = payload.get("sub")

    if not jti or not family_id or not sub:
        raise HTTPException(status_code=401, detail={
            "code": "INVALID_TOKEN", "message": "Token missing jti, family_id, or sub",
        })

    # ── 3. atomic status transition: active → used ──
    result = await db.execute(
        update(RefreshTokenRecord)
        .where(RefreshTokenRecord.jti == jti, RefreshTokenRecord.status == "active")
        .values(status="used")
        .returning(RefreshTokenRecord.id)
    )
    updated_id = result.scalar_one_or_none()

    if updated_id is None:
        # Another request already consumed this token — check current status.
        record_result = await db.execute(
            select(RefreshTokenRecord).where(RefreshTokenRecord.jti == jti)
        )
        record: RefreshTokenRecord | None = record_result.scalar_one_or_none()

        if record is None or record.status == "revoked":
            raise HTTPException(status_code=401, detail={
                "code": "INVALID_TOKEN", "message": "Token not found or revoked",
            })

        if record.status == "used":
            # ⚠️  replay attack detected — revoke the entire family ⚠️
            await db.execute(
                update(RefreshTokenRecord)
                .where(RefreshTokenRecord.family_id == record.family_id)
                .values(status="revoked")
            )
            await db.commit()
            raise HTTPException(status_code=401, detail={
                "code": "TOKEN_REUSE_DETECTED",
                "message": "Token reuse detected — entire token family revoked",
            })

        # Should never reach here (only valid statuses are active/used/revoked).
        raise HTTPException(status_code=401, detail={
            "code": "INVALID_TOKEN", "message": "Unexpected token status",
        })

    # ── 4. normal rotation: issue new tokens ──
    new_jti = str(uuid.uuid4())
    now = datetime.now(timezone.utc)

    new_record = RefreshTokenRecord(
        jti=new_jti,
        user_id=uuid.UUID(sub),
        family_id=family_id,
        status="active",
        issued_at=now,
        expires_at=now + timedelta(days=settings.jwt_refresh_expire_days),
    )
    db.add(new_record)
    await db.commit()

    # ── 5. look up user for full access_token claims ──
    user_service = UserService(db)
    user = await user_service.get_by_id(uuid.UUID(sub))
    if not user:
        raise HTTPException(status_code=404, detail={
            "code": "USER_NOT_FOUND", "message": "User not found",
        })

    # ── 6. issue new token pair ──
    new_access_token = jwt_svc.create_access_token(
        sub=str(user.id),
        email=user.email,
        tenant_id=user.tenant_id,
        products=user.products,
    )
    new_refresh_token = jwt_svc.create_refresh_token(
        sub=str(user.id), jti=new_jti, family_id=family_id,
    )

    return {
        "data": TokenResponse(
            access_token=new_access_token,
            refresh_token=new_refresh_token,
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
