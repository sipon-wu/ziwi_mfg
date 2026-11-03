"""工单全生命周期状态机 + 报工联动 单元测试。

覆盖改造点（出处 ``docs/scenario-verification-2026-10-29.md`` §六-1/2、§三 C 区）：

1. 状态流转矩阵：合法/非法/重复/终态
2. 时间戳副作用：``actual_start_at``（开工）与 ``actual_end_at``（完工）
3. 完工护栏：零产出拒绝、force 放行、超产/欠产只告警
4. 关闭语义收紧：``released`` 不能直接关闭，须先完工
5. 报工断言：数量为 0、负数、草稿/终态工单
6. 报工联动：已下达自动开工、报废自动开 NCR（幂等）
7. 前端按钮数据源：``available_actions``
8. 权限码：新增 pause/resume 后缀不污染资源名
"""
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import HTTPException

from app.constants.work_order_states import (
    REPORT_BLOCKED_STATUSES,
    WORK_ORDER_STATUSES,
    action_of,
    available_actions,
    can_transition,
    format_allowed,
    status_label,
)
from app.services.production_service import ProductionService


# ============================================================
# 测试替身
# ============================================================

class FakeRepo:
    """最小 Repository 替身：只管工单行、更新记录与状态流水。"""

    def __init__(self, order=None, reported_output=0, last_operation_code=None):
        self.order = order
        self.updates: list = []
        self.logs: list = []
        self.reports: list = []
        self._session = None
        self._tenant_id = "t1"
        self._write_org_id = None
        #: B-1：报工累计产出（完工闸读它）。默认 0，闸门转而看工单行的
        #: completed_qty，行为与改造前一致。
        self.reported_output = reported_output
        #: B-1：路线末道工序编码。默认 None = 工单没挂路线，每条报工都算完工。
        self.last_operation_code = last_operation_code
        self.queries: list = []

    async def query_one(self, sql, params=None):
        self.queries.append((sql, params))
        if "FROM work_reports" in sql:
            return {"q": self.reported_output}
        if "FROM route_steps" in sql:
            return ({"code": self.last_operation_code}
                    if self.last_operation_code else None)
        return None

    def set_tenant_id(self, tenant_id):
        self._tenant_id = tenant_id

    def set_write_org_id(self, org_id):
        self._write_org_id = org_id

    async def get_work_order(self, id):
        return dict(self.order) if self.order else None

    async def update_work_order(self, id, data):
        self.updates.append(dict(data))
        if self.order:
            self.order.update(data)
        return 1

    async def change_status(self, id, status):
        return await self.update_work_order(id, {"wo_status": status})

    async def add_status_log(self, order_id, from_status, to_status, operator_id,
                             remark=None):
        self.logs.append({
            "from": from_status, "to": to_status,
            "operator": operator_id, "remark": remark,
        })
        return 1

    async def create_report(self, data):
        self.reports.append(dict(data))
        return len(self.reports)


def make_order(**overrides):
    base = {
        "id": 1, "tenant_id": "t1", "wo_no": "WO-001",
        "product_code": "P001", "product_name": "测试产品",
        "wo_status": "draft", "planned_qty": 100,
        "completed_qty": 0, "scrap_qty": 0,
        "actual_start_at": None, "actual_end_at": None,
        "org_id": 5,
    }
    base.update(overrides)
    return base


def svc(order=None):
    repo = FakeRepo(order)
    return ProductionService(repo), repo


# ============================================================
# 1. 状态机矩阵
# ============================================================

LEGAL_EDGES = [
    ("draft", "released"), ("draft", "cancelled"),
    ("released", "in_progress"), ("released", "cancelled"),
    ("in_progress", "paused"), ("in_progress", "completed"),
    ("in_progress", "cancelled"),
    ("paused", "in_progress"), ("paused", "cancelled"),
    ("completed", "closed"),
]

ILLEGAL_EDGES = [
    ("draft", "in_progress"),        # 跳过了下达（无 BOM 快照/齐套）
    ("draft", "completed"),
    ("released", "completed"),       # 没开工就完工
    ("released", "closed"),          # ★ 改造前允许，现在必须走过完工
    ("released", "paused"),
    ("in_progress", "released"),     # 回退
    ("completed", "in_progress"),    # 完工后回炉
    ("completed", "draft"),
    ("closed", "draft"),             # 终态复活
    ("cancelled", "released"),
]


