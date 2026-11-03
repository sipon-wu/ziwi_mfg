"""报工完工口径（B-1）单元测试。

## 被修的是什么

``work_orders.completed_qty`` 是**合格完工数**。改造前每一条报工都做
``completed_qty += output_qty``，不看这条报工落在哪道工序：

    一张 30 道工序、计划 15 件的工单，每道各报 5 件
    → completed_qty = 150（= 5 × 30），计划是 15

后果不只是看板难看 —— ``_raise_production_receipt`` 直接把这个数当生产入库
数量，会凭空入库 150 件。A推进器厂场景验证里这条被记成 ``B-1``
（``deliverables/A推进器厂-staging场景验证-2026-11-03.md`` §12.5）。

## 现在的判据

只有**走到路线末道工序**的产出才算完工；中间工序的产出是在制品。三条向后
兼容的出口，避免误伤简单场景：

1. 工单没挂路线（单工序 / 手工建单）→ 每条报工都算完工
2. 报工没填工序编码（"报整单"）→ 算完工
3. 填了工序编码 → 必须等于路线末道工序

报废数不受影响：报废逐件发生，每件只报废一次，跨工序累加不会重复。

## 连带改的两道闸

完工闸与作废闸原先都只看 ``completed + scrap``。B-1 之后 completed 只记末道
产出，「每道工序都报了、只是末道还没报」的工单会被判成"零产出" —— 既完不了
工，也能不作任何确认就作废。两处改成看**全部工序的累计产出**。
"""
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from sqlalchemy.pool import StaticPool

from app.services.production_service import ProductionService


class FakeRepo:
    """只管工单行、报工、状态流水与两条聚合查询。"""

    def __init__(self, order=None, reported_output=0, last_operation_code=None):
        self.order = dict(order) if order else None
        self.updates: list = []
        self.logs: list = []
        self.reports: list = []
        self.queries: list = []
        self._session = None
        self._tenant_id = "t1"
        self._write_org_id = None
        self.reported_output = reported_output
        self.last_operation_code = last_operation_code

    def set_tenant_id(self, tenant_id):
        self._tenant_id = tenant_id

    def set_write_org_id(self, org_id):
        self._write_org_id = org_id

    async def query_one(self, sql, params=None):
        self.queries.append((sql, params))
        if "FROM work_reports" in sql:
            return {"q": self.reported_output}
        if "FROM route_steps" in sql:
            return ({"code": self.last_operation_code}
                    if self.last_operation_code else None)
        return None

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
        self.logs.append({"from": from_status, "to": to_status,
                          "operator": operator_id, "remark": remark})
        return 1

    async def create_report(self, data):
        self.reports.append(dict(data))
        return len(self.reports)


def make_order(**overrides):
    base = {
        "id": 1, "tenant_id": "t1", "wo_no": "WO-001", "wo_status": "in_progress",
        "planned_qty": 15, "completed_qty": 0, "scrap_qty": 0,
        "assignee_id": 9, "assigned_org_id": None,
        "actual_start_at": None, "route_id": None,
    }
    base.update(overrides)
    return base


def make_report(**overrides):
    base = {
        "work_order_id": 1, "report_date": "2026-11-03", "reporter_id": 9,
        "input_qty": 15, "output_qty": 5, "scrap_qty": 0,
        "operation_code": None, "operation_name": None,
    }
    base.update(overrides)
    return base


def build(order=None, **kw):
    repo = FakeRepo(order=order or make_order(), **kw)
    return ProductionService(repo), repo


# ============================================================
# 一、完工数的计入判据
# ============================================================

