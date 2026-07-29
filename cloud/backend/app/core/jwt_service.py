import uuid
from typing import Optional
from datetime import datetime, timedelta, timezone

from jose import JWTError, jwt
from jose.exceptions import JWTError as JoseJWTError
from app.core.rsa_key_manager import RSAKeyManager
from app.config import settings


class JWTService:
    def __init__(self, key_manager: RSAKeyManager):
        self.key_manager = key_manager
        self.access_expire = settings.jwt_access_expire_minutes
        self.refresh_expire = settings.jwt_refresh_expire_days

    def create_access_token(
        self,
        sub: str,
        email: str,
        tenant_id: Optional[str] = None,
        products: Optional[list] = None,
        account_type: str = "tenant",
        roles: Optional[list] = None,
        env: str = "prod",
        expires_minutes: Optional[int] = None,
        extra_claims: Optional[dict] = None,
    ) -> str:
        current_key = self.key_manager.get_current_key()
        now = datetime.now(timezone.utc)
        expire = expires_minutes if expires_minutes is not None else self.access_expire
        payload = {
            "sub": sub,
            "email": email,
            "tenant_id": tenant_id,
            "products": products or [],
            "account_type": account_type,
            "roles": roles or [],
            "env": env,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=expire)).timestamp()),
        }
        if extra_claims:
            payload.update(extra_claims)
        headers = {"kid": current_key.kid}
        return jwt.encode(payload, current_key.private_key, algorithm="RS256", headers=headers)

    def create_license_key(self, claims: dict, expires_at: datetime) -> str:
        """签发离线验签 license key（技术方案 v1.2 §0.5.2 私有化续期）。

        RS256 签名，typ=license；私有化实例内置 cloud 公钥（/public-key JWKS）
        本地验签 + 查有效期，离线可用。exp = license 到期时间（非 access token 短时效）。
        """
        current_key = self.key_manager.get_current_key()
        now = datetime.now(timezone.utc)
        payload = {
            **claims,
            "typ": "license",
            "iss": "cloud.ziwi.cn",
            "iat": int(now.timestamp()),
            "exp": int(expires_at.timestamp()),
        }
        headers = {"kid": current_key.kid}
        return jwt.encode(payload, current_key.private_key, algorithm="RS256", headers=headers)

    def verify_license_key(self, license_key: str) -> dict:
        """验签 license key（含 exp 校验），非 license 类型一律拒绝。"""
        payload = self.verify_token(license_key)
        if payload.get("typ") != "license":
            raise ValueError("not a license key")
        return payload

    def create_refresh_token(self, sub: str, jti: str, family_id: str) -> str:
        """Create a refresh token with JWT ID and family ID for rotation tracking.

        Args:
            sub: Subject (user ID as string).
            jti: Unique JWT ID for this specific token issuance.
            family_id: Token family ID shared across rotations.

        Returns:
            Encoded JWT string.
        """
        current_key = self.key_manager.get_current_key()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "type": "refresh",
            "jti": jti,
            "family_id": family_id,
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(days=self.refresh_expire)).timestamp()),
        }
        headers = {"kid": current_key.kid}
        return jwt.encode(payload, current_key.private_key, algorithm="RS256", headers=headers)

    def decode_token(self, token: str) -> dict:
        headers = jwt.get_unverified_header(token)
        kid = headers.get("kid")
        private_key = self.key_manager.get_private_key(kid)
        try:
            payload = jwt.decode(token, private_key.public_key(), algorithms=["RS256"])
            return payload
        except JWTError as e:
            raise ValueError(f"Token validation failed: {e}")

    def verify_token(self, token: str) -> dict:
        try:
            header = jwt.get_unverified_header(token)
            kid = header.get("kid")
            private_key = self.key_manager.get_private_key(kid)
            payload = jwt.decode(
                token,
                private_key.public_key(),
                algorithms=["RS256"],
                options={"verify_exp": True},
            )
            return payload
        except (JWTError, JoseJWTError, ValueError) as e:
            raise ValueError(f"Token verification failed: {e}")