@pytest.mark.parametrize("src,dst", LEGAL_EDGES)
def test_legal_transitions(src, dst):
    assert can_transition(src, dst) is True


@pytest.mark.parametrize("src,dst", ILLEGAL_EDGES)
def test_illegal_transitions(src, dst):
    assert can_transition(src, dst) is False


def test_transition_table_covers_all_statuses():
    """新增状态必须同时登记流转表，否则状态机会把它当终态静默锁死。"""
    from app.constants.work_order_states import WORK_ORDER_TRANSITIONS
    assert set(WORK_ORDER_TRANSITIONS) == set(WORK_ORDER_STATUSES)


def test_terminal_statuses_have_no_exit():
    for terminal in ("closed", "cancelled"):
        assert not any(can_transition(terminal, s) for s in WORK_ORDER_STATUSES)


def test_unknown_from_status_is_illegal():
    assert can_transition(None, "released") is False
    assert can_transition("bogus", "released") is False
    # 未知状态不能被报成"已是终态" —— 那会把排查方向引到状态机上
    assert "未知状态" in format_allowed(None)
    assert "终态" in format_allowed("closed")


def test_action_of_distinguishes_resume_from_start():
    """暂停后恢复必须记 resume，否则流水里出现两条 start，停机会被低估。"""
    assert action_of("released", "in_progress") == "start"
    assert action_of("paused", "in_progress") == "resume"
    assert action_of("in_progress", "paused") == "pause"
    assert action_of("in_progress", "completed") == "complete"
    assert action_of("completed", "closed") == "close"
    assert action_of("draft", "released") == "release"


def test_status_label_falls_back_to_raw_value():
    assert status_label("in_progress") == "生产中"
    assert status_label("unknown_x") == "unknown_x"
    assert status_label(None) == ""


# ============================================================
# 2. change_status 行为
# ============================================================

async def test_change_status_rejects_illegal_with_allowed_list():
    s, repo = svc(make_order(wo_status="released"))
    with pytest.raises(HTTPException) as ei:
        await s.change_status(1, "closed", 9)
    assert ei.value.status_code == 400
    detail = ei.value.detail
    assert detail["code"] == "400-0002"
    # 报错文案必须自己说清能去哪，否则前端只能猜
    assert "in_progress" in detail["message"]
    assert repo.updates == [] and repo.logs == []


async def test_change_status_rejects_same_status():
    s, repo = svc(make_order(wo_status="in_progress"))
    with pytest.raises(HTTPException) as ei:
        await s.change_status(1, "in_progress", 9)
    assert ei.value.detail["code"] == "400-0001"
    assert repo.updates == []


async def test_change_status_404_when_order_missing():
    s, _ = svc(None)
    with pytest.raises(HTTPException) as ei:
        await s.change_status(999, "released", 9)
    assert ei.value.status_code == 404


async def test_change_status_writes_log_with_action():
    s, repo = svc(make_order(wo_status="draft"))
    await s.change_status(1, "released", 9)
    assert repo.order["wo_status"] == "released"
    assert repo.logs[0]["remark"] == "action=release"
    assert repo.logs[0]["from"] == "draft"


# ============================================================
# 3. 开工 / 暂停 / 恢复
# ============================================================

async def test_start_writes_actual_start_at():
    s, repo = svc(make_order(wo_status="released", actual_start_at=None))
    result = await s.start_work_order(1, 9)
    assert result["to_status"] == "in_progress"
    assert repo.order["wo_status"] == "in_progress"
    assert repo.order["actual_start_at"] is not None


async def test_start_keeps_original_actual_start_at():
    """补录开工不应把首次开工时间往后推。"""
    original = "2026-10-01T08:00:00"
    s, repo = svc(make_order(wo_status="released", actual_start_at=original))
    await s.start_work_order(1, 9)
    assert repo.order["actual_start_at"] == original