class TestFinishedQuantityRule:

    @pytest.mark.asyncio
    async def test_no_route_counts_every_report_as_finished(self):
        """没挂路线的工单（单工序/手工建单）→ 报工直接计完工。"""
        s, repo = build()
        res = await s.create_report(make_report(output_qty=6), tenant_id="t1")
        assert res["completed_qty"] == 6
        assert res["is_finish_report"] is True
        assert res["finish_operation_code"] is None

    @pytest.mark.asyncio
    async def test_blank_operation_code_counts_as_finished(self):
        """填了路线但报工没填工序 = "报整单" → 计完工（保持改造前行为）。"""
        s, repo = build(order=make_order(route_id=7), last_operation_code="OP_LAST")
        res = await s.create_report(make_report(output_qty=4, operation_code=""), tenant_id="t1")
        assert res["completed_qty"] == 4
        assert res["is_finish_report"] is True

    @pytest.mark.asyncio
    async def test_intermediate_operation_does_not_move_completed(self):
        """中间工序的产出是在制品 —— 完工数不动，且必须告警说明原因。"""
        s, repo = build(order=make_order(route_id=7), last_operation_code="OP_LAST")
        res = await s.create_report(
            make_report(output_qty=5, operation_code="OP_FIRST"), tenant_id="t1")
        assert res["completed_qty"] == 0
        assert res["finished_delta"] == 0
        assert res["is_finish_report"] is False
        assert res["finish_operation_code"] == "OP_LAST"
        assert any("不是该工单路线的末道工序" in w for w in res["warnings"]), res["warnings"]

    @pytest.mark.asyncio
    async def test_last_operation_moves_completed(self):
        s, repo = build(order=make_order(route_id=7), last_operation_code="OP_LAST")
        res = await s.create_report(
            make_report(output_qty=5, operation_code="OP_LAST"), tenant_id="t1")
        assert res["completed_qty"] == 5
        assert res["is_finish_report"] is True

    @pytest.mark.asyncio
    async def test_thirty_operations_do_not_inflate_completed(self):
        """B-1 的原现场：30 道工序各报 5 件，完工数必须仍是 5 而不是 150。"""
        order = make_order(route_id=7, planned_qty=15)
        s, repo = build(order=order, last_operation_code="OP30")
        for i in range(1, 31):
            await s.create_report(
                make_report(output_qty=5, operation_code=f"OP{i}"), tenant_id="t1")
        assert repo.order["completed_qty"] == 5
        # 中间工序产出不该触发"超产"告警（150 超 15 那种假警报）
        res = await s.create_report(
            make_report(output_qty=5, operation_code="OP15"), tenant_id="t1")
        assert not any("超计划" in w for w in res["warnings"]), res["warnings"]

    @pytest.mark.asyncio
    async def test_scrap_still_accumulates_across_operations(self):
        """报废数是损失口径，跨工序累加不会重复计数，不随完工口径收紧。"""
        order = make_order(route_id=7)
        s, repo = build(order=order, last_operation_code="OP_LAST")
        with patch.object(ProductionService, "_raise_scrap_ncr",
                          new=AsyncMock(return_value=None)):
            res = await s.create_report(
                make_report(output_qty=0, scrap_qty=2, operation_code="OP_FIRST"),
                tenant_id="t1")
        assert res["scrap_qty"] == 2
        assert res["completed_qty"] == 0


# ============================================================
# 二、两道闸不能因为口径收紧而误拦
# ============================================================

class TestGuardsUseWipOutput:

    @pytest.mark.asyncio
    async def test_complete_allowed_when_only_wip_reported(self):
        """只有中间工序产出（completed=0）时，仍然可以完工 —— 车间确实干过活。"""
        order = make_order(wo_status="in_progress", completed_qty=0, scrap_qty=0)
        s, repo = build(order=order, reported_output=150)
        with patch.object(ProductionService, "_raise_production_receipt",
                          new=AsyncMock(return_value={"created": False})):
            res = await s.complete_work_order(1, 9)
        assert res is not None
        assert repo.order["wo_status"] == "completed"

    @pytest.mark.asyncio
    async def test_complete_still_rejects_pure_zero(self):
        order = make_order(wo_status="in_progress", completed_qty=0, scrap_qty=0)
        s, repo = build(order=order, reported_output=0)
        with pytest.raises(HTTPException) as ei:
            await s.complete_work_order(1, 9)
        assert ei.value.status_code == 400
        assert "零产出" in str(ei.value.detail) or "尚无任何报工产出" in str(ei.value.detail)

    @pytest.mark.asyncio
    async def test_cancel_requires_force_when_only_wip_reported(self):
        """有在制品时报工作废必须 force —— 否则在制产出被静默抹掉。"""
        order = make_order(wo_status="in_progress", completed_qty=0, scrap_qty=0)
        s, repo = build(order=order, reported_output=30)
        with pytest.raises(HTTPException) as ei:
            await s.cancel_work_order(1, 9, reason="客户取消")
        assert ei.value.status_code == 400
        assert "400-0009" in str(ei.value.detail)

    @pytest.mark.asyncio
    async def test_cancel_passes_with_force_and_snapshots_wip(self):
        order = make_order(wo_status="in_progress", completed_qty=0, scrap_qty=2)
        s, repo = build(order=order, reported_output=30)
        await s.cancel_work_order(1, 9, reason="客户取消", force=True,
                                  force_reason="在制品全部报废")
        remark = repo.logs[-1]["remark"]
        assert "在制+完工 30" in remark
        assert "报废 2" in remark


