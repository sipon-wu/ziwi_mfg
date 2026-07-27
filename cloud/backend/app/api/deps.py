"""FastAPI dependencies for auth & platform."""

from typing import Optional
from fastapi import Depends, Header, HTTPException, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
import uuid

from app.core.database import get_db
from app.models.platform import PlatformUser

bearer_scheme = HTTPBearer()


async def require_token(authorization: Optional[str] = Header(None)) -> str:
    """原始 token 验证：从 Header 取 Bearer token。"""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="缺少 Authorization header")
    return authorization[7:]


async def get_current_platform_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
) -> PlatformUser:
    """验证平台用户 JWT，返回 PlatformUser 对象。"""
    # 延迟导入避免循环依赖
    from app.main import jwt_service

    token = credentials.credentials
    try:
        payload = jwt_service.verify_token(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Token 无效: {e}",
        )

    user_id = payload.get("sub")
    if not user_id:
        raise HTTPException(status_code=401, detail="Token 缺少 sub")

    result = await db.execute(
        select(PlatformUser).where(PlatformUser.id == uuid.UUID(user_id))
    )
    user = result.scalar_one_or_none()
    if not user or not user.is_active:
        raise HTTPException(status_code=401, detail="账号不存在或已被禁用")

    return user
