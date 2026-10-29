"""通用状态流水 + NCR 状态闭环 集成测试。

与项目其余测试不同，本文件**使用真实 sqlite 内存库**（其余测试用 AsyncMock session），
目的是验证手写 SQL（INSERT 全字段绑定、索引、UPDATE 租户注入）在**真实执行**下无误——
仅靠 mock 无法发现绑定参数缺失这类运行期错误。
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.quality import NcrRecord
from app.models.status_log import EntityStatusLog
from app.repositories.status_log_repo import StatusLogRepository
from app.services.ncr_service import NcrService
from app.services.status_log_service import StatusLogService

TABLES = [NcrRecord.__table__, EntityStatusLog.__table__]


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(lambda sc: Base.metadata.create_all(sc, tables=TABLES))
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_create_ncr_writes_first_status_log(session):
    svc = NcrService(session, tenant_id="t1")
    result = await svc.create_ncr(
        {"ncr_no": "NC-001", "source_type": "iqc", "defect_qty": 3, "severity": "major"},
        actor_id=1,
        actor_name="张三",
    )
    await session.commit()

    ncr = await svc.get(result["id"])
    assert ncr["status"] == "open"
    assert ncr["ncr_no"] == "NC-001"

    trail = await svc.get_trail(result["id"])
    assert len(trail) == 1
    assert trail[0]["to_status"] == "open"
    assert trail[0]["action"] == "create"
    assert trail[0]["entity_type"] == "ncr"
    assert trail[0]["entity_no"] == "NC-001"
    assert trail[0]["actor_name"] == "张三"


@pytest.mark.asyncio
async def test_full_transition_writes_complete_trail(session):
    svc = NcrService(session, tenant_id="t1")
    created = await svc.create_ncr({"ncr_no": "NC-002", "source_type": "ipqc"}, actor_id=1)
    ncr_id = created["id"]

    await svc.advance(ncr_id, "reviewing", actor_id=2, actor_name="李四")
    await svc.advance(
        ncr_id, "disposed", actor_id=3, actor_name="王五",
        disposition="return", disposition_remark="整批退货",
    )
    await svc.advance(ncr_id, "closed", actor_id=3, actor_name="王五")
    await session.commit()

    ncr = await svc.get(ncr_id)
    assert ncr["status"] == "closed"
    assert ncr["disposition"] == "return"
    assert ncr["disposition_remark"] == "整批退货"
    assert ncr["disposition_by"] == 3
    assert ncr["closed_by"] == 3

    trail = await svc.get_trail(ncr_id)
    assert [t["to_status"] for t in trail] == ["open", "reviewing", "disposed", "closed"]
    assert trail[2]["action"] == "dispose"
    assert trail[3]["action"] == "close"


@pytest.mark.asyncio
async def test_illegal_transition_rejected(session):
    svc = NcrService(session, tenant_id="t1")
    created = await svc.create_ncr({"ncr_no": "NC-003", "source_type": "fqc"}, actor_id=1)
    await session.commit()

    # open → closed 不合法（必须先评审/处置）
    with pytest.raises(ValueError, match="非法状态流转"):
        await svc.advance(created["id"], "closed", actor_id=1)

    await session.rollback()
    ncr = await svc.get(created["id"])
    assert ncr["status"] == "open"


@pytest.mark.asyncio
async def test_status_log_validates_source_and_tenant(session):
    svc = StatusLogService(session, tenant_id="t1")

    with pytest.raises(ValueError, match="source 必须为"):
        await svc.record(
            tenant_id="t1", entity_type="ncr", entity_id=1, to_status="open",
            source="unknown",
        )

    with pytest.raises(ValueError, match="tenant_id 必填"):
        await svc.record(tenant_id="", entity_type="ncr", entity_id=1, to_status="open")


@pytest.mark.asyncio
async def test_status_log_tenant_isolation(session):
    svc_a = StatusLogService(session, tenant_id="tenant_a")
    svc_b = StatusLogService(session, tenant_id="tenant_b")

    await svc_a.record(tenant_id="tenant_a", entity_type="ncr", entity_id=1, to_status="open")
    await svc_b.record(tenant_id="tenant_b", entity_type="ncr", entity_id=1, to_status="open")
    await session.commit()

    assert len(await svc_a.list_by_entity("ncr", 1)) == 1
    assert len(await svc_b.list_by_entity("ncr", 1)) == 1


def test_status_log_repository_is_append_only():
    """约定：访问层不提供 UPDATE / DELETE，从接口面杜绝补录与篡改。"""
    assert not hasattr(StatusLogRepository, "update")
    assert not hasattr(StatusLogRepository, "delete")