# ============================================================
# 三、末道工序的 SQL 在真库上跑得通（SQLite 方言）
# ============================================================
# 替身能证明"判据写对了"，证明不了"SQL 写对了"。这里把 ``_last_operation_code``
# 的原文 SQL 直接打在内存库上：JOIN 写错列名、排序写错、方言不兼容都会当场炸。

DDL = """
CREATE TABLE operations (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  code TEXT NOT NULL,
  name TEXT
);
CREATE TABLE route_steps (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  tenant_id TEXT NOT NULL,
  route_id INTEGER NOT NULL,
  operation_id INTEGER NOT NULL,
  step_seq INTEGER NOT NULL
);
"""


class _SqlRepo:
    """只把 query_one 落到真 session 上，不做租户注入（测试里自备数据）。"""

    def __init__(self, session):
        self._session = session

    async def query_one(self, sql, params=None):
        res = await self._session.execute(text(sql), params or {})
        row = res.mappings().first()
        return dict(row) if row else None


@pytest.fixture
async def sql_session():
    engine = create_async_engine(
        "sqlite+aiosqlite://",
        poolclass=StaticPool,
        connect_args={"check_same_thread": False},
    )
    async with engine.begin() as conn:
        for stmt in [s.strip() for s in DDL.split(";") if s.strip()]:
            await conn.execute(text(stmt))
        # 路线 7：三步 OP10 → OP20 → OP30（故意乱序插入，考验 ORDER BY）
        await conn.execute(text(
            "INSERT INTO operations (tenant_id, code, name) VALUES "
            "('t1','OP10','下料'),('t1','OP20','机加'),('t1','OP30','总装')"))
        await conn.execute(text(
            "INSERT INTO route_steps (tenant_id, route_id, operation_id, step_seq) "
            "VALUES ('t1',7,3,30),('t1',7,1,10),('t1',7,2,20)"))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield s
    await engine.dispose()


class TestLastOperationSql:

    @pytest.mark.asyncio
    async def test_picks_max_step_seq(self, sql_session):
        svc = ProductionService(_SqlRepo(sql_session))
        code = await svc._last_operation_code({"id": 1, "route_id": 7})
        assert code == "OP30"

    @pytest.mark.asyncio
    async def test_no_route_returns_none(self, sql_session):
        svc = ProductionService(_SqlRepo(sql_session))
        assert await svc._last_operation_code({"id": 1, "route_id": None}) is None

    @pytest.mark.asyncio
    async def test_unknown_route_returns_none(self, sql_session):
        svc = ProductionService(_SqlRepo(sql_session))
        assert await svc._last_operation_code({"id": 1, "route_id": 999}) is None

    @pytest.mark.asyncio
    async def test_single_step_route_is_its_own_last(self, sql_session):
        await sql_session.execute(text(
            "INSERT INTO route_steps (tenant_id, route_id, operation_id, step_seq) "
            "VALUES ('t1',8,2,10)"))
        await sql_session.commit()
        svc = ProductionService(_SqlRepo(sql_session))
        assert await svc._last_operation_code({"id": 1, "route_id": 8}) == "OP20"
