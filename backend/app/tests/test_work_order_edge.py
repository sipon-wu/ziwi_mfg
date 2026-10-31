"""C 区工单异常/边界 — 单元测试（C-E3 / C-E4 / C-E5 / C-B2 / C-E7）。

这批测的不是"能不能报工"，而是**边界到底有没有人管**：

- 暂停中的工单能不能报工（停机期间产出 = 假数据）
- 已有产出的工单能不能凭一句原因作废（报工数据会不会成孤儿）
- 报工时刻早于开工能不能拦（时序错乱）
- 工单能不能挂到已停用的工作中心 / 已报废的设备上

以及一条**工具层**的坑：SQLite 的 DateTime 列取出来是字符串，与请求体里的
``datetime`` 直接比较会 TypeError → 报工接口 500。``_as_dt`` 就是为此存在，
这里把它单独钉死，免得哪天有人"简化"掉它。
"""
from datetime import date, datetime

import pytest
from unittest.mock import AsyncMock

from app.constants.work_order_states import REPORT_BLOCKED_STATUSES
from app.services.production_service import ProductionService, _as_dt


def _svc(order, query_one=None):
    repo = AsyncMock()
    repo.get_work_order = AsyncMock(return_value=order)
    repo.create_report = AsyncMock(return_value=1)
    repo.update_work_order = AsyncMock(return_value=1)
    repo.query_one = AsyncMock(return_value=query_one if query_one is not None else {})
    repo.execute = AsyncMock(return_value=1)
    return ProductionService(repo)


def _order(status="in_progress", **kw):
    base = {"id": 1, "wo_status": status, "planned_qty": 100,
            "completed_qty": 0, "scrap_qty": 0, "org_id": 1,
            "assignee_id": None, "assigned_org_id": None,
            "actual_start_at": None}
    base.update(kw)
    return base


# ── _as_dt：时间归一化（C-B2 的 500 就出在这） ──────────────────────

class TestAsDt:
    def test_sqlite_string(self):
        """SQLite 的 DateTime 列取出来是 'YYYY-MM-DD HH:MM:SS.ffffff'。"""
        assert _as_dt("2026-11-01 00:31:49.365141") == datetime(2026, 11, 1, 0, 31, 49, 365141)

    def test_iso_with_t(self):
        assert _as_dt("2026-11-01T00:31:49") == datetime(2026, 11, 1, 0, 31, 49)

    def test_date_only(self):
        assert _as_dt("2026-11-01") == datetime(2026, 11, 1)

    def test_date_object(self):
        assert _as_dt(date(2026, 11, 1)) == datetime(2026, 11, 1)

    def test_datetime_passthrough(self):
        d = datetime(2026, 11, 1, 8, 0)
        assert _as_dt(d) is d

    def test_tzaware_stripped(self):
        """PG 下取出来是 tz-aware，请求体也可能是带时区的 —— 混比会崩。"""
        from datetime import timezone
        d = datetime(2026, 11, 1, 8, 0, tzinfo=timezone.utc)
        assert _as_dt(d) == datetime(2026, 11, 1, 8, 0)

    def test_none_and_garbage(self):
        assert _as_dt(None) is None
        assert _as_dt("not-a-time") is None
        assert _as_dt(123) is None


# ── C-E4 暂停中禁止报工 ────────────────────────────────────────────

class TestPausedNoReport:
    def test_paused_is_blocked(self):
        """最基本的一条：paused 必须在禁止报工集合里。

        不在里面的后果是"停机期间照样有产出进账"—— 暂停不计工时成了空话，
        同一段时间既记停机又记产出，OEE 两个口径谁都不敢信。
        """
        assert "paused" in REPORT_BLOCKED_STATUSES

    async def test_report_on_paused_rejected(self):
        svc = _svc(_order("paused"))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc.create_report(
                {"work_order_id": 1, "report_date": date(2026, 11, 1),
                 "output_qty": 5}, "t1")
        assert e.value.status_code == 400
        # 报错必须给可执行的下一步，不能只说"不允许"
        assert "resume" in e.value.detail["message"] or "恢复" in e.value.detail["message"]

    async def test_report_on_in_progress_ok(self):
        svc = _svc(_order("in_progress"))
        r = await svc.create_report(
            {"work_order_id": 1, "report_date": date(2026, 11, 1),
             "output_qty": 5}, "t1")
        assert r["completed_qty"] == 5


# ── C-E3 未派工报工必须有提示 ──────────────────────────────────────

class TestUnassignedReport:
    async def test_warn_when_no_assignee(self):
        svc = _svc(_order("in_progress"))
        r = await svc.create_report(
            {"work_order_id": 1, "report_date": date(2026, 11, 1),
             "output_qty": 5}, "t1")
        assert any("派工" in w for w in r["warnings"])

    async def test_no_warn_when_assigned(self):
        svc = _svc(_order("in_progress", assignee_id=7))
        r = await svc.create_report(
            {"work_order_id": 1, "report_date": date(2026, 11, 1),
             "output_qty": 5}, "t1")
        assert not any("派工" in w for w in r["warnings"])


