"""账号 ↔ 工作中心绑定（`user_work_centers`）的解析与同步测试。

## 这一层的两条判据都不能只看"有没有报错"

1. **`sync` 的三种取值必须分开**：`None`（不动）/ `[]`（解绑全部）/ `[ids]`。
   合并成"空就是清空"，会让"改个手机号"顺手抹掉工位绑定 —— 而绑定没了
   等于**权限面扩大**（从只看两个工位变成看全厂），没有任何提示。
2. **`resolve` 的 `None` 与 `[]` 语义相反**：`None` = 不限（没有绑定行），
   `[]` = 恒假（什么都看不到）。拿反了要么全员越权，要么全员瞎。

## 不测什么

`report_step` 的 403 分支在 `test_step_report.py` 里用 FakeRepo 测（那里没有 SQL）；
端到端由 `e2e/operation_groups_e2e.py` 打真接口验。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.core.dependencies import resolve_user_work_center_ids
from app.models.user import User, UserWorkCenter
from app.repositories.user_repo import UserRepository

TABLES = [User.__table__, UserWorkCenter.__table__]

SEED = [
    "INSERT INTO users (id, tenant_id, username, password_hash) VALUES "
    "(1, 't', 'u1', 'x'), (2, 't', 'u2', 'x'), (3, 'other', 'u3', 'x')",
]


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
        for sql in SEED:
            await conn.execute(text(sql))
    s = async_sessionmaker(engine, expire_on_commit=False)()
    yield s
    await s.close()
    await engine.dispose()


@pytest.fixture
def repo(session):
    r = UserRepository(session)
    r.set_tenant_id("t")
    return r


class TestResolve:

    async def test_no_binding_returns_none(self, session):
        """没有绑定行 = 不限（升级后所有存量账号的默认状态）。"""
        assert await resolve_user_work_center_ids(
            {"id": 1, "tenant_id": "t"}, session) is None

    async def test_bound_returns_restriction_list(self, session, repo):
        await repo.sync_user_work_centers(1, [30, 10, 20])
        got = await resolve_user_work_center_ids({"id": 1, "tenant_id": "t"}, session)
        assert got == [10, 20, 30], "去重且排序，探针才能直接比数组"

    async def test_duplicate_binding_rejected_by_db(self, session, repo):
        """同一账号绑同一工位两次由**库级唯一键**挡住，不靠应用层查重。

        应用层查重永远有并发窗口：两个人同时保存同一份绑定，两个请求都
        查不到已有行、都插入成功 —— 于是 `resolve` 返回 `[10, 10]`，
        `IN (...)` 不会报错，只是列表看起来正常而绑定数多算一倍。
        """
        with pytest.raises(Exception) as ei:
            await repo.execute(
                "INSERT INTO user_work_centers (tenant_id, user_id, wc_id) VALUES "
                "('t', 1, 10), ('t', 1, 10)")
        assert "UNIQUE" in str(ei.value).upper()

    async def test_other_users_binding_does_not_leak(self, session, repo):
        await repo.sync_user_work_centers(2, [99])
        assert await resolve_user_work_center_ids({"id": 1, "tenant_id": "t"}, session) is None

    async def test_other_tenant_does_not_leak(self, session, repo):
        other = UserRepository(session)
        other.set_tenant_id("other")
        await other.sync_user_work_centers(1, [77])
        assert await resolve_user_work_center_ids({"id": 1, "tenant_id": "t"}, session) is None

    async def test_api_key_has_no_user_scope(self, session):
        """API Key 认证走 `key_id`，不走用户维度的工位范围。"""
        assert await resolve_user_work_center_ids(
            {"key_id": 5, "tenant_id": "t"}, session) is None


class TestSync:

    async def test_none_leaves_binding_untouched(self, repo):
        """不传 = 不动。这是 `UpdateUserRequest.work_center_ids` 的默认路径。"""
        await repo.sync_user_work_centers(1, [10])
        out = await repo.sync_user_work_centers(1, None)
        assert out["synced"] is None
        assert await repo.work_center_ids_of(1) == [10]

    async def test_empty_list_unbinds_all(self, repo):
        await repo.sync_user_work_centers(1, [10, 20])
        await repo.sync_user_work_centers(1, [])
        assert await repo.work_center_ids_of(1) == []

    async def test_replaces_wholesale(self, repo):
        await repo.sync_user_work_centers(1, [10, 20])
        await repo.sync_user_work_centers(1, [20, 30])
        assert await repo.work_center_ids_of(1) == [20, 30]

    async def test_sync_is_scoped_to_one_user(self, repo):
        await repo.sync_user_work_centers(1, [10])
        await repo.sync_user_work_centers(2, [20])
        await repo.sync_user_work_centers(1, [])
        assert await repo.work_center_ids_of(1) == []
        assert await repo.work_center_ids_of(2) == [20], "清一家的绑定不能波及另一家"
