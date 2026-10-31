"""D 区品质边界 — 单元测试（D-B2 / D-B3 / D-E7）。

三条修复的回归闸：

- **D-B2 检验明细归属**：``inspection_result.created_by`` 进固定列 INSERT 后，
  未传该键的旧调用方（实验室模块等）不能因此 500；显式传入时必须落库。
  同 bug 的另一半：``role_ids`` 建户/改户时被静默丢弃 → ``sync_user_roles``
  全量同步（先删后插、去重、幂等）。
- **D-B3 改判回滚**：``BatchRepository.unlock`` —— REJ 锁批后改判合格/让步，
  批次必须能解开，且锁/解全程留痕（lock_reason 追加而非清空）。
- **D-E7 PPAP 固定列缺参**：``create_item`` 只传 4 个键时缺省补 None，
  不再 InvalidRequestError 500。
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.ppap import PpapSubmissionItem
from app.models.quality import InspectionOrder, InspectionResult
from app.models.role import Role
from app.models.user import User, UserRole
from app.models.wms import Batch
from app.repositories.ppap_repo import PpapSubmissionItemRepository
from app.repositories.quality_repo import InspectionResultRepository
from app.repositories.user_repo import UserRepository
from app.repositories.wms_repo import BatchRepository

pytestmark = pytest.mark.asyncio


async def _session(tables):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=tables, checkfirst=True))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    return engine, factory()


# ── D-B2：created_by 归属 + 旧调用方兼容 ────────────────────────────

async def test_create_result_with_created_by():
    engine, s = await _session([InspectionOrder.__table__, InspectionResult.__table__])
    async with engine.begin() as conn:
        await conn.execute(InspectionOrder.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "order_no": "QC-1", "order_type": "inspection"}))
    repo = InspectionResultRepository(s)
    repo.set_tenant_id("t")
    rid = await repo.create_result({
        "tenant_id": "t", "order_id": 1, "item_id": None, "item_name": "长度",
        "spec_value": None, "measured_value": None, "deviation": None,
        "unit": None, "remark": None,
        "result": "PASS", "created_by": 42})
    row = await repo.query_one("SELECT * FROM inspection_result WHERE id = :id", {"id": rid})
    assert row["created_by"] == 42
    await engine.dispose()


async def test_create_result_without_created_by_compatible():
    """旧调用方（实验室等）不传 created_by：补 None 而不是 500。"""
    engine, s = await _session([InspectionOrder.__table__, InspectionResult.__table__])
    async with engine.begin() as conn:
        await conn.execute(InspectionOrder.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "order_no": "QC-1", "order_type": "inspection"}))
    repo = InspectionResultRepository(s)
    repo.set_tenant_id("t")
    rid = await repo.create_result({
        "tenant_id": "t", "order_id": 1, "item_id": None, "item_name": "宽度",
        "spec_value": None, "measured_value": None, "deviation": None,
        "unit": None, "remark": None,
        "result": "FAIL"})
    row = await repo.query_one("SELECT * FROM inspection_result WHERE id = :id", {"id": rid})
    assert row["created_by"] is None
    await engine.dispose()


# ── D-B2：role_ids 静默丢弃 → sync_user_roles ───────────────────────

async def _user_bundle():
    engine, s = await _session([User.__table__, Role.__table__, UserRole.__table__])
    async with engine.begin() as conn:
        await conn.execute(User.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "username": "u1", "password_hash": "x"}))
        await conn.execute(Role.__table__.insert().values([
            {"id": 1, "tenant_id": "t", "code": "r1", "name": "角色1"},
            {"id": 2, "tenant_id": "t", "code": "r2", "name": "角色2"},
            {"id": 3, "tenant_id": "t", "code": "r3", "name": "角色3"}]))
    repo = UserRepository(s)
    repo.set_tenant_id("t")
    return engine, repo


async def test_sync_user_roles_assign():
    engine, repo = await _user_bundle()
    result = await repo.sync_user_roles(1, [1, 2])
    assert result["synced"] == 2
    rows = await repo.query(
        "SELECT role_id FROM user_roles WHERE user_id = 1 ORDER BY role_id", {})
    assert [r["role_id"] for r in rows] == [1, 2]
    await engine.dispose()


async def test_sync_user_roles_full_replace():
    """全量语义：目标集合之外的旧关联被删除。"""
    engine, repo = await _user_bundle()
    await repo.sync_user_roles(1, [1, 2])
    await repo.sync_user_roles(1, [2, 3])
    rows = await repo.query(
        "SELECT role_id FROM user_roles WHERE user_id = 1 ORDER BY role_id", {})
    assert [r["role_id"] for r in rows] == [2, 3]
    await engine.dispose()


async def test_sync_user_roles_dedup_and_empty():
    engine, repo = await _user_bundle()
    result = await repo.sync_user_roles(1, [2, 2, None])
    assert result["role_ids"] == [2]
    # 传 [] = 清空全部角色
    result = await repo.sync_user_roles(1, [])
    assert result["synced"] == 0
    rows = await repo.query("SELECT role_id FROM user_roles WHERE user_id = 1", {})
    assert rows == []
    await engine.dispose()


# ── D-B3：批次解锁（改判回滚的一半） ────────────────────────────────

async def test_batch_unlock_after_lock():
    engine, s = await _session([Batch.__table__])
    async with engine.begin() as conn:
        await conn.execute(Batch.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "batch_no": "B-1", "material_id": 1,
             "status": "active", "is_locked": False}))
    repo = BatchRepository(s)
    repo.set_tenant_id("t")
    await repo.lock(1, "IQC 判定不合格")
    row = await repo.query_one("SELECT * FROM batches WHERE id = 1", {})
    assert row["is_locked"] in (True, 1) and row["status"] == "locked"

    await repo.unlock(1)
    row = await repo.query_one("SELECT * FROM batches WHERE id = 1", {})
    assert row["is_locked"] in (False, 0)
    assert row["status"] == "active"
    # 留痕：锁过原因不清空，追加解锁标记
    assert "IQC 判定不合格" in (row["lock_reason"] or "")
    assert "已解锁" in row["lock_reason"]
    await engine.dispose()


# ── D-E7：PPAP create_item 缺省补 None ──────────────────────────────

async def test_ppap_create_item_minimal_keys():
    engine, s = await _session([PpapSubmissionItem.__table__])
    repo = PpapSubmissionItemRepository(s)
    repo.set_tenant_id("t")
    iid = await repo.create_item({
        "tenant_id": "t", "submission_id": 1, "element_id": 1,
        "status": "not_started"})
    row = await repo.query_one(
        "SELECT * FROM ppap_submission_items WHERE id = :id", {"id": iid})
    assert row["status"] == "not_started"
    assert row["file_path"] is None and row["assignee_id"] is None
    await engine.dispose()