# ── C-B2 报工时刻早于开工 ──────────────────────────────────────────

class TestReportTimeOrder:
    async def test_reported_at_before_start_rejected(self):
        svc = _svc(_order("in_progress",
                          actual_start_at="2026-11-01 08:00:00"))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc.create_report(
                {"work_order_id": 1, "report_date": date(2026, 11, 1),
                 "output_qty": 5,
                 "reported_at": datetime(2026, 10, 1, 8, 0)}, "t1")
        assert e.value.status_code == 400
        assert "早于" in e.value.detail["message"]

    async def test_report_date_earlier_only_warns(self):
        """补录是正常业务（昨天干的活今天补），只告警不阻断。"""
        svc = _svc(_order("in_progress",
                          actual_start_at="2026-11-01 08:00:00"))
        r = await svc.create_report(
            {"work_order_id": 1, "report_date": date(2026, 10, 1),
             "output_qty": 5}, "t1")
        assert r["report_id"] == 1
        assert any("报工日期" in w for w in r["warnings"])

    async def test_reported_at_after_start_ok(self):
        svc = _svc(_order("in_progress",
                          actual_start_at="2026-11-01 08:00:00"))
        r = await svc.create_report(
            {"work_order_id": 1, "report_date": date(2026, 11, 1),
             "output_qty": 5,
             "reported_at": datetime(2026, 11, 1, 10, 0)}, "t1")
        assert r["report_id"] == 1
        assert not any("报工时刻" in w for w in r["warnings"])


# ── C-E5 已有产出的工单不能凭一句原因作废 ──────────────────────────

class TestCancelWithOutput:
    async def test_cancel_with_output_rejected(self):
        svc = _svc(_order("in_progress", completed_qty=16))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc.cancel_work_order(1, 1, reason="客户取消")
        assert e.value.status_code == 400
        assert "孤儿" in e.value.detail["message"]

    async def test_force_requires_disposition(self):
        svc = _svc(_order("in_progress", completed_qty=16))
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc.cancel_work_order(1, 1, reason="客户取消", force=True)
        assert e.value.status_code == 400
        assert "force_reason" in e.value.detail["message"]

    async def test_force_with_disposition_ok(self):
        svc = _svc(_order("in_progress", completed_qty=16, scrap_qty=2))
        svc.change_status = AsyncMock(return_value={"message": "ok"})
        await svc.cancel_work_order(1, 1, reason="客户取消", force=True,
                                    force_reason="已产出全部报废")
        # 产出快照必须进流水：事后要能回答"作废时到底做了多少"
        remark = svc.change_status.call_args.kwargs["remark"]
        assert "16" in remark and "2" in remark

    async def test_cancel_without_output_ok(self):
        """没有产出的工单照旧一句原因就能作废，不该被新规则误伤。"""
        svc = _svc(_order("released"))
        svc.change_status = AsyncMock(return_value={"message": "ok"})
        await svc.cancel_work_order(1, 1, reason="计划取消")
        svc.change_status.assert_awaited_once()


# ── C-E7 工单不能挂停用资源 ────────────────────────────────────────

class TestResourceValidation:
    async def test_inactive_work_center_rejected(self):
        svc = _svc(_order(), query_one={"id": 3, "name": "A线", "is_active": False})
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc._validate_resources({"work_center_id": 3})
        assert e.value.status_code == 400
        assert "已停用" in e.value.detail["message"]

    async def test_scrapped_equipment_rejected(self):
        svc = _svc(_order(), query_one={"id": 5, "equipment_name": "1号机",
                                        "status": "scrapped"})
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc._validate_resources({"equipment_id": 5})
        assert e.value.status_code == 400

    async def test_fault_equipment_only_warns(self):
        """故障/维修中的设备只告警：现场确实会先排到待修设备上等修好。"""
        svc = _svc(_order(), query_one={"id": 5, "equipment_name": "1号机",
                                        "status": "fault"})
        warns = await svc._validate_resources({"equipment_id": 5})
        assert warns and any("故障" in w for w in warns)

    async def test_missing_resource_rejected(self):
        svc = _svc(_order(), query_one=None)
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as e:
            await svc._validate_resources({"work_center_id": 999})
        assert e.value.status_code == 400
        assert "不存在" in e.value.detail["message"]

    async def test_active_resource_passes(self):
        svc = _svc(_order(), query_one={"id": 3, "name": "A线", "is_active": True})
        assert await svc._validate_resources({"work_center_id": 3}) == []
