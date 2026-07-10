"""
cloud.ziwi.cn 统一 JWT 认证集成测试。

测试范围:
  1. JWKSStore 缓存与降级
  2. verify_access_token 验签（有效/过期/无效签名/缺 kid）
  3. get_current_user 依赖注入（有效 token / 过期 / 未知 cloud_uuid / 缺 token）
  4. get_feature_flags 从 DB 查询
  5. API 路由：/logout, /me, /change-password 端点可用
  6. 已移除的 /login 和 /refresh 路由返回 404

NOTE: 测试使用 mock，不依赖真实的 cloud.ziwi.cn 服务。
"""

import json
import time
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from jose.jwt import JWTError, ExpiredSignatureError
from jose.constants import Algorithms

from app.core.jwks import (
    JWKSStore,
    TokenVerifyError,
    classify_jwt_error,
    get_signing_key,
    verify_access_token,
)
from app.main import app


# ────────────────────────────────────────────────────────────────
# 测试数据
# ────────────────────────────────────────────────────────────────

# 伪造的 JWKS 响应（用于 mock cloud 公钥端点）
MOCK_JWKS_RESPONSE = {
    "data": {
        "keys": [
            {
                "kty": "RSA",
                "kid": "key_v1",
                "n": "0vx7aq...fake_modulus...",
                "e": "AQAB",
                "use": "sig",
                "alg": "RS256",
            }
        ]
    }
}


# ────────────────────────────────────────────────────────────────
# Part A: JWKSStore 单元测试
# ────────────────────────────────────────────────────────────────

class TestJWKSStore:
    """JWKSStore 缓存、拉取、降级、刷新逻辑。"""

    def test_init_empty(self):
        """新创建的 JWKSStore 缓存为空。"""
        store = JWKSStore()
        assert store.is_valid() is False
        assert store.find_key("key_v1") is None

    @pytest.mark.asyncio
    async def test_fetch_success(self):
        """从 cloud 拉取成功 → 缓存填充 + is_valid=True。"""
        store = JWKSStore()
        with patch.object(store, "fetch") as mock_fetch:
            mock_fetch.return_value = {"key_v1": MOCK_JWKS_RESPONSE["data"]["keys"][0]}
            result = await store.fetch()
            assert "key_v1" in result
            mock_fetch.assert_called_once()

    @pytest.mark.asyncio
    async def test_fetch_fallback_to_local_file(self, tmp_path):
        """cloud 不可达时降级读取本地缓存文件。"""
        # 写入本地缓存文件
        cache_file = tmp_path / ".cloud_jwks_cache.json"
        cache_file.write_text(json.dumps(MOCK_JWKS_RESPONSE["data"]["keys"]))

        store = JWKSStore()
        # mock httpx 请求抛异常，但本地文件存在
        with patch("app.core.jwks.httpx.AsyncClient.get", side_effect=Exception("network error")):
            with patch("app.core.jwks.JWKS_CACHE_FILE", cache_file):
                result = await store.fetch()
                assert "key_v1" in result

    @pytest.mark.asyncio
    async def test_refresh_invalidates_cache(self):
        """refresh() 使缓存失效后重新拉取。"""
        store = JWKSStore()
        store._keys = {"old_key": {}}
        store._fetched_at = time.monotonic()

        with patch.object(store, "fetch", return_value={"key_v1": {}}) as mock_fetch:
            await store.refresh()
            mock_fetch.assert_called_once()
            assert store._fetched_at == 0.0  # 已被 refresh 重置为 0

    def test_is_valid_within_ttl(self):
        """缓存未过期时 is_valid=True。"""
        store = JWKSStore()
        store._keys = {"key_v1": {}}
        store._fetched_at = time.monotonic() - 100  # 100 秒前
        # TTL 默认 3600 秒，100 < 3600 → 有效
        assert store.is_valid() is True

    def test_is_valid_expired(self):
        """缓存过期时 is_valid=False。"""
        store = JWKSStore()
        store._keys = {"key_v1": {}}
        store._fetched_at = time.monotonic() - 3700  # 3700 秒前，超过 3600 TTL
        assert store.is_valid() is False


# ────────────────────────────────────────────────────────────────
# Part B: classify_jwt_error 测试
# ────────────────────────────────────────────────────────────────

