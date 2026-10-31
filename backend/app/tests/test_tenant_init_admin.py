"""
A-S1「开通租户 → 初始化管理员 → 首登改密」三环的单元测试。

覆盖两条以前完全不存在的能力：
1. ``TenantService.init_admin`` —— 建管理员账号 + 绑 admin 角色 + 置首登改密标志
2. ``_enforce_password_change`` —— 持临时密码的账号只能读、不能写

第 2 条是本轮最需要注意的语义，单独用纯函数直接测（不绕 HTTP），
因为"拦什么、放行什么"的边界一旦写错，用户会被关在系统外面或者强制形同虚设。
"""

import pytest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.core.dependencies import _enforce_password_change
from app.services.tenant_service import TenantService

TENANT = {"id": 1, "tenant_id": "mfg_acme", "name": "阿克米", "code": "acme"}


class _FakeRequest:
    """最小 Request 替身：_enforce_password_change 只用到 method 与 url.path。"""

    def __init__(self, method: str, path: str):
        self.method = method
        self.url = SimpleNamespace(path=path)


def _svc(tenant_repo=None, user_repo=None, role_repo=None):
    return TenantService(
        tenant_repo or AsyncMock(),
        user_repo=user_repo or AsyncMock(),
        role_repo=role_repo or AsyncMock(),
    )


# ────────────────────────────────────────────────────────────────
# 1. 初始化管理员
# ────────────────────────────────────────────────────────────────


class TestInitAdmin:
    async def test_init_admin_creates_user_binds_role_and_sets_flag(self):
        """三件事必须一次做全：建账号、绑角色、置首登改密标志。

        少任何一件，租户在用户眼里都还是"进不去"：
        不建账号=没人能登录；不绑角色=能登录但什么都做不了；
        不置标志=临时密码被一直用下去。
        """
        tenant_repo = AsyncMock()
        tenant_repo.get_by_tenant_id.return_value = TENANT
        user_repo = AsyncMock()
        user_repo.exists_username_in_tenant.return_value = False
        user_repo.create.return_value = 42
        user_repo.count_by_tenant.return_value = 0
        role_repo = AsyncMock()
        role_repo.get_by_code_in_tenant.return_value = {"id": 7}

        result = await _svc(tenant_repo, user_repo, role_repo).init_admin(
            "mfg_acme", "acme_admin", "Init@2026", "王工")

        assert result["user_id"] == 42
        assert result["role_id"] == 7
        assert result["must_change_password"] is True
        role_repo.add_user.assert_awaited_once_with(7, 42, "mfg_acme")

        # 密码必须落哈希，绝不能明文入库
        create_kwargs = user_repo.create.await_args[0][0]
        assert create_kwargs["password_hash"] != "Init@2026"
        assert create_kwargs["password_hash"].startswith("$2")
        assert create_kwargs["must_change_password"] is True

    async def test_init_admin_rejects_when_tenant_missing(self):
        tenant_repo = AsyncMock()
        tenant_repo.get_by_tenant_id.return_value = None
        with pytest.raises(ValueError, match="租户不存在"):
            await _svc(tenant_repo).init_admin("nope", "admin", "Init@2026")

    async def test_init_admin_rejects_short_password(self):
        """初始密码过短要拒：它会经邮件/微信转交，是链路上唯一"密码离开系统"的环节。"""
        tenant_repo = AsyncMock()
        tenant_repo.get_by_tenant_id.return_value = TENANT
        with pytest.raises(ValueError, match="至少 8 位"):
            await _svc(tenant_repo).init_admin("mfg_acme", "admin", "123")

    async def test_init_admin_refuses_second_time(self):
        """★一个租户只能初始化一次。

        这条是安全契约而非易用性问题：允许重复调用等于给"重置他人密码"
        开了一个不需要任何身份校验的后门 —— 知道租户编码就能接管整个租户。
        """
        tenant_repo = AsyncMock()
        tenant_repo.get_by_tenant_id.return_value = TENANT
        user_repo = AsyncMock()
        user_repo.exists_username_in_tenant.return_value = False
        user_repo.count_by_tenant.return_value = 3     # 租户下已有用户
        with pytest.raises(ValueError, match="已初始化"):
            await _svc(tenant_repo, user_repo).init_admin("mfg_acme", "admin2", "Init@2026")

    async def test_init_admin_rejects_duplicate_username(self):
        tenant_repo = AsyncMock()
        tenant_repo.get_by_tenant_id.return_value = TENANT
        user_repo = AsyncMock()
        user_repo.exists_username_in_tenant.return_value = True
        with pytest.raises(ValueError, match="已存在"):
            await _svc(tenant_repo, user_repo).init_admin("mfg_acme", "admin", "Init@2026")

    async def test_init_admin_creates_admin_role_when_absent(self):
        """roles 表里没有 admin 时，按种子口径建一个（否则账号能登录却无任何权限）。"""
        tenant_repo = AsyncMock()
        tenant_repo.get_by_tenant_id.return_value = TENANT
        user_repo = AsyncMock()
        user_repo.exists_username_in_tenant.return_value = False
        user_repo.create.return_value = 42
        user_repo.count_by_tenant.return_value = 0
        role_repo = AsyncMock()
        # 第一次查无、建完再查有（create 返回的是影响行数，不是新 id，必须回查）
        role_repo.get_by_code_in_tenant.side_effect = [None, {"id": 9}]

        result = await _svc(tenant_repo, user_repo, role_repo).init_admin(
            "mfg_acme", "admin", "Init@2026")
        assert result["role_id"] == 9
        role_repo.create.assert_awaited_once()


