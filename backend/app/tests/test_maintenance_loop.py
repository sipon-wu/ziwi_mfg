"""保养计划 → 任务 → 停机 → 排产调整（台账 C-39，场景 X9）。

改造前 ``maintenance_plans`` 是一张**死表**：五个环节一个都没接上 ——

    create_plan 不写 next_execute_at  → 新计划永远不到期
    没有"到期扫描"的任何代码          → 计划永远不会变成任务
    create_task 丢掉 task_no/plan_id  → 任务执行过几次查不出来
    开工/完成只改 status             → 设备台账还是 running、没有停机记录
    计划 next_execute_at 原地不动     → 做完了下次还是"已到期"，天天生成任务

本文件锁住六条契约：

1. ``add_cycle`` 月份/年份必须走日历加法（1/31 + 1 月 = 2/28，不是 3/3）；
2. ``create_plan`` **必须把 ``next_execute_at`` 真的落库** —— 这一条用真库跑，
   因为缺陷出在仓储层硬编码列清单的 INSERT 上，打桩测不出来（同类缺陷已复发三次：
   ``create_equipment`` 漏 status、``create_task`` 漏 task_no、``create_plan`` 漏 next_execute_at）；
3. 到期扫描同日同计划幂等（连点两次不能开出两条任务）；
4. 老计划 ``next_execute_at IS NULL`` 也算到期（否则历史数据永远不到期）；
5. 完工必须先把计划推到下一周期，否则下次扫描还会命中同一张计划；
6. 重复开工不开第二条停机记录、未开工不能完成、未指定工单不动工单。

真实链路验证见 ``e2e/maintenance_downtime_e2e.py``（M1–M10，22 段全通）。
"""
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.sync import ChangeLog
from app.models.tpm import (
    Equipment, EquipmentDowntime, MaintenancePlan, MaintenanceTask)
from app.repositories.tpm_repo import EquipmentDowntimeRepository, TpmRepository
from app.services.maintenance_service import MaintenanceService, _as_dt, add_cycle

TABLES = [
    Equipment.__table__, MaintenancePlan.__table__, MaintenanceTask.__table__,
    EquipmentDowntime.__table__,
    # MultiTenantRepository.execute 会往 change_log 写一行（同步层）。缺这张表时
    # 设备状态更新会抛 "no such table: change_log"，被联动的 try/except 兜住 →
    # 测试拿到一条 {"error": ...} 却仍"通过"，等于什么都没验。
    ChangeLog.__table__,
]


@pytest.fixture
async def session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        await s.execute(Equipment.__table__.insert().values([
            {"id": 1, "tenant_id": "t", "equipment_code": "EQ-01",
             "equipment_name": "注塑机 A", "status": "running"},
            {"id": 2, "tenant_id": "t", "equipment_code": "EQ-02",
             "equipment_name": "注塑机 B", "status": "running"},
        ]))
        await s.commit()
        yield s
    await engine.dispose()


def _svc(s):
    repo = TpmRepository(s)
    repo.set_tenant_id("t")
    return MaintenanceService(repo)


async def _plan(s, **kw):
    """直接落一条计划（绕过 service，用于构造"历史数据"）。"""
    row = {"tenant_id": "t", "equipment_id": 1, "plan_name": "月度保养",
           "plan_type": "monthly", "cycle_value": 1, "cycle_unit": "month",
           "status": "active"}
    row.update(kw)
    await s.execute(MaintenancePlan.__table__.insert().values(**row))
    await s.commit()
    return (await s.execute(
        MaintenancePlan.__table__.select().order_by(
            MaintenancePlan.__table__.c.id.desc()))).first()._mapping["id"]


async def _plan_row(s, plan_id):
    row = (await s.execute(
        MaintenancePlan.__table__.select().where(
            MaintenancePlan.__table__.c.id == plan_id))).first()
    return dict(row._mapping) if row else None


async def _task_row(s, task_id):
    row = (await s.execute(
        MaintenanceTask.__table__.select().where(
            MaintenanceTask.__table__.c.id == task_id))).first()
    return dict(row._mapping) if row else None


async def _equipment_status(s, eq_id):
    row = (await s.execute(
        Equipment.__table__.select().where(
            Equipment.__table__.c.id == eq_id))).first()
    return row._mapping["status"]


# ============================================================
# 周期推进
# ============================================================

