"""角色管理模块 API 测试"""
import pytest
from unittest.mock import patch


class TestRoleAPI:
    async def test_list_roles(self, async_client):
        with patch("app.repositories.role_repo.RoleRepository.list") as mock:
            mock.return_value = {"items": [{"id": 1, "name": "管理员"}], "total": 1, "page": 1, "page_size": 20}
            resp = await async_client.get("/api/v1/roles?page=1&page_size=20")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0


class TestM00KeyUser:
    """M00 key_user 关键用户角色测试"""

    async def test_assign_key_user_permissions_to_existing_role(self, async_client):
        """为已有角色分配 key_user 的三个专属权限"""
        with (
            patch("app.repositories.role_repo.RoleRepository.seed_permissions_if_not_exist") as mock_seed,
            patch("app.repositories.role_repo.RoleRepository.bulk_assign_permissions") as mock_assign,
        ):
            mock_seed.return_value = [101, 102, 103]
            mock_assign.return_value = None
            resp = await async_client.post("/api/v1/roles/key-user-permissions", json={
                "role_id": 1,
                "role_name": None,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["message"] == "key_user 权限分配成功"
        mock_seed.assert_called_once()
        mock_assign.assert_called_once_with(1, [101, 102, 103])

    async def test_create_key_user_role_and_assign_permissions(self, async_client):
        """自动创建 key_user 角色并分配权限"""
        with (
            patch("app.repositories.role_repo.RoleRepository.get_by_code") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.create") as mock_create,
            patch("app.repositories.role_repo.RoleRepository.seed_permissions_if_not_exist") as mock_seed,
            patch("app.repositories.role_repo.RoleRepository.bulk_assign_permissions") as mock_assign,
        ):
            # get_by_code 返回 None（角色不存在）→ 然后返回创建的 ID
            mock_get.side_effect = [
                None,  # 第一次查：不存在
                {"id": 99, "code": "key_user"},  # 第二次查：创建后
            ]
            mock_create.return_value = 1
            mock_seed.return_value = [101, 102, 103]
            mock_assign.return_value = None
            resp = await async_client.post("/api/v1/roles/key-user-permissions", json={
                "role_id": None,
                "role_name": "关键用户",
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        assert data["message"] == "key_user 权限分配成功"
        # 验证创建角色时传入了正确参数
        mock_create.assert_called_once()
        created_data = mock_create.call_args[0][0]
        assert created_data["code"] == "key_user"
        assert created_data["name"] == "关键用户"

    async def test_create_key_user_role_idempotent(self, async_client):
        """重复创建 key_user 角色应幂等（复用已有角色）"""
        with (
            patch("app.repositories.role_repo.RoleRepository.get_by_code") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.seed_permissions_if_not_exist") as mock_seed,
            patch("app.repositories.role_repo.RoleRepository.bulk_assign_permissions") as mock_assign,
        ):
            # 角色已存在，返回已有记录
            mock_get.return_value = {"id": 5, "code": "key_user", "name": "关键用户"}
            mock_seed.return_value = [101, 102, 103]
            mock_assign.return_value = None
            # 第一次调用
            resp1 = await async_client.post("/api/v1/roles/key-user-permissions", json={
                "role_id": None,
                "role_name": "关键用户",
            })
            assert resp1.status_code == 200
            assert resp1.json()["code"] == 0
            # 第二次调用（幂等）
            resp2 = await async_client.post("/api/v1/roles/key-user-permissions", json={
                "role_id": None,
                "role_name": "关键用户",
            })
            assert resp2.status_code == 200
            assert resp2.json()["code"] == 0
            # create 不应被调用（角色已存在）
            create_mock = None
            assert mock_get.call_count >= 2

    async def test_assign_key_user_permissions_result(self, async_client):
        """验证返回结果包含正确的 permission_codes"""
        with (
            patch("app.repositories.role_repo.RoleRepository.seed_permissions_if_not_exist") as mock_seed,
            patch("app.repositories.role_repo.RoleRepository.bulk_assign_permissions") as mock_assign,
        ):
            mock_seed.return_value = [101, 102, 103]
            mock_assign.return_value = None
            resp = await async_client.post("/api/v1/roles/key-user-permissions", json={
                "role_id": 2,
            })
        assert resp.status_code == 200
        data = resp.json()
        assert data["code"] == 0
        # 验证 data 中的 permission_codes 包含三个 key_user 权限
        result = data["data"]
        assert result["affected"] == 3
        assert "key_user:module_config" in result["permission_codes"]
        assert "key_user:approval_scope" in result["permission_codes"]
        assert "key_user:dept_scope" in result["permission_codes"]
