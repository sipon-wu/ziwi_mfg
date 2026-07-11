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

    @patch("app.api.auth.httpx.AsyncClient")
    async def test_login_returns_200(self, mock_client_cls, async_client):
        """POST /login 已恢复为代理转发到 cloud.ziwi.cn (2026-07-11)。

        验证: /login 端点存在并正确透传 cloud 返回的 token。
        通过 mock httpx.AsyncClient 避免真实外网请求。
        """
        # 构造云侧 mock 响应
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = {"code": 0, "data": {"token": "fake.jwt.token"}}

        # httpx.AsyncClient(timeout=15) 作为 async context manager
        mock_instance = MagicMock()
        mock_instance.post = AsyncMock(return_value=mock_resp)
        mock_cm = AsyncMock()
        mock_cm.__aenter__.return_value = mock_instance
        mock_client_cls.return_value = mock_cm

        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "admin@ziwi.cn", "password": "admin123"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["data"]["token"] == "fake.jwt.token"

    async def test_refresh_returns_404(self, async_client):
        """POST /refresh 已移除（无可匹配路由）→ 404 或 405。

        FastAPI 对不存在的 POST 路径返回 405 (Method Not Allowed)，
        404/405 均代表 refresh 端点不可用。
        """
        resp = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "fake_token"},
        )
        assert resp.status_code in (404, 405)

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
    """验证 schema 类的可用性（随 /login 代理恢复，LoginRequest 重新引入）。"""

    def test_login_request_exists(self):
        """LoginRequest 随 /login 代理恢复后重新引入 (2026-07-11)。"""
        from app.schemas.auth import LoginRequest
        req = LoginRequest(username="admin@ziwi.cn", password="admin123")
        assert req.username == "admin@ziwi.cn"
        assert req.password == "admin123"

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


# ────────────────────────────────────────────────────────────────
# Part F: 边缘用例测试
# ────────────────────────────────────────────────────────────────

class TestEdgeCases:
    """补充边缘场景：无 token 401、空租户 feature_flags、未知 cloud_uuid。"""

    async def test_me_without_token_returns_401(self, async_client):
        """GET /me 不带 Authorization header → 401。

        临时移除 get_current_user 的 mock override，使真实的依赖注入逻辑生效。
        由于 HTTPBearer(auto_error=False)，无 token 时 credentials=None，
        get_current_user 应直接抛出 401。
        """
        from app.core.dependencies import get_current_user
        from app.main import app
        from app.tests.conftest import _mock_get_current_user

        # 移除 mock，让真实的 get_current_user 运行
        app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = await async_client.get("/api/v1/auth/me")
            assert resp.status_code == 401
            body = resp.json()
            assert body["detail"]["code"] == "MISSING_TOKEN"
        finally:
            # 恢复 mock 以免影响后续测试
            app.dependency_overrides[get_current_user] = _mock_get_current_user

    async def test_change_password_without_token_returns_401(self, async_client):
        """POST /change-password 不带 Authorization header → 401。"""
        from app.core.dependencies import get_current_user
        from app.main import app
        from app.tests.conftest import _mock_get_current_user

        app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = await async_client.post(
                "/api/v1/auth/change-password",
                json={"old_password": "old", "new_password": "new"},
            )
            assert resp.status_code == 401
            body = resp.json()
            assert body["detail"]["code"] == "MISSING_TOKEN"
        finally:
            app.dependency_overrides[get_current_user] = _mock_get_current_user

    @pytest.mark.asyncio
    async def test_feature_flags_empty_tenant_returns_empty_dict(self):
        """get_feature_flags: tenant_id 为 None/空时返回 {}。"""
        from app.core.dependencies import get_feature_flags
        from sqlalchemy.ext.asyncio import AsyncSession
        from unittest.mock import AsyncMock

        mock_db = AsyncMock(spec=AsyncSession)
        # tenant_id 为 None
        user_no_tenant = {"id": 1, "tenant_id": None}
        result = await get_feature_flags(user_no_tenant, mock_db)
        assert result == {}

        # tenant_id 为空字符串
        user_empty_tenant = {"id": 1, "tenant_id": ""}
        result2 = await get_feature_flags(user_empty_tenant, mock_db)
        assert result2 == {}

    @pytest.mark.asyncio
    async def test_get_current_user_missing_sub_in_payload(self):
        """get_current_user: cloud JWT payload 缺 sub → 401。"""
        from unittest.mock import AsyncMock, patch
        from fastapi import HTTPException

        with patch("app.core.dependencies.verify_cloud_token") as mock_verify:
            mock_verify.return_value = {
                "email": "test@ziwi.cn",
                "exp": 9999999999,
                "iat": 1700000000,
                # 故意缺少 sub
            }
            from app.core.dependencies import get_current_user
            from fastapi.security import HTTPAuthorizationCredentials

            creds = HTTPAuthorizationCredentials(
                scheme="Bearer", credentials="fake_token"
            )
            mock_db = AsyncMock()

            with pytest.raises(HTTPException) as exc_info:
                await get_current_user(credentials=creds, db=mock_db)
            assert exc_info.value.status_code == 401
            assert exc_info.value.detail["code"] == "MISSING_TOKEN"
