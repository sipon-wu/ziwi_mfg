"""F-S5 备件领用 → 库存扣减（台账 C-58）。

改造前这条链**没有入口**：备件主数据（``spare_parts``）与流水表
（``spare_part_inventories``）都在，但没有任何端点能发起领用 ——
``spare_part_inventories`` 因此常年 0 行，备件是"有主数据、无业务"。
维修工换了个轴承，系统里既不知道用掉几个、也不知道归到哪次维修。

补 ``POST /spare-parts/{part_id}/consume`` 与 ``GET .../movements``，
锁三条契约：

1. **不允许领成负数** —— 备件不是生产物料，不存在欠料出库；账面为负只会让
   下一次领用继续成功，缺口越滚越大且无人察觉。
2. **必须留痕** —— 流水带 before/after 快照。备件没有独立台账，只靠
   ``spare_parts.current_stock`` 一个数字；不记快照，事后只能看到"现在是几"。
3. **关联维修单必须校验存在** —— 给了 ``maintenance_task_id`` 却查不到就直接拒，
   否则界面上"关联了维修单"、实际挂的是空 id，备件成本永远归不到那次维修。

**顺带修同一形态的第六次复发**：``create_spare_part`` 的固定列 INSERT 漏了
``max_stock``（模型 ``default=0``），一起在写入口兜住。
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.sync import ChangeLog
from app.models.tpm import (
    Equipment, MaintenanceTask, SparePart, SparePartInventory)
from app.repositories.tpm_repo import TpmRepository
from app.services.tpm_service import TpmService

TABLES = [
    SparePart.__table__, SparePartInventory.__table__,
    MaintenanceTask.__table__, Equipment.__table__, ChangeLog.__table__,
]


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        await conn.execute(Equipment.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "equipment_code": "EQ-01",
             "equipment_name": "注塑机 A", "status": "running"}))
        await conn.execute(MaintenanceTask.__table__.insert().values(
            {"id": 7, "tenant_id": "t", "task_no": "MT-7", "equipment_id": 1,
             "task_type": "repair", "status": "pending"}))
        await conn.execute(SparePart.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "part_code": "BRG-01",
             "part_name": "主轴轴承", "unit": "个",
             "current_stock": 10, "min_stock": 3}))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _svc(s):
    repo = TpmRepository(s)
    repo.set_tenant_id("t")
    return TpmService(repo), repo


# ==================== 1. 领用扣库存 ====================

async def test_consume_decreases_stock():
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            res = await svc.consume_spare_part(1, 4, operator_id=2)
            assert res["before_qty"] == 10
            assert res["after_qty"] == 6
            assert (await repo.get_spare_part(1))["current_stock"] == 6
    finally:
        await engine.dispose()


async def test_consume_rejects_when_insufficient():
    """★库存不足必须拒 —— 领成负数会让缺口越滚越大且无人察觉。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            with pytest.raises(ValueError, match="库存不足"):
                await svc.consume_spare_part(1, 999)
            # 拒绝后库存不能被改动
            assert (await repo.get_spare_part(1))["current_stock"] == 10
    finally:
        await engine.dispose()


async def test_consume_rejects_non_positive_qty():
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, _ = _svc(s)
            for bad in (0, -1):
                with pytest.raises(ValueError, match="必须为正"):
                    await svc.consume_spare_part(1, bad)
    finally:
        await engine.dispose()


# ==================== 2. 留痕 ====================

async def test_consume_writes_movement_with_snapshot():
    """流水必须带 before/after 快照，否则事后对账只看得到"现在是几"。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, _ = _svc(s)
            await svc.consume_spare_part(1, 3, remark="更换主轴")
            rows = await svc.list_spare_part_movements(1)
            assert len(rows) == 1
            assert rows[0]["change_type"] == "out"
            assert rows[0]["qty"] == 3
            assert rows[0]["before_qty"] == 10
            assert rows[0]["after_qty"] == 7
            assert rows[0]["remark"] == "更换主轴"
    finally:
        await engine.dispose()


# ==================== 3. 关联维修单 ====================

async def test_consume_links_maintenance_task():
    """挂了维修单 → 流水必须记下引用，备件成本才归得到那次维修。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, _ = _svc(s)
            res = await svc.consume_spare_part(1, 2, maintenance_task_id=7)
            assert res["maintenance_task_id"] == 7
            rows = await svc.list_spare_part_movements(1)
            assert rows[0]["reference_type"] == "maintenance_task"
            assert rows[0]["reference_id"] == "7"
    finally:
        await engine.dispose()


async def test_consume_rejects_unknown_task_without_changing_stock():
    """给了维修单却查不到 → 必须拒，否则界面显示"已关联"实际挂空。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            with pytest.raises(ValueError, match="维修任务不存在"):
                await svc.consume_spare_part(1, 2, maintenance_task_id=9999)
            assert (await repo.get_spare_part(1))["current_stock"] == 10
            assert await svc.list_spare_part_movements(1) == []
    finally:
        await engine.dispose()


async def test_consume_flags_below_min_stock():
    """领用后跌破安全库存要提示 —— 否则下次维修才发现没货。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, _ = _svc(s)
            res = await svc.consume_spare_part(1, 8)   # 10 → 2，低于 min 3
            assert res["after_qty"] == 2
            assert res["below_min_stock"] is True
    finally:
        await engine.dispose()


# ==================== 4. 建备件不再漏列 ====================

async def test_create_spare_part_fills_defaults():
    """max_stock 等有默认值的列必须能建出来（固定列 INSERT 漏列的第六次复发）。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, repo = _svc(s)
            pid = (await svc.create_spare_part({
                "tenant_id": "t", "part_code": "OIL-01", "part_name": "润滑油"}))["id"]
            row = await repo.get_spare_part(pid)
            assert row["max_stock"] == 0
            assert row["current_stock"] == 0
            assert row["min_stock"] == 0
    finally:
        await engine.dispose()