def test_add_cycle_month_uses_calendar():
    """★ 1/31 加一个月必须是 2/28 —— ``timedelta(days=30)`` 会落成 3/2。"""
    base = datetime(2027, 1, 31, 9, 0, tzinfo=timezone.utc)
    assert add_cycle(base, 1, "month") == datetime(2027, 2, 28, 9, 0, tzinfo=timezone.utc)


def test_add_cycle_year_rollover():
    base = datetime(2027, 11, 15, 8, 30, tzinfo=timezone.utc)
    assert add_cycle(base, 3, "month") == datetime(2028, 2, 15, 8, 30, tzinfo=timezone.utc)
    assert add_cycle(base, 1, "year") == datetime(2028, 11, 15, 8, 30, tzinfo=timezone.utc)


def test_add_cycle_leap_day():
    base = datetime(2028, 2, 29, 0, 0, tzinfo=timezone.utc)
    assert add_cycle(base, 1, "year") == datetime(2029, 2, 28, 0, 0, tzinfo=timezone.utc)


def test_add_cycle_simple_units():
    base = datetime(2027, 5, 10, tzinfo=timezone.utc)
    assert add_cycle(base, 2, "day") == datetime(2027, 5, 12, tzinfo=timezone.utc)
    assert add_cycle(base, 1, "week") == datetime(2027, 5, 17, tzinfo=timezone.utc)
    assert add_cycle(base, 6, "hour") == datetime(2027, 5, 10, 6, tzinfo=timezone.utc)


def test_add_cycle_none_value_defaults_to_one():
    base = datetime(2027, 5, 10, tzinfo=timezone.utc)
    assert add_cycle(base, None, "month") == datetime(2027, 6, 10, tzinfo=timezone.utc)


# ============================================================
# 建计划：★ 真库回归闸
# ============================================================

async def test_create_plan_persists_next_execute_at(session):
    """★ 这条是 C-39 的核心回归闸。

    ``create_plan`` 曾经用硬编码列清单的 INSERT，``next_execute_at`` 传进来
    也被静默丢掉 → 计划建出来永远不到期。用真库跑才能看见这一列到底写没写进去。
    """
    svc = _svc(session)
    res = await svc.create_plan({
        "tenant_id": "t", "equipment_id": 1, "plan_name": "周检",
        "plan_type": "weekly", "cycle_value": 1, "cycle_unit": "week",
    })

    row = await _plan_row(session, res["id"])
    assert row["next_execute_at"] is not None, "next_execute_at 没落库 → 计划永远不到期"
    assert row["status"] == "active"
    assert _as_dt(row["next_execute_at"]) == _as_dt(res["next_execute_at"])
    # 周期 1 周，算出的大约是 7 天后
    delta = (_as_dt(row["next_execute_at"]) - datetime.now(timezone.utc)).days
    assert 6 <= delta <= 7, delta


async def test_create_plan_honours_explicit_next_execute_at(session):
    """调用方显式给了到期日就不能被自动计算覆盖（补录历史计划要用）。"""
    svc = _svc(session)
    due = datetime(2027, 3, 1, 8, 0, tzinfo=timezone.utc)
    res = await svc.create_plan({
        "tenant_id": "t", "equipment_id": 1, "plan_name": "补录",
        "cycle_value": 1, "cycle_unit": "month", "next_execute_at": due,
    })
    row = await _plan_row(session, res["id"])
    assert _as_dt(row["next_execute_at"]) == due


# ============================================================
# 到期扫描
# ============================================================

async def test_due_scan_generates_task_links_plan(session):
    """扫到的计划要变成任务，并且任务上必须带 ``plan_id`` —— 否则完工时无从推进计划。"""
    due = datetime.now(timezone.utc) - timedelta(days=1)
    plan_id = await _plan(session, next_execute_at=due)

    res = await _svc(session).generate_due_tasks(actor_id=9)

    assert res["created"] == 1, res
    task = await _task_row(session, res["tasks"][0]["task_id"])
    assert task["plan_id"] == plan_id
    assert task["task_no"] == res["tasks"][0]["task_no"]
    assert task["status"] == "pending"
    assert task["task_type"] == "maintenance"