# ────────────────────────────────────────────────────────────────
# 2. 首登强制改密
# ────────────────────────────────────────────────────────────────


class TestEnforcePasswordChange:
    def test_write_is_blocked(self):
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as ei:
            _enforce_password_change(
                _FakeRequest("POST", "/api/v1/work-orders"),
                {"must_change_password": True})
        assert ei.value.status_code == 403
        assert ei.value.detail["code"] == "403-PWD-CHANGE-REQUIRED"

    def test_read_is_allowed(self):
        """★读必须放行。

        全拦（含 GET）的话用户一登录就撞墙，连"我是谁、去哪改密码"都看不到，
        那是把人挡在门外而不是引导他改密。拦写则能看不能动，改密是唯一
        被放行的写操作，链路自然收敛到改密上。
        """
        _enforce_password_change(_FakeRequest("GET", "/api/v1/work-orders"),
                                 {"must_change_password": True})

    def test_change_password_itself_is_allowed(self):
        """放行改密本身，否则死锁：要改密才能写，改密又是写。"""
        _enforce_password_change(_FakeRequest("POST", "/api/v1/auth/change-password"),
                                 {"must_change_password": True})

    def test_logout_is_allowed(self):
        """放行登出，否则用户被关在系统里出不去。"""
        _enforce_password_change(_FakeRequest("POST", "/api/v1/auth/logout"),
                                 {"must_change_password": True})

    def test_normal_user_unaffected(self):
        for method in ("GET", "POST", "PUT", "DELETE"):
            _enforce_password_change(_FakeRequest(method, "/api/v1/work-orders"),
                                     {"must_change_password": False})

    def test_no_request_context_skips_check(self):
        """非 HTTP 上下文（单元测试直接调依赖）不应拦，也不应炸。"""
        _enforce_password_change(None, {"must_change_password": True})


# ────────────────────────────────────────────────────────────────
# 3. 回归：响应体里的 rowcount 必须做过类型收敛
# ────────────────────────────────────────────────────────────────


class TestClearFlagTypeCoercion:
    async def test_magicmock_rowcount_does_not_leak(self):
        """回归：session 为测试替身时 rowcount 不是 int。

        未收敛就往响应体里塞，jsonable_encoder 会递归爆栈（RecursionError）。
        凡是"从驱动拿到的数"进响应体之前都要收成 int/bool。
        """
        from unittest.mock import MagicMock
        from app.repositories.user_repo import UserRepository

        repo = UserRepository(MagicMock())
        cleared = await repo.clear_must_change_password(1)
        assert isinstance(cleared, int)
        assert cleared == 0
