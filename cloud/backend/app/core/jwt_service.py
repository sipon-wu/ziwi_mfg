import uuid
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
        self, sub: str, email: str, tenant_id: str | None = None, products: list | None = None
    ) -> str:
        current_key = self.key_manager.get_current_key()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "email": email,
            "tenant_id": tenant_id,
            "products": products or [],
            "iat": int(now.timestamp()),
            "exp": int((now + timedelta(minutes=self.access_expire)).timestamp()),
        }
        headers = {"kid": current_key.kid}
        return jwt.encode(payload, current_key.private_key, algorithm="RS256", headers=headers)

    def create_refresh_token(self, sub: str) -> str:
        current_key = self.key_manager.get_current_key()
        now = datetime.now(timezone.utc)
        payload = {
            "sub": sub,
            "type": "refresh",
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