async def test_pause_reason_goes_into_log():
    s, repo = svc(make_order(wo_status="in_progress"))
    await s.pause_work_order(1, 9, reason="缺料待料")
    assert repo.order["wo_status"] == "paused"
    assert "缺料待料" in repo.logs[0]["remark"]


async def test_resume_does_not_touch_actual_start_at():
    original = "2026-10-01T08:00:00"
    s, repo = svc(make_order(wo_status="paused", actual_start_at=original))
    await s.resume_work_order(1, 9)
    assert repo.order["wo_status"] == "in_progress"
    assert repo.order["actual_start_at"] == original
    assert repo.logs[0]["remark"] == "action=resume"


# ============================================================
# 4. 完工护栏
# ============================================================

async def test_complete_rejects_zero_output():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=0, scrap_qty=0))
    with pytest.raises(HTTPException) as ei:
        await s.complete_work_order(1, 9)
    assert ei.value.detail["code"] == "400-0003"
    assert repo.order["wo_status"] == "in_progress"


async def test_complete_force_allows_zero_output():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=0, scrap_qty=0))
    result = await s.complete_work_order(1, 9, force=True, force_reason="客户取消，直接收尾")
    assert result["to_status"] == "completed"
    assert "客户取消" in repo.logs[0]["remark"]


async def test_complete_writes_actual_end_at():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=100))
    await s.complete_work_order(1, 9)
    assert repo.order["wo_status"] == "completed"
    assert repo.order["actual_end_at"] is not None


async def test_complete_warns_overproduction_but_passes():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=120, planned_qty=100))
    result = await s.complete_work_order(1, 9)
    assert result["to_status"] == "completed"
    assert any("超计划" in w for w in result["warnings"])


async def test_complete_warns_underproduction():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=60, planned_qty=100))
    result = await s.complete_work_order(1, 9)
    assert any("少于计划" in w for w in result["warnings"])


# ============================================================
# 5. 关闭 / 作废
# ============================================================

async def test_close_requires_completed():
    """★ 行为变更：改造前 released 可直接 close，工单凭空消失。"""
    s, repo = svc(make_order(wo_status="released"))
    with pytest.raises(HTTPException) as ei:
        await s.close_work_order(1, 9)
    assert ei.value.status_code == 400
    assert repo.order["wo_status"] == "released"


async def test_close_from_completed():
    s, repo = svc(make_order(wo_status="completed"))
    result = await s.close_work_order(1, 9)
    assert result["to_status"] == "closed"
    assert repo.order["wo_status"] == "closed"


async def test_cancel_requires_reason():
    s, repo = svc(make_order(wo_status="draft"))
    with pytest.raises(HTTPException) as ei:
        await s.cancel_work_order(1, 9)
    assert ei.value.detail["code"] == "400-0004"
    assert repo.order["wo_status"] == "draft"


async def test_cancel_from_in_progress_keeps_reason():
    s, repo = svc(make_order(wo_status="in_progress"))
    await s.cancel_work_order(1, 9, reason="客户撤单")
    assert repo.order["wo_status"] == "cancelled"
    assert "客户撤单" in repo.logs[0]["remark"]


async def test_terminal_order_cannot_be_cancelled():
    s, repo = svc(make_order(wo_status="completed"))
    with pytest.raises(HTTPException):
        await s.cancel_work_order(1, 9, reason="试试")


# ============================================================
# 6. 前端按钮数据源
# ============================================================

@pytest.mark.parametrize("status,expected", [
    ("draft", {"release", "cancel"}),
    ("released", {"start", "cancel"}),
    ("in_progress", {"pause", "complete", "cancel"}),
    ("paused", {"resume", "cancel"}),
    ("completed", {"close"}),
    ("closed", set()),
    ("cancelled", set()),
])
def test_available_actions(status, expected):
    assert {a["action"] for a in available_actions(status)} == expected


async def test_get_work_order_exposes_actions_and_label():
    s, _ = svc(make_order(wo_status="paused"))
    order = await s.get_work_order(1)
    assert order["status_label"] == "已暂停"
    assert [a["action"] for a in order["available_actions"]] == ["resume", "cancel"]


# ============================================================
# 7. 报工断言
# ============================================================

