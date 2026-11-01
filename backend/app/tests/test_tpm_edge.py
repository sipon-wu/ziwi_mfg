"""F 区设备维护/能耗采集边界 — 单元测试（F-E1 / F-E2 / F-B1 / F-B2）。

四条修复的回归闸：

- **F-E1 逾期判定**：``scheduled_start_at`` 从 SQLite 出来是**字符串**（
  ``_row_to_dict`` 不做类型还原），直接与 ``datetime`` 相减会 TypeError ——
  必须先过 ``_as_dt`` 归一。分档口径 ≥3 天 urgent、≥7 天 critical；
  completed / canceled 不参与判定（否则"做完的活还挂着红灯"）。
- **F-E2 报废拦截**：设备挂 released/in_progress/paused 工单时 ``update_equipment``
  抛 ValueError，且**不写库**（拦住了却把状态改掉是最坏的结果）。
- **F-B1 调拨留痕**：``location`` 变更写 ``audit_logs`` 的 ``equipment.transfer``，
  归属没变则不写。
- **F-B2 周期非法**：``cycle_value`` ≤ 0 抛 ValueError（0 会被 ``add_cycle``
  的 ``value or 1`` 静默当 1；负数让 ``next_execute_at`` 落到过去 → 永久逾期）。
"""
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.audit import AuditLog
from app.models.production import WorkOrder
from app.models.sync import ChangeLog
from app.models.tpm import (Equipment, EquipmentCategory, MaintenancePlan,
                            MaintenanceTask)
from app.repositories.tpm_repo import TpmRepository
from app.services.maintenance_service import MaintenanceService
from app.services.tpm_service import TpmService

pytestmark = pytest.mark.asyncio


async def _session(tables, tenant="t"):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=tables, checkfirst=True))
    factory = async_sessionmaker(engine, expire_on_commit=False)
    repo = TpmRepository(factory())
    repo.set_tenant_id(tenant)
    return engine, repo


async def _seed_equipment(repo, eq_id=1, location="A车间"):
    await repo.execute(
        "INSERT INTO equipment (id, tenant_id, equipment_code, equipment_name, "
        "location, status) VALUES (:id, :t, :c, :n, :loc, 'idle')",
        {"id": eq_id, "t": "t", "c": f"EQ-{eq_id}", "n": f"设备{eq_id}",
         "loc": location})


async def _seed_task(repo, task_id, eq_id=1, days_ago=0, status="pending"):
    start = (datetime.now(timezone.utc) - timedelta(days=days_ago)) \
        .isoformat(timespec="seconds")
    await repo.execute(
        "INSERT INTO maintenance_tasks (id, tenant_id, equipment_id, task_type, "
        "description, scheduled_start_at, status) "
        "VALUES (:id, 't', :eq, 'preventive', :d, :s, :st)",
        {"id": task_id, "eq": eq_id, "d": f"任务{task_id}", "s": start, "st": status})


# ── F-E1：逾期判定 ────────────────────────────────────────────────

async def test_overdue_grading_boundaries():
    """2 天 normal / 3 天 urgent / 6 天 urgent / 7 天 critical。"""
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            MaintenanceTask.__table__])
    await _seed_equipment(repo)
    for tid, days in ((1, 2), (2, 3), (3, 6), (4, 7), (5, 0)):
        await _seed_task(repo, tid, days_ago=days)

    data = await TpmService(repo).list_tasks(1, 20)
    rows = {r["id"]: r for r in data["items"]}

    assert rows[1]["is_overdue"] is True and rows[1]["escalation"] == "normal"
    assert rows[2]["escalation"] == "urgent"
    assert rows[3]["escalation"] == "urgent"
    assert rows[4]["escalation"] == "critical"
    # 0 天（刚刚到期/未到期）不算逾期
    assert rows[5]["is_overdue"] is False and rows[5]["overdue_days"] == 0
    assert rows[1]["overdue_days"] == 2
    await engine.dispose()


async def test_overdue_handles_string_datetime():
    """SQLite 出来的字符串时间不能 TypeError —— 这是 _as_dt 的存在理由。"""
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            MaintenanceTask.__table__])
    await _seed_equipment(repo)
    await _seed_task(repo, 1, days_ago=5)
    row = await TpmService(repo).list_tasks(1, 20)
    assert row["items"][0]["overdue_days"] == 5
    await engine.dispose()


async def test_completed_and_canceled_not_overdue():
    """做完的活不能还挂红灯。"""
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            MaintenanceTask.__table__])
    await _seed_equipment(repo)
    await _seed_task(repo, 1, days_ago=30, status="completed")
    await _seed_task(repo, 2, days_ago=30, status="canceled")
    rows = {r["id"]: r for r in (await TpmService(repo).list_tasks(1, 20))["items"]}
    for tid in (1, 2):
        assert rows[tid]["is_overdue"] is False
        assert rows[tid]["overdue_days"] == 0
        assert rows[tid]["escalation"] == "normal"
    await engine.dispose()


