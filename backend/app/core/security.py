"""
密码哈希 + cloud JWT 验签 + 本地 JWT 签发工具。

变更说明 (2026-07-12):
- 新增 create_local_token / verify_local_token（本地 HS256 JWT，用于子账号认证降级）
"""

from datetime import datetime, timedelta

import jwt
from passlib.context import CryptContext

from app.core.config import get_settings
from app.core.jwks import verify_access_token as _verify_cloud
from app.core.jwks import classify_jwt_error, TokenVerifyError

# ─── 密码哈希（bcrypt） ────────────────────────────────────
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """对明文密码进行 bcrypt 哈希。

    Args:
        password: 明文密码

    Returns:
        bcrypt 哈希字符串
    """
    return pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """验证明文密码与 bcrypt 哈希是否匹配。

    Args:
        plain_password: 用户输入的明文密码
        hashed_password: 数据库中存储的 bcrypt 哈希

    Returns:
        True 表示匹配
    """
    return pwd_context.verify(plain_password, hashed_password)


# ─── cloud JWT 验签（thin wrapper） ────────────────────────
async def verify_cloud_token(token: str) -> dict:
    """验签 cloud.ziwi.cn 签发的 RS256 JWT 并返回 payload。"""
    return await _verify_cloud(token)


# ─── 本地 JWT 签发与验签（HS256，用于子账号认证降级） ──────


def create_local_token(user_id: int, tenant_id: str) -> str:
    """签发本地 HS256 JWT。"""
    settings = get_settings()
    payload = {
        "sub": str(user_id),
        "tenant_id": tenant_id,
        "iss": "mfg_local",
        "type": "local",
        "iat": datetime.utcnow(),
        "exp": datetime.utcnow() + timedelta(hours=24),
    }
    return jwt.encode(payload, settings.APP_SECRET_KEY, algorithm="HS256")


def verify_local_token(token: str) -> dict:
    """验签本地 HS256 JWT 并返回 payload。"""
    settings = get_settings()
    payload = jwt.decode(token, settings.APP_SECRET_KEY, algorithms=["HS256"])
    if payload.get("iss") != "mfg_local":
        raise jwt.InvalidTokenError("Invalid issuer: not a local token")
    return payload


# ─── 公开 API ──────────────────────────────────────────────
__all__ = [
    "hash_password",
    "verify_password",
    "verify_cloud_token",
    "create_local_token",
    "verify_local_token",
    "classify_jwt_error",
    "TokenVerifyError",
]