async def test_report_rejects_zero_qty():
    s, repo = svc(make_order(wo_status="in_progress"))
    with pytest.raises(HTTPException) as ei:
        await s.create_report({"work_order_id": 1, "output_qty": 0, "scrap_qty": 0}, "t1")
    assert ei.value.detail["code"] == "400-0006"
    assert repo.reports == []


async def test_report_rejects_negative_qty():
    s, _ = svc(make_order(wo_status="in_progress"))
    with pytest.raises(HTTPException) as ei:
        await s.create_report({"work_order_id": 1, "output_qty": -5, "scrap_qty": 0}, "t1")
    assert ei.value.detail["code"] == "400-0005"


@pytest.mark.parametrize("blocked", sorted(REPORT_BLOCKED_STATUSES))
async def test_report_rejects_blocked_status(blocked):
    s, repo = svc(make_order(wo_status=blocked))
    with pytest.raises(HTTPException) as ei:
        await s.create_report({"work_order_id": 1, "output_qty": 5}, "t1")
    assert ei.value.detail["code"] == "400-0007"
    assert repo.reports == []


async def test_report_404_when_order_missing():
    s, _ = svc(None)
    with pytest.raises(HTTPException) as ei:
        await s.create_report({"work_order_id": 404, "output_qty": 5}, "t1")
    assert ei.value.status_code == 404


# ============================================================
# 8. 报工联动
# ============================================================

async def test_report_auto_starts_released_order():
    s, repo = svc(make_order(wo_status="released", actual_start_at=None))
    result = await s.create_report({"work_order_id": 1, "output_qty": 10, "reporter_id": 9}, "t1")
    assert result["started"] is True
    assert repo.order["wo_status"] == "in_progress"
    assert repo.order["actual_start_at"] is not None
    assert repo.logs[0]["remark"].startswith("action=start")


async def test_report_does_not_restart_in_progress_order():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=5))
    result = await s.create_report({"work_order_id": 1, "output_qty": 10}, "t1")
    assert result["started"] is False
    assert repo.logs == []
    assert repo.order["completed_qty"] == 15


async def test_report_accumulates_scrap():
    s, repo = svc(make_order(wo_status="in_progress", completed_qty=10, scrap_qty=2))
    with patch.object(ProductionService, "_raise_scrap_ncr", new=AsyncMock(return_value=None)):
        result = await s.create_report(
            {"work_order_id": 1, "output_qty": 5, "scrap_qty": 3, "defect_reason": "毛刺"}, "t1")
    assert result["completed_qty"] == 15
    assert result["scrap_qty"] == 5


async def test_report_overproduction_returns_warning():
    s, repo = svc(make_order(wo_status="in_progress", planned_qty=10, completed_qty=8))
    with patch.object(ProductionService, "_raise_scrap_ncr", new=AsyncMock(return_value=None)):
        result = await s.create_report({"work_order_id": 1, "output_qty": 5}, "t1")
    assert any("超计划" in w for w in result["warnings"])


async def test_report_scrap_triggers_ncr():
    s, repo = svc(make_order(wo_status="in_progress"))
    with patch.object(ProductionService, "_raise_scrap_ncr",
                      new=AsyncMock(return_value=77)) as mock_ncr:
        result = await s.create_report(
            {"work_order_id": 1, "output_qty": 10, "scrap_qty": 2,
             "defect_reason": "尺寸超差", "reporter_id": 9}, "t1")
    assert result["ncr_id"] == 77
    kwargs = mock_ncr.call_args.kwargs
    assert kwargs["scrap_qty"] == 2
    assert kwargs["defect_reason"] == "尺寸超差"


async def test_report_no_scrap_no_ncr():
    s, _ = svc(make_order(wo_status="in_progress"))
    with patch.object(ProductionService, "_raise_scrap_ncr",
                      new=AsyncMock(return_value=1)) as mock_ncr:
        result = await s.create_report({"work_order_id": 1, "output_qty": 10}, "t1")
    assert result["ncr_id"] is None
    mock_ncr.assert_not_awaited()


