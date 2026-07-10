"""
cloud.ziwi.cn JWT 验签模块 (RS256 / JWKS)

从 cloud.ziwi.cn 拉取 JWKS 公钥，验证 RS256 签名的 JWT access_token。
- 内存缓存 + 本地文件降级，TTL=1h
- kid 不匹配时自动强制刷新
- 线程不安全的轻量实现（FastAPI 单线程事件循环下安全）

移植自: docs/cloud-jwt-integration-guide.md §3.3
依赖: pip install python-jose[cryptography] httpx
"""

import json
import time
from enum import Enum
from pathlib import Path

import httpx
from jose import jwt
from jose.jwt import JWTError, ExpiredSignatureError, JWTClaimsError
from jose.constants import Algorithms

from app.core.config import get_settings


# ─── JWKS 缓存文件路径 ────────────────────────────────────
JWKS_CACHE_FILE = Path(__file__).parent / ".cloud_jwks_cache.json"


# ─── 错误类型枚举 ──────────────────────────────────────────
class TokenVerifyError(str, Enum):
    """JWT 验签错误码枚举。"""
    EXPIRED = "TOKEN_EXPIRED"
    INVALID_SIGNATURE = "INVALID_SIGNATURE"
    MALFORMED = "MALFORMED_TOKEN"
    UNKNOWN_KID = "UNKNOWN_KID"
    JWKS_UNAVAILABLE = "JWKS_UNAVAILABLE"


def classify_jwt_error(exc: Exception) -> TokenVerifyError:
    """将 JWT / 网络异常映射为业务错误码。

    Args:
        exc: python-jose 抛出的 JWT 异常或网络异常

    Returns:
        TokenVerifyError 枚举值
    """
    if isinstance(exc, ExpiredSignatureError):
        return TokenVerifyError.EXPIRED
    if isinstance(exc, JWTClaimsError):
        return TokenVerifyError.INVALID_SIGNATURE
    if isinstance(exc, JWTError):
        return TokenVerifyError.INVALID_SIGNATURE
    if isinstance(exc, RuntimeError) and "JWKS" in str(exc):
        return TokenVerifyError.JWKS_UNAVAILABLE
    return TokenVerifyError.MALFORMED


# ─── JWKS 缓存存储 ─────────────────────────────────────────
class JWKSStore:
    """JWKS 公钥缓存存储。

    特性：
    - 内存 dict 缓存，TTL=CLOUD_JWKS_CACHE_TTL 秒
    - 缓存失效时从 cloud 拉取
    - cloud 不可达时降级到本地 JSON 文件
    - kid 不匹配时强制刷新后重试
    """

    def __init__(self):
        self._keys: dict[str, dict] = {}
        self._fetched_at: float = 0.0

    def is_valid(self) -> bool:
        """检查内存缓存是否在 TTL 内有效。"""
        s = get_settings()
        return bool(self._keys) and (time.monotonic() - self._fetched_at < s.CLOUD_JWKS_CACHE_TTL)

    def find_key(self, kid: str) -> dict | None:
        """按 kid 查找 JWK 公钥字典。

        Args:
            kid: JWT Header 中的密钥 ID

        Returns:
            JWK dict（可直接传给 jose.jwt.decode），未找到返回 None
        """
        return self._keys.get(kid)

    async def fetch(self) -> dict[str, dict]:
        """从 cloud 拉取 JWKS，失败时降级到本地文件。

        Returns:
            {kid: jwk_dict, ...} 映射

        Raises:
            RuntimeError: cloud 不可达且无本地缓存文件
        """
        s = get_settings()
        try:
            async with httpx.AsyncClient(timeout=s.CLOUD_JWKS_FETCH_TIMEOUT) as client:
                resp = await client.get(s.CLOUD_JWKS_URL)
                resp.raise_for_status()
                keys_list = resp.json()["data"]["keys"]
                self._keys = {k["kid"]: k for k in keys_list}
                self._fetched_at = time.monotonic()
                # 写本地备份文件
                JWKS_CACHE_FILE.write_text(json.dumps(keys_list))
                return self._keys
        except Exception:
            # 降级：读本地缓存文件
            if JWKS_CACHE_FILE.exists():
                keys_list = json.loads(JWKS_CACHE_FILE.read_text())
                self._keys = {k["kid"]: k for k in keys_list}
                return self._keys
            raise RuntimeError("无法获取 JWKS 且无本地缓存") from None

    async def refresh(self) -> dict[str, dict]:
        """强制刷新 JWKS 缓存（kid 不匹配时调用）。

        使当前缓存失效后重新拉取。

        Returns:
            {kid: jwk_dict, ...} 映射
        """
        self._fetched_at = 0.0  # 使缓存失效
        return await self.fetch()


# ─── 全局单例 ──────────────────────────────────────────────
_jwks_store = JWKSStore()


async def get_signing_key(kid: str) -> dict:
    """根据 kid 获取对应的 JWK 公钥。

    缓存有效则直接返回，缓存失效则拉取。
    若 kid 不匹配则强制刷新后重试一次。

    Args:
        kid: JWT Header 中的密钥 ID

    Returns:
        JWK dict

    Raises:
        JWTError: kid 未找到（刷新后仍不匹配）
    """
    if not _jwks_store.is_valid():
        await _jwks_store.fetch()

    key = _jwks_store.find_key(kid)
    if key is None:
        # kid 不匹配 → 强制刷新后重试
        await _jwks_store.refresh()
        key = _jwks_store.find_key(kid)
        if key is None:
            raise JWTError(f"未知的 kid: {kid}")

    return key


# ─── Token 验证 ────────────────────────────────────────────
async def verify_access_token(token: str) -> dict:
    """验证 cloud.ziwi.cn 签发的 RS256 JWT access_token。

    流程：
    1. 解析 Header 获取 kid（不验签）
    2. 通过 kid 获取 JWK 公钥
    3. RS256 验签 + claims 校验（sub, email, exp, iat 必填）

    Args:
        token: JWT access_token 字符串

    Returns:
        dict: JWT payload claims（sub, email, tenant_id, products, iat, exp）

    Raises:
        ExpiredSignatureError: token 已过期
        JWTClaimsError: claims 不合法
        JWTError: 签名/格式无效或 kid 缺失
    """
    s = get_settings()

    # 1. 解析 Header 获取 kid（不验签）
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError:
        raise JWTError("无法解析 JWT Header")

    kid = unverified_header.get("kid")
    if not kid:
        raise JWTError("JWT Header 缺少 kid")

    # 2. 获取对应公钥
    jwk = await get_signing_key(kid)

    # 3. RS256 验签 + claims 校验
    expected_alg = s.CLOUD_EXPECTED_ALGORITHM
    # 将 "RS256" 字符串映射到 jose.constants.Algorithms 常量
    alg_value = getattr(Algorithms, expected_alg, Algorithms.RS256)

    payload = jwt.decode(
        token,
        jwk,
        algorithms=[alg_value],
        audience=None,  # cloud 当前未设置 aud
        options={
            "require": ["sub", "email", "exp", "iat"],
            "verify_exp": True,
            "verify_iat": True,
        },
        leeway=s.CLOUD_CLOCK_SKEW_SECONDS,
    )

    return payload
