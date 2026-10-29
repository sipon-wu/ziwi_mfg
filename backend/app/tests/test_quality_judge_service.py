"""QualityService.judge_order 修复验证（真实 sqlite 内存库）。

背景：`QualityService.judge_order` 调用 `InspectionOrderRepository.judge_order`，
而仓储层此前**没有该方法**（API 层走 update_inspection_order，故长期未暴露）。
本测试验证补齐后 Service 路径可正常执行。
"""
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.database import Base
from app.models.quality import InspectionOrder
from app.services.quality_service import QualityService


@pytest.fixture
async def session():
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda sc: Base.metadata.create_all(sc, tables=[InspectionOrder.__table__])
        )
    factory = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with factory() as s:
        yield s
    await engine.dispose()


@pytest.mark.asyncio
async def test_judge_order_via_service(session):
    svc = QualityService(session)
    svc.set_tenant_id("t1")

    order_id = await svc.order.create_inspection_order(
        {
            "tenant_id": "t1",
            "order_no": "QC-001",
            "order_type": "first",
            "work_order_id": None,
            "process_id": None,
            "material_id": 9,
            "qc_point_id": None,
            "inspector_id": None,
            "remark": None,
        }
    )
    await session.commit()

    result = await svc.judge_order(order_id, "REJ", inspector_id=7)
    await session.commit()
    assert result["affected"] == 1

    order = await svc.order.get_inspection_order(order_id)
    assert order["result"] == "REJ"
    assert order["inspector_id"] == 7
    assert order["judge_at"] is not None