async def test_raise_scrap_ncr_builds_payload_and_is_idempotent():
    """报废 NCR：来源固定 process，一张报工单只开一张评审单。"""
    order = make_order(wo_status="in_progress", wo_no="WO-777")
    repo = FakeRepo(order)
    s = ProductionService(repo)

    created_payload = {}

    fake_ncr_repo = MagicMock()
    fake_ncr_repo.set_tenant_id = MagicMock()
    fake_ncr_repo.set_write_org_id = MagicMock()
    fake_ncr_repo.get_by_source = AsyncMock(return_value=None)

    fake_svc = MagicMock()
    fake_svc.create_ncr = AsyncMock(return_value={"id": 101})

    with (
        patch("app.repositories.ncr_repo.NcrRepository", return_value=fake_ncr_repo),
        patch("app.services.ncr_service.NcrService", return_value=fake_svc),
    ):
        ncr_id = await s._raise_scrap_ncr(
            order=order, report_id=55, scrap_qty=3, output_qty=7,
            defect_reason="气孔", reporter_id=9, tenant_id="t1")

    assert ncr_id == 101
    payload = fake_svc.create_ncr.call_args[0][0]
    assert payload["source_type"] == "process"
    assert payload["source_id"] == 55
    assert payload["defect_qty"] == 3
    assert payload["total_qty"] == 10
    assert payload["work_order_id"] == 1
    # 写入归属必须继承，否则部门负责人看不到自己工单开出的 NCR
    fake_ncr_repo.set_write_org_id.assert_called_once_with(5)


async def test_raise_scrap_ncr_returns_existing_on_repeat():
    order = make_order(wo_status="in_progress")
    s = ProductionService(FakeRepo(order))

    fake_ncr_repo = MagicMock()
    fake_ncr_repo.set_tenant_id = MagicMock()
    fake_ncr_repo.set_write_org_id = MagicMock()
    fake_ncr_repo.get_by_source = AsyncMock(return_value={"id": 88})

    fake_svc = MagicMock()
    fake_svc.create_ncr = AsyncMock()

    with (
        patch("app.repositories.ncr_repo.NcrRepository", return_value=fake_ncr_repo),
        patch("app.services.ncr_service.NcrService", return_value=fake_svc),
    ):
        ncr_id = await s._raise_scrap_ncr(
            order=order, report_id=55, scrap_qty=3, output_qty=0,
            defect_reason=None, reporter_id=9, tenant_id="t1")

    assert ncr_id == 88
    fake_svc.create_ncr.assert_not_awaited()


async def test_raise_scrap_ncr_failure_does_not_break_report():
    """开 NCR 失败不能回滚已成功的报工 —— 报工是事实，评审单是后续动作。"""
    order = make_order(wo_status="in_progress")
    s = ProductionService(FakeRepo(order))
    with patch("app.repositories.ncr_repo.NcrRepository", side_effect=RuntimeError("boom")):
        ncr_id = await s._raise_scrap_ncr(
            order=order, report_id=55, scrap_qty=3, output_qty=0,
            defect_reason=None, reporter_id=9, tenant_id="t1")
    assert ncr_id is None


# ============================================================
# 9. 权限码：新增后缀不得污染资源名
# ============================================================

@pytest.mark.parametrize("suffix,action", [
    ("start", "execute"), ("pause", "execute"), ("resume", "execute"),
    ("complete", "execute"), ("close", "execute"), ("cancel", "execute"),
])
def test_work_order_action_suffix_permission(suffix, action):
    from app.core.permissions import derive_action, derive_permission_code
    from app.constants.modules import make_perm_code

    code = derive_permission_code(
        f"/api/v1/work-orders/{{order_id}}/{suffix}", "POST", "app.api.production")
    assert code == make_perm_code("M01", "work_order", action)
    assert derive_action(f"/api/v1/work-orders/{{order_id}}/{suffix}", "POST") == action


def test_new_endpoints_registered_and_mapped():
    from app.core.permissions import build_permission_map
    from app.main import app

    m = build_permission_map(app)
    for suffix in ("start", "pause", "resume", "complete", "close", "cancel"):
        key = (f"/api/v1/work-orders/{{order_id}}/{suffix}", "POST")
        assert key in m, f"端点未注册: {key}"
        assert m[key] == "M01:work_order:execute"
    assert ("/api/v1/work-orders/{order_id}/actions", "GET") in m
