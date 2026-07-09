"""
Test suite for M00-Auth Module (7 test cases).

Testing strategy:
  - Mock Repo methods (no real database)
  - Mock security functions (password verify/hash, JWT creation, token verify)
  - Override get_db / get_current_user via conftest.py
  - Use httpx.AsyncClient + ASGITransport to send requests
"""

import pytest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Test data
# ---------------------------------------------------------------------------

MOCK_USER_WITH_PW = {
    "id": 1,
    "username": "admin",
    "password_hash": "$2b$12$fakehashforunittest",
    "tenant_id": "default",
    "status": "active",
}

MOCK_USER_INFO = {
    "id": 1,
    "username": "admin",
    "tenant_id": "default",
    "real_name": "管理员",
    "email": "admin@ziwi.cn",
    "phone": "13800138000",
    "avatar_url": None,
    "status": "active",
    "roles": ["admin"],
    "last_login_at": None,
    "created_at": "2025-01-01T00:00:00",
}

MOCK_ROLES = [
    {"id": 1, "code": "admin", "name": "管理员", "tenant_id": "default",
     "description": "系统管理员", "is_system": True, "created_at": "2025-01-01T00:00:00"},
]

MOCK_PERMISSIONS = ["system:config", "user:manage"]

# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestAuthAPI:
    """7 test cases covering login / me / refresh / change-password."""

    # ── Login ──────────────────────────────────────────────────────────

    @patch("app.services.auth_service.create_refresh_token", return_value="fake_refresh")
    @patch("app.services.auth_service.create_access_token", return_value="fake_access")
    @patch("app.services.auth_service.verify_password", return_value=True)
    @patch("app.api.auth.UserRepository.get_with_password")
    async def test_login_success(self, mock_get_pw, mock_vpw, mock_at, mock_rt, async_client):
        """正确用户名密码 → 返回 token + 用户信息"""
        mock_get_pw.return_value = MOCK_USER_WITH_PW
        with patch("app.api.auth.UserRepository.update_last_login") as mock_ll:
            with patch("app.api.auth.UserRepository.get") as mock_get:
                mock_get.return_value = MOCK_USER_INFO
                resp = await async_client.post(
                    "/api/v1/auth/login",
                    json={"username": "admin", "password": "admin123"},
                )

        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "fake_access"
        assert data["refresh_token"] == "fake_refresh"
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 1800
        assert data["user"]["username"] == "admin"

    @patch("app.services.auth_service.verify_password", return_value=False)
    @patch("app.api.auth.UserRepository.get_with_password")
    async def test_login_invalid_credentials(self, mock_get_pw, mock_vpw, async_client):
        """错误密码 → 401"""
        mock_get_pw.return_value = MOCK_USER_WITH_PW
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "admin", "password": "wrong_password"},
        )
        assert resp.status_code == 401
        detail = resp.json()["detail"]
        assert detail["code"] == "401-0000"
        assert "用户名或密码错误" in detail["message"]

    # ── Get Me ─────────────────────────────────────────────────────────

    @patch("app.api.auth.RoleRepository.get_user_permissions", return_value=MOCK_PERMISSIONS)
    @patch("app.api.auth.RoleRepository.get_user_roles", return_value=MOCK_ROLES)
    @patch("app.api.auth.UserRepository.get")
    async def test_get_me(self, mock_get, mock_roles, mock_perms, async_client):
        """有效 token → 返回当前用户信息 (带 roles 和 permissions)"""
        user_info = {**MOCK_USER_INFO}
        mock_get.return_value = user_info
        resp = await async_client.get("/api/v1/auth/me")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["username"] == "admin"
        assert body["data"]["tenant_id"] == "default"
        assert "roles" in body["data"]
        assert "permissions" in body["data"]

    async def test_get_me_unauthorized(self, async_client):
        """无有效 token → 401"""
        from app.main import app
        from app.core.dependencies import get_current_user

        # 临时移除 get_current_user 的 mock 覆盖，恢复真实鉴权逻辑
        original = app.dependency_overrides.pop(get_current_user, None)
        try:
            resp = await async_client.get("/api/v1/auth/me")
            # HTTPBearer(auto_error=True) 无凭证时返回 403
            assert resp.status_code in (401, 403)
        finally:
            # 恢复 override
            app.dependency_overrides[get_current_user] = original

    # ── Refresh Token ──────────────────────────────────────────────────

    @patch("app.services.auth_service.create_access_token", return_value="new_access")
    @patch("app.services.auth_service.verify_token")
    @patch("app.api.auth.UserRepository.get")
    async def test_refresh_token(self, mock_get, mock_vt, mock_at, async_client):
        """有效 refresh_token → 返回新 access_token"""
        mock_vt.return_value = {
            "sub": "1",
            "tenant_id": "default",
            "type": "refresh",
        }
        mock_get.return_value = MOCK_USER_INFO

        resp = await async_client.post(
            "/api/v1/auth/refresh",
            json={"refresh_token": "valid_refresh_token"},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["access_token"] == "new_access"
        assert data["token_type"] == "bearer"
        assert data["expires_in"] == 1800

    # ── Change Password ────────────────────────────────────────────────

    @patch("app.services.auth_service.hash_password", return_value="new_hash")
    @patch("app.services.auth_service.verify_password", return_value=True)
    @patch("app.api.auth.UserRepository.get_with_password_by_id")
    async def test_change_password(self, mock_get_pw, mock_vpw, mock_hp, async_client):
        """正确旧密码 → 修改成功"""
        mock_get_pw.return_value = MOCK_USER_WITH_PW
        with patch("app.api.auth.UserRepository.update") as mock_update:
            mock_update.return_value = 1
            resp = await async_client.post(
                "/api/v1/auth/change-password",
                json={"old_password": "old123", "new_password": "new123"},
            )

        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "密码修改成功"

    @patch("app.services.auth_service.verify_password", return_value=False)
    @patch("app.api.auth.UserRepository.get_with_password_by_id")
    async def test_change_password_wrong_old(self, mock_get_pw, mock_vpw, async_client):
        """错误旧密码 → 400"""
        mock_get_pw.return_value = MOCK_USER_WITH_PW
        resp = await async_client.post(
            "/api/v1/auth/change-password",
            json={"old_password": "wrong", "new_password": "new123"},
        )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "400-0000"
        assert "原密码错误" in detail["message"]