async def test_overdue_list_sorted_and_counted():
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            MaintenanceTask.__table__])
    await _seed_equipment(repo)
    for tid, days in ((1, 9), (2, 4), (3, 1), (4, 0)):
        await _seed_task(repo, tid, days_ago=days)
    out = await TpmService(repo).list_overdue_tasks()
    days = [r["overdue_days"] for r in out["list"]]
    assert days == sorted(days, reverse=True)
    assert out["total"] == 3          # 0 天那条不算
    assert out["critical"] == 1       # 9 天
    assert out["urgent"] == 1         # 4 天
    await engine.dispose()


# ── F-E2：报废拦截 ────────────────────────────────────────────────

async def test_scrap_blocked_by_active_work_order():
    engine, repo = await _session(
        [EquipmentCategory.__table__, Equipment.__table__,
                            WorkOrder.__table__, ChangeLog.__table__])
    await _seed_equipment(repo)
    await repo.execute(
        "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name, "
        "planned_qty, wo_status, equipment_id) "
        "VALUES (1, 't', 'WO-1', 'P1', '产品1', 10, 'released', 1)")

    with pytest.raises(ValueError) as ei:
        await TpmService(repo).update_equipment(1, {"status": "scrapped"})
    assert "在制工单" in str(ei.value)

    # 关键：拦住了就不能写库（否则"报错但状态已改"是最坏结果）
    row = await repo.query_one("SELECT status FROM equipment WHERE id = 1")
    assert row["status"] != "scrapped"
    await engine.dispose()


async def test_scrap_allowed_without_active_work_order():
    """完工/作废的工单不算在制。"""
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            WorkOrder.__table__, ChangeLog.__table__])
    await _seed_equipment(repo)
    await repo.execute(
        "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name, "
        "planned_qty, wo_status, equipment_id) "
        "VALUES (1, 't', 'WO-1', 'P1', '产品1', 10, 'completed', 1)")
    out = await TpmService(repo).update_equipment(1, {"status": "scrapped"})
    assert out["affected"] == 1
    row = await repo.query_one("SELECT status FROM equipment WHERE id = 1")
    assert row["status"] == "scrapped"
    await engine.dispose()


async def test_update_missing_equipment_raises():
    engine, repo = await _session([EquipmentCategory.__table__,
                                   Equipment.__table__, ChangeLog.__table__])
    with pytest.raises(ValueError):
        await TpmService(repo).update_equipment(999, {"status": "idle"})
    await engine.dispose()


# ── F-B1：调拨留痕 ────────────────────────────────────────────────

async def test_location_change_writes_transfer_audit():
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            AuditLog.__table__, ChangeLog.__table__])
    await _seed_equipment(repo, location="冲压车间")
    out = await TpmService(repo).update_equipment(
        1, {"location": "装配车间"}, actor_id=7, actor_name="张三")
    assert out["transfer"] == {"from": "冲压车间", "to": "装配车间"}

    log = await repo.query_one(
        "SELECT * FROM audit_logs WHERE action = 'equipment.transfer'")
    assert log is not None
    assert log["actor_id"] == 7 and log["actor_name"] == "张三"
    assert "冲压车间" in (log["before"] or "") and "装配车间" in (log["after"] or "")
    await engine.dispose()


async def test_same_location_no_audit():
    engine, repo = await _session([EquipmentCategory.__table__, Equipment.__table__,
                            AuditLog.__table__, ChangeLog.__table__])
    await _seed_equipment(repo, location="A车间")
    out = await TpmService(repo).update_equipment(1, {"location": "A车间"})
    assert out["transfer"] is None
    cnt = await repo.query_one(
        "SELECT COUNT(*) AS c FROM audit_logs WHERE action = 'equipment.transfer'")
    assert (cnt or {}).get("c") == 0
    await engine.dispose()


# ── F-B2：保养周期 ────────────────────────────────────────────────

@pytest.mark.parametrize("bad", [0, -1, -30])
async def test_plan_cycle_non_positive_rejected(bad):
    engine, repo = await _session(
        [EquipmentCategory.__table__, Equipment.__table__,
         MaintenancePlan.__table__])
    await _seed_equipment(repo)
    svc = MaintenanceService(repo)
    with pytest.raises(ValueError) as ei:
        await svc.create_plan({"tenant_id": "t", "equipment_id": 1,
                               "plan_name": "月度保养", "plan_type": "preventive",
                               "cycle_value": bad, "cycle_unit": "month"})
    assert "正整数" in str(ei.value)
    await engine.dispose()


async def test_plan_cycle_positive_computes_next_execute():
    engine, repo = await _session(
        [EquipmentCategory.__table__, Equipment.__table__,
         MaintenancePlan.__table__])
    await _seed_equipment(repo)
    out = await MaintenanceService(repo).create_plan({
        "tenant_id": "t", "equipment_id": 1, "plan_name": "月度保养",
        "plan_type": "preventive", "cycle_value": 1, "cycle_unit": "month"})
    assert out["next_execute_at"] is not None
    assert out["next_execute_at"] > datetime.now(timezone.utc)
    await engine.dispose()