async def test_due_scan_is_idempotent_same_day(session):
    """★ 连点两次"扫描"不能开出两条任务（``MT-<plan>-<YYYYMMDD>`` 幂等）。"""
    due = datetime.now(timezone.utc) - timedelta(days=1)
    await _plan(session, next_execute_at=due)
    svc = _svc(session)

    first = await svc.generate_due_tasks()
    second = await svc.generate_due_tasks()

    assert first["created"] == 1
    assert second["created"] == 0 and second["skipped"] == 1
    rows = (await session.execute(MaintenanceTask.__table__.select())).fetchall()
    assert len(rows) == 1


async def test_legacy_plan_without_next_execute_at_is_due(session):
    """★ 老计划 ``next_execute_at`` 是 NULL，只按 ``<= now`` 过滤会让它们永远不到期。"""
    await _plan(session, next_execute_at=None)
    res = await _svc(session).generate_due_tasks()
    assert res["scanned"] == 1 and res["created"] == 1


async def test_future_plan_is_not_due(session):
    future = datetime.now(timezone.utc) + timedelta(days=10)
    await _plan(session, next_execute_at=future)
    res = await _svc(session).generate_due_tasks()
    assert res["created"] == 0


async def test_inactive_plan_is_not_due(session):
    """停用的计划不该再生成任务。"""
    due = datetime.now(timezone.utc) - timedelta(days=1)
    await _plan(session, next_execute_at=due, status="paused")
    res = await _svc(session).generate_due_tasks()
    assert res["created"] == 0


# ============================================================
# 开工 / 完工
# ============================================================

async def _pending_task(session, work_order_id=None):
    due = datetime.now(timezone.utc) - timedelta(days=1)
    plan_id = await _plan(session, next_execute_at=due)
    res = await _svc(session).generate_due_tasks()
    task_id = res["tasks"][0]["task_id"]
    if work_order_id is not None:
        await session.execute(
            MaintenanceTask.__table__.update()
            .where(MaintenanceTask.__table__.c.id == task_id)
            .values(work_order_id=work_order_id))
        await session.commit()
    return plan_id, task_id


async def test_start_task_sets_equipment_maintenance_and_opens_downtime(session):
    plan_id, task_id = await _pending_task(session)
    res = await _svc(session).start_task(task_id, actor_id=9)

    assert res["status"] == "in_progress"
    assert res["equipment_status"] == "maintenance"
    assert await _equipment_status(session, 1) == "maintenance"

    dt = await EquipmentDowntimeRepository(session).find_open(1)
    assert dt and dt["downtime_type"] == "maintenance"
    assert dt["reason"].startswith("保养任务")
    # 未指定工单 → 明确告知没做排产调整，而不是假装调过
    assert res["work_order_status"] is None and "未指定" in res["note"]


async def test_start_task_twice_reuses_open_downtime(session):
    """★ 车间点两次不能开出两条并行停机 —— 时长会被算两遍。"""
    plan_id, task_id = await _pending_task(session)
    svc = _svc(session)
    first = await svc.start_task(task_id)
    second = await svc.start_task(task_id)

    assert second["already"] is True
    assert first["downtime_id"] == second["downtime_id"]
    rows = (await session.execute(
        EquipmentDowntime.__table__.select().where(
            EquipmentDowntime.__table__.c.ended_at.is_(None)))).fetchall()
    assert len(rows) == 1


async def test_complete_without_start_is_rejected(session):
    """没开工就没停机时长可算，硬完成会静默吞掉"这台设备停了多久"。"""
    plan_id, task_id = await _pending_task(session)
    with pytest.raises(ValueError, match="尚未开工"):
        await _svc(session).complete_task(task_id, {"result": "ok"})


async def test_complete_closes_downtime_and_restores_equipment(session):
    plan_id, task_id = await _pending_task(session)
    svc = _svc(session)
    await svc.start_task(task_id)
    # 把停机起点前移 45 分钟，让时长可断言
    dt = await EquipmentDowntimeRepository(session).find_open(1)
    await EquipmentDowntimeRepository(session).update_record(
        dt["id"], {"started_at": datetime.now(timezone.utc) - timedelta(minutes=45)})

    res = await svc.complete_task(task_id, {"result": "更换润滑油"}, actor_id=9)

    assert res["status"] == "completed"
    assert res["equipment_status"] == "running"
    assert await _equipment_status(session, 1) == "running"
    assert 44 <= res["downtime_minutes"] <= 46, res

    closed = (await session.execute(
        EquipmentDowntime.__table__.select().where(
            EquipmentDowntime.__table__.c.id == dt["id"]))).first()._mapping
    assert closed["ended_at"] is not None
    assert closed["duration_minutes"] == res["downtime_minutes"]


