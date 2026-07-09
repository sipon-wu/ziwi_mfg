"""
Test suite for M00-User Management Module (5 test cases).

Testing strategy:
  - Mock UserRepository methods (no real database)
  - Mock security hash_password for user creation
  - Dependencies (get_db / get_current_user) overridden via conftest.py
  - Use httpx.AsyncClient + ASGITransport to send requests
"""

import pytest
from unittest.mock import patch

# ---------------------------------------------------------------------------
# Test data helpers
# ---------------------------------------------------------------------------

USER_ITEM = {
    "id": 1,
    "tenant_id": "default",
    "username": "admin",
    "real_name": "管理员",
    "email": "admin@ziwi.cn",
    "phone": "13800138000",
    "avatar_url": None,
    "status": "active",
    "roles": ["admin"],
    "last_login_at": None,
    "created_at": "2025-01-01T00:00:00",
}


def _page_data(items, page=1, page_size=20):
    return {
        "items": items,
        "total": len(items),
        "page": page,
        "page_size": page_size,
    }


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestUserAPI:
    """5 test cases: list / create / get / get_not_found / update"""

    @patch("app.api.users.UserRepository.list")
    async def test_list_users(self, mock_list, async_client):
        """用户列表返回分页数据"""
        mock_list.return_value = _page_data([USER_ITEM])
        resp = await async_client.get("/api/v1/users")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert len(body["data"]["items"]) == 1
        assert body["data"]["total"] == 1
        assert body["data"]["items"][0]["username"] == "admin"

    @patch("app.services.user_service.hash_password", return_value="hashed_pw")
    @patch("app.api.users.UserRepository.create")
    async def test_create_user(self, mock_create, mock_hp, async_client):
        """创建用户返回成功消息"""
        mock_create.return_value = 1
        payload = {
            "username": "newuser",
            "password": "pass123",
            "real_name": "新用户",
            "email": "new@ziwi.cn",
        }
        resp = await async_client.post("/api/v1/users", json=payload)
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "用户创建成功"
        # 验证 tenant_id 由 current_user 注入
        saved = mock_create.call_args[0][0]
        assert saved["tenant_id"] == "default"
        assert saved["username"] == "newuser"

    @patch("app.api.users.UserRepository.get")
    async def test_get_user(self, mock_get, async_client):
        """查询用户返回用户信息"""
        mock_get.return_value = USER_ITEM
        resp = await async_client.get("/api/v1/users/1")
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["data"]["id"] == 1
        assert body["data"]["username"] == "admin"
        assert body["data"]["real_name"] == "管理员"

    @patch("app.api.users.UserRepository.get")
    async def test_get_user_not_found(self, mock_get, async_client):
        """不存在的用户 ID → 404"""
        mock_get.return_value = None
        resp = await async_client.get("/api/v1/users/999")
        assert resp.status_code == 404
        detail = resp.json()["detail"]
        assert detail["code"] == "404-0000"
        assert "用户不存在" in detail["message"]

    @patch("app.api.users.UserRepository.update")
    async def test_update_user(self, mock_update, async_client):
        """修改用户返回成功消息"""
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/users/1",
            json={"real_name": "新名字", "email": "newemail@ziwi.cn"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "更新成功"
        # 验证参数正确传递
        saved_data = mock_update.call_args[0][1]
        assert saved_data["real_name"] == "新名字"
        assert saved_data["email"] == "newemail@ziwi.cn"
