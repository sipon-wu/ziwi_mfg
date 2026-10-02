"""租户系统管理 P0 测试（B1 / B2 / B7 / B8 / B9 / B12 / B13）。

覆盖：
  - B1  License 本地字段预留（只读，不调用 cloud）
  - B2  模块启停写回 package_modules（+ 跨租户写被拒）
  - B7/B8/B9 用户组织归属（主组织 + 兼任）
  - B12 角色数据作用域 PUT /roles/{id}/scope
  - B13 GET /roles/{id} 返回 permissions(codes) + scope；POST /roles 支持 codes

测试策略与既有用例一致：mock Repository 方法（不连真实 DB），
依赖 get_db / get_current_user 由 conftest.py 自动 override。
"""

import pytest
from unittest.mock import AsyncMock, patch

# conftest.py 的 MOCK_USER 固定 tenant_id = "default"，跨租户写/读断言均以它为准
TENANT_ID = "default"


# ---------------------------------------------------------------------------
# B2: 模块启停写回 package_modules
# ---------------------------------------------------------------------------

class TestTenantModules:
    """B2 模块启停写回（PUT /api/v1/tenants/tenant/modules）"""

    @patch("app.api.tenants.TenantRepository.update_package_modules")
    async def test_set_modules_writes_package_modules(self, mock_update, async_client):
        """写入 package_modules 并按当前租户隔离（跨租户不得写）"""
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/tenants/tenant/modules",
            json={"module_codes": ["M01_WORK_ORDER", "M01_WORK_REPORT", "M02_EQUIPMENT"]},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["code"] == 0
        assert body["message"] == "模块配置已保存"

        tenant_id, package_modules = mock_update.call_args[0][0], mock_update.call_args[0][1]
        assert tenant_id == TENANT_ID, "必须写当前登录租户，禁止跨租户写入"
        assert package_modules == {"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}

    @patch("app.api.tenants.TenantRepository.update_package_modules")
    async def test_set_modules_reject_illegal_code(self, mock_update, async_client):
        """非法编码（非 <模块>_<子功能> 扁平键）→ 400，且不得写库"""
        mock_update.return_value = 1
        resp = await async_client.put(
            "/api/v1/tenants/tenant/modules",
            json={"module_codes": ["M01"]},
        )
        assert resp.status_code == 400
        assert "非法的模块编码" in resp.json()["detail"]["message"]
        mock_update.assert_not_called()

    @patch("app.api.tenants.TenantRepository.update_package_modules")
    async def test_set_modules_tenant_not_found(self, mock_update, async_client):
        """租户不存在（affected=0）→ 400"""
        mock_update.return_value = 0
        resp = await async_client.put(
            "/api/v1/tenants/tenant/modules",
            json={"module_codes": ["M01_WORK_ORDER"]},
        )
        assert resp.status_code == 400

    def test_package_modules_flatten_reflects_switch(self):
        """写回的 package_modules 能被 get_feature_flags 扁平化为 True（开关真的生效）"""
        from app.repositories.tenant_repo import TenantRepository
        flags = TenantRepository.flatten_feature_flags(
            {"M01": ["WORK_ORDER", "WORK_REPORT"], "M02": ["EQUIPMENT"]}
        )
        assert flags == {
            "M01_WORK_ORDER": True,
            "M01_WORK_REPORT": True,
            "M02_EQUIPMENT": True,
        }

    def test_package_modules_accepts_json_string(self):
        """SQLite 裸 SQL 读回 JSON 文本时不退化为空配置（否则改了开关不生效）"""
        from app.repositories.tenant_repo import TenantRepository
        assert TenantRepository._as_json_dict('{"M01": ["WORK_ORDER"]}') == {"M01": ["WORK_ORDER"]}
        assert TenantRepository._as_json_dict(None) == {}
        assert TenantRepository._as_json_dict("not-json") == {}


# ---------------------------------------------------------------------------
# B1: License 本地字段预留
# ---------------------------------------------------------------------------

class TestTenantLicense:
    """B1 只建本地字段 + 只读预留，不调用 cloud"""

    @patch("app.api.tenants.TenantRepository.get_license_by_tenant_id")
    async def test_get_license_returns_local_fields(self, mock_license, async_client):
        """返回本地预留字段（status/expires_at）"""
        mock_license.return_value = {
            "tenant_id": TENANT_ID,
            "license_status": None,
            "license_expires_at": None,
        }
        resp = await async_client.get(f"/api/v1/tenants/{TENANT_ID}/license")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["tenant_id"] == TENANT_ID
        assert data["license_status"] is None, "未配置时应为 null，禁止伪造数据"

    @patch("app.api.tenants.TenantRepository.get_license_by_tenant_id")
    async def test_license_is_local_only(self, mock_license, async_client):
        """读取路径只碰本地字段：不引入任何 cloud 端点的 import / 出站调用"""
        import inspect

        import app.api.tenants as tenants_api
        mock_license.return_value = {
            "tenant_id": TENANT_ID, "license_status": None, "license_expires_at": None,
        }
        resp = await async_client.get(f"/api/v1/tenants/{TENANT_ID}/license")
        assert resp.status_code == 200
        assert mock_license.await_count == 1
        src = inspect.getsource(tenants_api)
        assert "httpx" not in src, "B1 禁止在租户 License 读取路径发起 cloud 调用"


# ---------------------------------------------------------------------------
# B12/B13: 角色数据作用域
# ---------------------------------------------------------------------------

class TestRoleScope:
    """B12 PUT /roles/{id}/scope"""

    @patch("app.repositories.role_repo.RoleRepository.set_scope")
    async def test_set_scope_success(self, mock_set, async_client):
        mock_set.return_value = 1
        resp = await async_client.put("/api/v1/roles/7/scope", json={"scope": "DEPT_CHILD"})
        assert resp.status_code == 200
        assert resp.json()["data"]["scope"] == "DEPT_CHILD"
        assert mock_set.call_args[0] == (7, "DEPT_CHILD")

    @patch("app.repositories.role_repo.RoleRepository.set_scope")
    async def test_set_scope_reject_invalid(self, mock_set, async_client):
        mock_set.return_value = 1
        resp = await async_client.put("/api/v1/roles/7/scope", json={"scope": "SUPER"})
        assert resp.status_code == 400
        mock_set.assert_not_called()


class TestRolePermissionsAndScope:
    """B13 GET /roles/{id} 返回 permissions(codes)+scope；POST /roles 支持 codes"""

    @patch("app.repositories.role_repo.RoleRepository.get")
    @patch("app.repositories.role_repo.RoleRepository.get_permission_codes")
    async def test_get_role_returns_codes_and_scope(self, mock_codes, mock_get, async_client):
        mock_get.return_value = {
            "id": 7, "tenant_id": TENANT_ID, "name": "关键用户", "code": "key_user",
            "description": None, "is_system": True, "scope": "DEPT_CHILD",
        }
        mock_codes.return_value = ["key_user:module_config", "key_user:dept_scope"]
        resp = await async_client.get("/api/v1/roles/7")
        assert resp.status_code == 200
        data = resp.json()["data"]
        assert data["permissions"] == ["key_user:module_config", "key_user:dept_scope"]
        assert data["scope"] == "DEPT_CHILD"

    @patch("app.repositories.role_repo.RoleRepository.create")
    @patch("app.repositories.role_repo.RoleRepository.assign_permissions")
    @patch("app.repositories.role_repo.RoleRepository.find_permission_ids_by_codes")
    async def test_create_role_with_permissions_codes(self, mock_find, mock_assign, mock_create, async_client):
        mock_create.return_value = 88
        mock_find.return_value = [11, 12]
        resp = await async_client.post("/api/v1/roles", json={
            "name": "质检员", "code": "qc", "scope": "DEPT",
            "permissions": ["qc:create", "qc:read"],
        })
        assert resp.status_code == 200
        created = mock_create.call_args[0][0]
        assert created["scope"] == "DEPT"
        assert "permissions" not in created, "permissions 编码应在 create 后转成 permission_ids"
        mock_find.assert_called_once_with(["qc:create", "qc:read"])
        mock_assign.assert_called_once_with(88, [11, 12])


# ---------------------------------------------------------------------------
# B7/B8/B9: 用户组织归属
# ---------------------------------------------------------------------------

class TestUserOrg:
    """用户主组织 + 兼任组织"""

    @patch("app.api.users.UserRepository.create")
    async def test_create_user_with_org(self, mock_create, async_client):
        """POST /users 带 org_id 与 org_ids 时传入 repo（同时带 role_ids）"""
        mock_create.return_value = 1
        resp = await async_client.post("/api/v1/users", json={
            "username": "op1", "password": "pass123", "real_name": "操作工",
            "org_id": 10, "org_ids": [10, 11], "role_ids": [3],
        })
        assert resp.status_code == 200
        saved = mock_create.call_args[0][0]
        assert saved["org_id"] == 10
        assert saved["org_ids"] == [10, 11]

    @patch("app.api.users.UserRepository.create")
    async def test_create_user_email_lowered(self, mock_create, async_client):
        """B15: email 入库前小写归一（由 UserRepository.create 负责）"""
        mock_create.return_value = 1
        resp = await async_client.post("/api/v1/users", json={
            "username": "op2", "password": "pass123", "email": "Op2@Ziwi.CN",
        })
        assert resp.status_code == 200
        from app.repositories.user_repo import UserRepository
        assert UserRepository.normalize_email("Op2@Ziwi.CN") == "op2@ziwi.cn"

    @patch("app.services.user_service.UserService.update")
    async def test_update_user_org(self, mock_update, async_client):
        """PUT /users/{id} 带 org_id → service 走组织同步分支"""
        mock_update.return_value = {"affected": 1,
                                    "org": {"primary_org_id": 12, "org_ids": [12], "removed": 1}}
        resp = await async_client.put("/api/v1/users/5", json={"org_id": 12})
        assert resp.status_code == 200
        assert resp.json()["data"]["org"]["primary_org_id"] == 12

    def test_user_org_unique_index_contract(self):
        """user_organizations 声明「一个用户最多一个主组织」的部分唯一索引"""
        from app.models.user import UserOrganization
        idx_names = {ix.name for ix in UserOrganization.__table__.indexes}
        assert "uq_user_primary_org" in idx_names