async def test_complete_advances_plan_to_next_cycle(session):
    """★ 计划不推进，下次扫描还会命中同一张 → 天天生成任务。"""
    plan_id, task_id = await _pending_task(session)
    svc = _svc(session)
    await svc.start_task(task_id)
    res = await svc.complete_task(task_id, {"result": "ok"})

    row = await _plan_row(session, plan_id)
    assert row["last_execute_at"] is not None
    assert _as_dt(row["next_execute_at"]) == _as_dt(res["plan_next_execute_at"])
    assert _as_dt(row["next_execute_at"]) > datetime.now(timezone.utc)

    # 推进后再扫，这张计划不该再命中
    again = await svc.generate_due_tasks()
    assert again["created"] == 0


async def test_complete_twice_is_idempotent(session):
    """完工后置幂等，重复完工不能把停机时长再算一遍。"""
    plan_id, task_id = await _pending_task(session)
    svc = _svc(session)
    await svc.start_task(task_id)
    first = await svc.complete_task(task_id, {"result": "ok"})
    second = await svc.complete_task(task_id, {"result": "ok"})

    assert second["already"] is True
    assert first["downtime_minutes"] == second.get("downtime_minutes", first["downtime_minutes"])


async def test_start_completed_task_is_rejected(session):
    plan_id, task_id = await _pending_task(session)
    svc = _svc(session)
    await svc.start_task(task_id)
    await svc.complete_task(task_id, {})
    with pytest.raises(ValueError, match="不能开工"):
        await svc.start_task(task_id)


# ============================================================
# 工单联动（用假 ProductionService，避免拖进整套生产表）
# ============================================================

def _fake_prod(order):
    prod = MagicMock()
    prod.repo = MagicMock()
    prod.repo.get_work_order = AsyncMock(return_value=order)
    prod.repo.update_work_order = AsyncMock(return_value=1)
    prod.pause_work_order = AsyncMock(return_value={"affected": 1})
    prod.resume_work_order = AsyncMock(return_value={"affected": 1})
    return prod


def _patch_prod(prod):
    return (
        patch("app.repositories.production_repo.ProductionRepository",
              return_value=MagicMock()),
        patch("app.services.production_service.ProductionService", return_value=prod),
    )


async def test_start_task_pauses_specified_work_order(session):
    plan_id, task_id = await _pending_task(session, work_order_id=108)
    prod = _fake_prod({"id": 108, "wo_status": "in_progress"})
    p1, p2 = _patch_prod(prod)
    with p1, p2:
        res = await _svc(session).start_task(task_id)
    assert res["work_order_status"] == "paused"
    prod.pause_work_order.assert_awaited_once()


async def test_no_work_order_means_no_production_touch(session):
    """★ 任务没指定工单就只停机、不动工单 —— 硬猜"这台设备上的单"会停错别人的单。"""
    plan_id, task_id = await _pending_task(session)
    prod = _fake_prod(None)
    p1, p2 = _patch_prod(prod)
    with p1, p2:
        await _svc(session).start_task(task_id)
    prod.pause_work_order.assert_not_awaited()
    prod.repo.get_work_order.assert_not_awaited()


async def test_complete_reschedules_work_order_by_downtime(session):
    plan_id, task_id = await _pending_task(session, work_order_id=108)
    end0 = datetime.now(timezone.utc) + timedelta(days=2)
    prod = _fake_prod({"id": 108, "wo_status": "paused", "scheduled_end_at": end0})
    p1, p2 = _patch_prod(prod)
    svc = _svc(session)
    with p1, p2:
        await svc.start_task(task_id)
        dt = await EquipmentDowntimeRepository(session).find_open(1)
        await EquipmentDowntimeRepository(session).update_record(
            dt["id"], {"started_at": datetime.now(timezone.utc) - timedelta(minutes=90)})
        res = await svc.complete_task(task_id, {"result": "ok"})

    minutes = res["downtime_minutes"]
    assert 89 <= minutes <= 91, minutes
    new_end = prod.repo.update_work_order.await_args.args[1]["scheduled_end_at"]
    delta = (_as_dt(new_end) - _as_dt(end0)).total_seconds() / 60.0
    assert abs(delta - minutes) < 1e-6, f"顺延 {delta} != 停机 {minutes}"