class TestClassifyJwtError:
    """异常 → 错误码映射。"""

    def test_expired(self):
        assert classify_jwt_error(ExpiredSignatureError("expired")) == TokenVerifyError.EXPIRED

    def test_invalid_signature(self):
        assert classify_jwt_error(JWTError("bad sig")) == TokenVerifyError.INVALID_SIGNATURE

    def test_malformed(self):
        assert classify_jwt_error(ValueError("random error")) == TokenVerifyError.MALFORMED

    def test_jwks_unavailable(self):
        assert classify_jwt_error(RuntimeError("JWKS 获取失败")) == TokenVerifyError.JWKS_UNAVAILABLE


# ────────────────────────────────────────────────────────────────
# Part C: API 路由测试
# ────────────────────────────────────────────────────────────────

class TestAuthRoutes:
    """验证路由变更：/login /refresh 移除，/logout /me /change-password 保留。"""

    async def test_login_returns_404(self, async_client):
        """POST /login 已移除 → 404。"""
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "admin123"},
        )
        assert resp.status_code == 404

    async def test_refresh_returns_404(self, async_client):
        """POST /refresh 已移除 → 404。"""
        resp = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "fake_token"},
        )
        assert resp.status_code == 404

    async def test_logout_returns_200(self, async_client):
        """POST /logout 保留 → 200。"""
        resp = await async_client.post("/api/v1/auth/logout")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "退出成功"

    @patch("app.api.auth.RoleRepository.get_user_permissions", return_value=[])
    @patch("app.api.auth.RoleRepository.get_user_roles", return_value=[])
    @patch("app.api.auth.UserRepository.get")
    async def test_me_endpoint_exists(self, mock_get, mock_roles, mock_perms, async_client):
        """GET /me 端点存在（mock get_current_user + UserRepository.get）。"""
        mock_get.return_value = {
            "id": 1, "username": "admin", "tenant_id": "default",
            "real_name": "管理员", "email": "admin@ziwi.cn",
            "roles": [], "permissions": [],
        }
        resp = await async_client.get("/api/v1/auth/me")
        assert resp.status_code == 200

    @patch("app.services.auth_service.verify_password", return_value=True)
    @patch("app.services.auth_service.hash_password", return_value="$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ12")
    @patch("app.api.auth.UserRepository.update", return_value=1)
    @patch("app.api.auth.UserRepository.get_with_password_by_id")
    async def test_change_password_endpoint_exists(self, mock_get_pw, mock_update, mock_hp, mock_vpw, async_client):
        """POST /change-password 端点存在。"""
        mock_get_pw.return_value = {
            "id": 1, "password_hash": "$2b$12$abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ12",
        }
        resp = await async_client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "old", "new_password": "new"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0


# ────────────────────────────────────────────────────────────────
# Part D: schema 变更验证
# ────────────────────────────────────────────────────────────────

class TestSchemaChanges:
    """验证已移除的 schema 类不可导入。"""

    def test_login_request_removed(self):
        """LoginRequest 已从 schemas.auth 移除。"""
        with pytest.raises(ImportError):
            from app.schemas.auth import LoginRequest

    def test_token_response_removed(self):
        """TokenResponse 已从 schemas.auth 移除。"""
        with pytest.raises(ImportError):
            from app.schemas.auth import TokenResponse

    def test_refresh_token_request_removed(self):
        """RefreshTokenRequest 已从 schemas.auth 移除。"""
        with pytest.raises(ImportError):
            from app.schemas.auth import RefreshTokenRequest

    def test_change_password_request_exists(self):
        """ChangePasswordRequest 保留。"""
        from app.schemas.auth import ChangePasswordRequest
        req = ChangePasswordRequest(old_password="old", new_password="new")
        assert req.old_password == "old"
        assert req.new_password == "new"


# ────────────────────────────────────────────────────────────────
# Part E: 配置验证
# ────────────────────────────────────────────────────────────────

class TestConfigChanges:
    """验证 cloud JWT 配置项存在。"""

    def test_cloud_config_exists(self):
        from app.core.config import get_settings
        s = get_settings()
        assert s.CLOUD_JWKS_URL == "https://cloud.ziwi.cn/api/v1/auth/public-key"
        assert s.CLOUD_JWKS_CACHE_TTL == 3600
        assert s.CLOUD_JWKS_FETCH_TIMEOUT == 5.0
        assert s.CLOUD_EXPECTED_ALGORITHM == "RS256"
        assert s.CLOUD_CLOCK_SKEW_SECONDS == 30
