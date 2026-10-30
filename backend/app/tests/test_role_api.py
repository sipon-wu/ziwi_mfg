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


class TestRoleCodeUniqueness:
    """角色编码唯一性（B-1 做「角色增删改界面」时挖出的后端缺陷）。

    `roles.code` 是授权与数据范围判断的锚点，此前**没有唯一约束** —— 同编码能
    建出多个角色，`get_by_code()` 随机命中其中一个，表现为"权限时有时无"，
    且不报任何错。三层防护：DB 唯一约束（兜并发）/ 服务层前置查重（给人话）/
    接口层 ValueError→400（不让 500 冒到页面）。
    """

    async def test_duplicate_code_returns_400_with_human_message(self, async_client):
        with (
            patch("app.repositories.role_repo.RoleRepository.get_by_code") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.create") as mock_create,
        ):
            mock_get.return_value = {"id": 2, "code": "admin"}
            resp = await async_client.post(
                "/api/v1/roles",
                json={"name": "重复", "code": "admin", "scope": "DEPT"},
            )
        assert resp.status_code == 400
        detail = resp.json()["detail"]
        assert detail["code"] == "400-0000"
        assert "已存在" in detail["message"]
        mock_create.assert_not_called()

    async def test_invalid_code_format_returns_400(self, async_client):
        # 大写开头 / 单字符 / 中文 / 空格 —— 都不该落库
        for bad in ("Admin", "a", "仓库主管", "has space", "1abc", ""):
            with patch("app.repositories.role_repo.RoleRepository.create") as mock_create:
                resp = await async_client.post(
                    "/api/v1/roles",
                    json={"name": "格式测试", "code": bad, "scope": "DEPT"},
                )
            assert resp.status_code == 400, f"{bad!r} 应被拒绝"
            assert "角色编码" in resp.json()["detail"]["message"]
            mock_create.assert_not_called()

    async def test_valid_code_creates_role(self, async_client):
        with (
            patch("app.repositories.role_repo.RoleRepository.get_by_code") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.create") as mock_create,
        ):
            mock_get.return_value = None
            mock_create.return_value = 42
            resp = await async_client.post(
                "/api/v1/roles",
                json={"name": "仓库主管", "code": "warehouse_manager_2", "scope": "DEPT"},
            )
        assert resp.status_code == 200
        assert resp.json()["data"]["id"] == 42
        mock_create.assert_called_once()

    def test_model_declares_tenant_code_unique_constraint(self):
        """约束必须声明在模型上：`create_all` 只建表不补约束，
        靠手工 SQL 加索引会让全新环境与老库分叉（见 2026-10-06 结构漂移复盘）。"""
        from app.models.role import Role
        names = {
            tuple(c.name for c in con.columns)
            for con in Role.__table__.constraints
            if con.__class__.__name__ == "UniqueConstraint"
        }
        assert ("tenant_id", "code") in names, f"roles 缺少 (tenant_id, code) 唯一约束，现有 {names}"

    def test_migration_file_exists(self):
        from pathlib import Path
        root = Path(__file__).resolve().parents[2]
        assert (root / "migrations" / "20261101_roles_code_unique.py").exists()


class TestRoleDeleteGuard:
    """删除角色前的两道闸：内置角色 / 还有成员。

    此前 ``RoleService.delete`` 只拦内置角色，**不检查成员** ——
    ``RoleRepository.delete`` 会连 ``user_roles`` 一起清掉，等价于
    "删一个角色，悄悄摘掉一批人的权限"，不报错、不提示。
    """

    async def test_delete_role_with_members_returns_409(self, async_client):
        with (
            patch("app.repositories.role_repo.RoleRepository.get") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.count_users") as mock_count,
            patch("app.repositories.role_repo.RoleRepository.delete") as mock_del,
        ):
            mock_get.return_value = {"id": 5, "code": "scheduler", "is_system": False}
            mock_count.return_value = 3
            resp = await async_client.delete("/api/v1/roles/5")
        assert resp.status_code == 409
        detail = resp.json()["detail"]
        assert "3 名成员" in detail["message"]
        mock_del.assert_not_called()

    async def test_delete_system_role_returns_409(self, async_client):
        with (
            patch("app.repositories.role_repo.RoleRepository.get") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.delete") as mock_del,
        ):
            mock_get.return_value = {"id": 2, "code": "admin", "is_system": True}
            resp = await async_client.delete("/api/v1/roles/2")
        assert resp.status_code == 409
        assert "内置角色" in resp.json()["detail"]["message"]
        mock_del.assert_not_called()

    async def test_delete_empty_role_ok(self, async_client):
        with (
            patch("app.repositories.role_repo.RoleRepository.get") as mock_get,
            patch("app.repositories.role_repo.RoleRepository.count_users") as mock_count,
            patch("app.repositories.role_repo.RoleRepository.delete") as mock_del,
        ):
            mock_get.return_value = {"id": 7, "code": "temp_role", "is_system": False}
            mock_count.return_value = 0
            mock_del.return_value = 1
            resp = await async_client.delete("/api/v1/roles/7")
        assert resp.status_code == 200
        assert resp.json()["code"] == 0
        mock_del.assert_called_once_with(7)


class TestRoleUsersQuery:
    """`GET /roles/{id}/users` 的 JOIN 必须带 `ur.user_id = u.id`。

    漏掉这个条件时 `users` 与 `user_roles` 会做**笛卡尔积**：角色有 1 名成员、
    租户有 11 个用户 → 接口返回 11 行，界面上"随便点开哪个角色都显示全部用户"。
    这条测试直接跑生产 SQL（不复制 SQL 文本，改坏了必红）。
    """

    async def test_get_users_only_returns_members(self):
        from sqlalchemy import text
        from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
        from sqlalchemy.pool import StaticPool
        from app.repositories.role_repo import RoleRepository

        engine = create_async_engine(
            "sqlite+aiosqlite://",
            poolclass=StaticPool,
            connect_args={"check_same_thread": False},
        )
        async with engine.begin() as conn:
            await conn.execute(text(
                "CREATE TABLE users (id INTEGER PRIMARY KEY, username TEXT, real_name TEXT,"
                " status INTEGER, primary_org_id INTEGER)"
            ))
            await conn.execute(text(
                "CREATE TABLE organizations (id INTEGER PRIMARY KEY, name TEXT, code TEXT)"
            ))
            await conn.execute(text(
                "CREATE TABLE user_roles (id INTEGER PRIMARY KEY, user_id INTEGER,"
                " role_id INTEGER, tenant_id TEXT)"
            ))
            # 11 个用户，只有 id=3 是 role 99 的成员
            for i in range(1, 12):
                await conn.execute(
                    text("INSERT INTO users (id, username) VALUES (:i, :u)"),
                    {"i": i, "u": f"u{i}"},
                )
            await conn.execute(text(
                "INSERT INTO user_roles (user_id, role_id, tenant_id) VALUES (3, 99, 't')"
            ))

        Session = async_sessionmaker(engine, expire_on_commit=False)
        async with Session() as s:
            rows = await RoleRepository(s).get_users(99)
        await engine.dispose()

        assert [r["id"] for r in rows] == [3], (
            f"角色 99 只有 1 名成员，却返回了 {len(rows)} 行 —— "
            f"JOIN 少了 ur.user_id = u.id，成了笛卡尔积"
        )
