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


class TestLoginTenantResolution:
    """登录「租户」字段允许填 tenant_id 或租户编码。

    真因背景：`get_with_password` 是 `users.tenant_id = :x` 精确匹配，而
    `tenants.tenant_id` 是服务端生成的 `t_xxxx`（重新开通就会变），客户手上
    只有租户编码（`AH-THR`）。只认 tenant_id 时，客户填对编码也会得到
    「用户名或密码错误」——文案指向账号，真因在租户，极难判读。
    """

    LOGIN_USER = {
        "id": 7, "username": "ah_admin", "tenant_id": "t_1692982c9cb7",
        "password_hash": "$2b$12$fakehashforunittest", "status": "active",
        "must_change_password": False,
    }

    @patch("app.api.auth.create_local_token", return_value="tok")
    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.UserRepository.get_with_password")
    @patch("app.api.auth.UserRepository.resolve_login_tenant")
    async def test_login_accepts_tenant_code(self, mock_resolve, mock_get_pw,
                                            mock_vpw, mock_tok, async_client):
        """填租户编码 AH-THR → 归一成 t_xxx 再查账号"""
        mock_resolve.return_value = "t_1692982c9cb7"
        mock_get_pw.return_value = dict(self.LOGIN_USER)
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "ah_admin", "password": "pw", "tenant_id": "AH-THR"},
        )
        assert resp.status_code == 200
        assert resp.json()["access_token"] == "tok"
        # ★ 断言传给账号查询的是归一后的 tenant_id，不是用户输入的编码
        mock_get_pw.assert_called_once_with("ah_admin", "t_1692982c9cb7")

    @patch("app.api.auth.create_local_token", return_value="tok")
    @patch("app.api.auth.verify_password", return_value=True)
    @patch("app.api.auth.UserRepository.get_with_password")
    @patch("app.api.auth.UserRepository.resolve_login_tenant")
    async def test_login_keeps_raw_when_unresolved(self, mock_resolve, mock_get_pw,
                                                   mock_vpw, mock_tok, async_client):
        """查不到的租户 → 保留原值，行为与改动前一致（不改变 401 口径）"""
        mock_resolve.return_value = None
        mock_get_pw.return_value = None
        resp = await async_client.post(
            "/api/v1/auth/login",
            json={"username": "nobody", "password": "pw", "tenant_id": "NO-SUCH"},
        )
        assert resp.status_code == 401
        mock_get_pw.assert_called_once_with("nobody", "NO-SUCH")

