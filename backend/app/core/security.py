"""
密码哈希 + cloud JWT 验签工具。

变更说明 (2026-07-10):
- 移除 create_access_token / create_refresh_token / verify_token（本地 HS256 签发）
- 保留 hash_password / verify_password（change-password 仍需密码哈希）
- 新增 verify_cloud_token（thin wrapper，调用 app.core.jwks.verify_access_token）
"""

from passlib.context import CryptContext

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
    """验签 cloud.ziwi.cn 签发的 RS256 JWT 并返回 payload。

    本函数是 app.core.jwks.verify_access_token 的 async thin wrapper，
    供 dependencies.get_current_user 调用。

    Args:
        token: JWT access_token 字符串

    Returns:
        dict: JWT payload claims（sub, email, tenant_id, products, iat, exp）

    Raises:
        ExpiredSignatureError: token 已过期
        JWTClaimsError: claims 不合法
        JWTError: 签名/格式无效
    """
    return await _verify_cloud(token)


# ─── 公开 API ──────────────────────────────────────────────
__all__ = [
    "hash_password",
    "verify_password",
    "verify_cloud_token",
    "classify_jwt_error",
    "TokenVerifyError",
]
