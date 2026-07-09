import os
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend


class KeyPairEntry:
    def __init__(self, kid: str, private_key, public_key, created_at: datetime, expires_at: Optional[datetime] = None):
        self.kid = kid
        self.private_key = private_key
        self.public_key = public_key
        self.created_at = created_at
        self.expires_at = expires_at

    @property
    def is_active(self) -> bool:
        return self.expires_at is None or datetime.now(timezone.utc) < self.expires_at

    def to_jwk(self) -> dict:
        pub_numbers = self.public_key.public_numbers()
        n_bytes = pub_numbers.n.to_bytes((pub_numbers.n.bit_length() + 7) // 8, "big")
        e_bytes = pub_numbers.e.to_bytes((pub_numbers.e.bit_length() + 7) // 8, "big")
        import base64
        n_b64 = base64.urlsafe_b64encode(n_bytes).rstrip(b"=").decode("ascii")
        e_b64 = base64.urlsafe_b64encode(e_bytes).rstrip(b"=").decode("ascii")
        return {
            "kty": "RSA",
            "kid": self.kid,
            "n": n_b64,
            "e": e_b64,
            "use": "sig",
            "alg": "RS256",
        }


class RSAKeyManager:
    def __init__(self, keys_dir: str = "keys"):
        self.keys_dir = Path(keys_dir)
        self.keys_dir.mkdir(parents=True, exist_ok=True)
        self._keys: dict[str, KeyPairEntry] = {}
        self._load_or_generate_keys()

    def _load_or_generate_keys(self):
        pem_files = sorted(self.keys_dir.glob("*_private.pem"))
        if pem_files:
            for pem_path in pem_files:
                kid = pem_path.stem.replace("_private", "")
                priv = serialization.load_pem_private_key(
                    pem_path.read_bytes(), password=None, backend=default_backend()
                )
                pub_path = self.keys_dir / f"{kid}_public.pem"
                pub = serialization.load_pem_public_key(
                    pub_path.read_bytes(), backend=default_backend()
                )
                created_at = datetime.fromtimestamp(pem_path.stat().st_ctime, tz=timezone.utc)
                self._keys[kid] = KeyPairEntry(kid, priv, pub, created_at)
        else:
            kid = "key_v1"
            self._generate_key_pair(kid)

    def _generate_key_pair(self, kid: str):
        private_key = rsa.generate_private_key(
            public_exponent=65537, key_size=4096, backend=default_backend()
        )
        public_key = private_key.public_key()

        priv_path = self.keys_dir / f"{kid}_private.pem"
        pub_path = self.keys_dir / f"{kid}_public.pem"
        priv_path.write_bytes(
            private_key.private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        pub_path.write_bytes(
            public_key.public_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PublicFormat.SubjectPublicKeyInfo,
            )
        )
        created_at = datetime.now(timezone.utc)
        self._keys[kid] = KeyPairEntry(kid, private_key, public_key, created_at)

    def get_current_key(self) -> KeyPairEntry:
        active = [k for k in self._keys.values() if k.is_active]
        if not active:
            kid = f"key_v{len(self._keys) + 1}"
            self._generate_key_pair(kid)
            return self._keys[kid]
        active.sort(key=lambda k: k.created_at, reverse=True)
        return active[0]

    def get_public_jwks(self) -> list[dict]:
        keys = [k for k in self._keys.values() if k.is_active]
        keys.sort(key=lambda k: k.created_at, reverse=True)
        return [k.to_jwk() for k in keys]

    def get_private_key(self, kid: str):
        entry = self._keys.get(kid)
        if entry:
            return entry.private_key
        current = self.get_current_key()
        return current.private_key

    def rotate_keys(self) -> str:
        current = self.get_current_key()
        current.expires_at = datetime.now(timezone.utc) + timedelta(hours=1)
        kid = f"key_v{len(self._keys) + 1}"
        self._generate_key_pair(kid)
        return kid
