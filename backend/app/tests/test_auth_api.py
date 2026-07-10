"""
Test suite for M00-Auth Module (4 test cases).

变更说明 (2026-07-10):
- 移除: test_login_success, test_login_invalid_credentials, test_refresh_token
  （POST /login 和 POST /refresh 路由已移除，认证迁移至 cloud.ziwi.cn）
- 保留: test_get_me, test_get_me_unauthorized, test_change_password, test_change_password_wrong_old

Testing strategy:
  - Mock Repo methods (no real database)
  - Mock security functions (password verify/hash)
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
    """4 test cases covering /me, /logout, /change-password."""

    # ── Get Me ─────────────────────────────────────────────────────────

    @patch("app.api.auth.RoleRepository.get_user_permissions", return_value=MOCK_PERMISSIONS)
    @patch("app.api.auth.RoleRepository.get_user_roles", return_value=MOCK_ROLES)
    @patch("app.api.auth.UserRepository.get")
    async def test_get_me(self, mock_get, mock_roles, mock_perms, async_client):
        """有效 token → 返回当前用户信息 (带 roles, permissions, cloud_uuid)"""
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
            # HTTPBearer(auto_error=False) 无凭证时返回 401
            assert resp.status_code in (401, 403)
        finally:
            # 恢复 override
            app.dependency_overrides[get_current_user] = original

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
