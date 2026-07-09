# JWT + 密码工具
from datetime import datetime, timedelta, timezone
from typing import Dict, Optional
from jose import JWTError, jwt
from passlib.context import CryptContext
from app.core.config import get_settings

settings = get_settings()
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

def hash_password(password: str) -> str:
    return pwd_context.hash(password)

def verify_password(plain_password: str, hashed_password: str) -> bool:
    return pwd_context.verify(plain_password, hashed_password)

def create_access_token(
    data: dict,
    expires_delta: Optional[timedelta] = None,
    features: Optional[Dict[str, bool]] = None,
) -> str:
    """创建 JWT access token。

    [rev] 新增 features 参数，将租户套餐信息写入 JWT payload。

    Args:
        data: JWT payload 数据
        expires_delta: 过期时间（可选，默认使用配置值）
        features: 租户 feature_flags dict，写入 JWT claims 中的 features 字段
    """
    to_encode = data.copy()
    if features:
        to_encode["features"] = features
    expire = datetime.now(timezone.utc) + (expires_delta or timedelta(minutes=settings.JWT_ACCESS_TOKEN_EXPIRE_MINUTES))
    to_encode.update({"exp": expire})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def create_refresh_token(data: dict) -> str:
    to_encode = data.copy()
    expire = datetime.now(timezone.utc) + timedelta(days=settings.JWT_REFRESH_TOKEN_EXPIRE_DAYS)
    to_encode.update({"exp": expire, "type": "refresh"})
    return jwt.encode(to_encode, settings.JWT_SECRET_KEY, algorithm=settings.JWT_ALGORITHM)

def verify_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, settings.JWT_SECRET_KEY, algorithms=[settings.JWT_ALGORITHM])
        return payload
    except JWTError:
        from fastapi import HTTPException
        raise HTTPException(status_code=401, detail={"code": "401-1001", "message": "Token 无效或已过期", "request_id": ""})
