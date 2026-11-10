"""工序任务台（`work_order_steps`）的仓储层测试 —— 跑真 SQLite，不 mock SQL。

## 为什么这一层必须跑真库

这里的四条 SQL 都是"错了不会报错、只会算错"的类型：

- `expand_steps_from_route`：漏了 `NOT EXISTS` → 重复下达就多出一倍工序行，
  界面上看着"这道工序有两条"，产量被摊成两半；
- `apply_report_to_step`：把累计与状态判定拆成两步 → 并发下少算产量，
  而两条报工记录都在，事后对不上任何数；
- `list_work_steps` 的 `scope` 分档：判错一档 → 待作业 tab 里混进已完工的活，
  工人翻三屏找不到该干的；
- `blocked` 标记：`NOT IN` 写反 → 安灯已解决的单还标着"阻塞"，
  现场跑去看一个不存在的问题。

用 FakeRepo 测这些等于测了个假 SQL。所以这里建真表、真插数据、真查。

## 不测什么

`report_step()` 的编排（工序由路径决定、找不到工序 404）在
`test_step_report.py` 里用 FakeRepo 测 —— 那部分没有 SQL，测的是接线。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.andon import AndonCall
from app.models.basic_data import Operation, RouteStep, WorkCenter
from app.models.production import WorkOrder, WorkOrderStep
from app.repositories.production_repo import ProductionRepository

TABLES = [
    WorkOrder.__table__, WorkOrderStep.__table__,
    RouteStep.__table__, Operation.__table__, WorkCenter.__table__,
    AndonCall.__table__,
]

# 路线 100 = 两道工序（CW010 车 / CW020 铣），各挂一个工作中心。
# 工单 1 挂这条路线；工单 2 **故意不挂路线** —— 老单"报整单"的合法形态。
SEED = [
    "INSERT INTO operations (id, tenant_id, code, name, op_type) VALUES "
    "(1, 't', 'CW010', '车削', 'machining'), "
    "(2, 't', 'CW020', '铣削', 'machining')",
    "INSERT INTO work_centers (id, tenant_id, code, name, wc_type) VALUES "
    "(10, 't', 'WC-CNC', '数控工位', 'machine'), "
    "(11, 't', 'WC-MILL', '铣削工位', 'machine')",
    "INSERT INTO route_steps (id, tenant_id, route_id, operation_id, step_seq, wc_id,"
    " step_type) VALUES "
    "(100, 't', 100, 1, 1, 10, 'production'), "
    "(101, 't', 100, 2, 2, 11, 'production')",
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name,"
    " planned_qty, wo_status, route_id) VALUES "
    "(1, 't', 'WO-1', 'P-1', '整机', 10, 'released', 100), "
    "(2, 't', 'WO-2', 'P-2', '老单', 5, 'released', NULL)",
]


@pytest.fixture
async def repo():
    engine = create_async_engine(
        "sqlite+aiosqlite:///:memory:",
        connect_args={"check_same_thread": False}, poolclass=StaticPool)
    async with engine.begin() as conn:
        await conn.run_sync(lambda c: Base.metadata.create_all(c, tables=TABLES))
        for sql in SEED:
            await conn.execute(text(sql))
    session = async_sessionmaker(engine, expire_on_commit=False)()
    r = ProductionRepository(session)
    r.set_tenant_id("t")
    yield r
    await session.close()
    await engine.dispose()


async def _count(repo, sql: str, params=None) -> int:
    row = await repo.query_one(sql, params or {})
    return int(list(row.values())[0] or 0)


class TestExpandSteps:
    async def test_expands_from_route(self, repo):
        order = await repo.get_work_order(1)
        n = await repo.expand_steps_from_route(order)
        assert n == 2, f"应按路线展开 2 道工序，实际 {n}"
        rows = await repo.steps_of_order(1)
        assert [r["step_seq"] for r in rows] == [1, 2]
        assert [r["operation_code"] for r in rows] == ["CW010", "CW020"]
        # 工作中心与计划量都是**快照**，不是查询时现算
        assert [r["wc_id"] for r in rows] == [10, 11]
        assert all(r["planned_qty"] == 10 for r in rows)

    async def test_is_idempotent(self, repo):
        """重复下达不能多出工序行 —— 少一个 NOT EXISTS 就会翻倍。"""
        order = await repo.get_work_order(1)
        await repo.expand_steps_from_route(order)
        await repo.expand_steps_from_route(order)
        assert await _count(
            repo, "SELECT COUNT(*) FROM work_order_steps WHERE work_order_id = 1") == 2

    async def test_no_route_expands_nothing(self, repo):
        """无路线老单不造工序 —— 造了等于把"没有路线"从数据上抹掉。"""
        order = await repo.get_work_order(2)
        assert await repo.expand_steps_from_route(order) == 0
        assert await repo.steps_of_order(2) == []

    async def test_new_steps_start_pending(self, repo):
        order = await repo.get_work_order(1)
        await repo.expand_steps_from_route(order)
        rows = await repo.steps_of_order(1)
        assert {r["status"] for r in rows} == {"pending"}
        assert all((r["output_qty"] or 0) == 0 for r in rows)


class TestApplyReport:
    async def _step(self, repo, seq=1):
        await repo.expand_steps_from_route(await repo.get_work_order(1))
        return await repo.get_step(1, seq)

    async def test_accumulates_and_moves_to_in_progress(self, repo):
        step = await self._step(repo)
        await repo.apply_report_to_step(step["id"], input_qty=5, output_qty=4, scrap_qty=1)
        row = await repo.get_step(1, 1)
        assert (row["input_qty"], row["output_qty"], row["scrap_qty"]) == (5, 4, 1)
        assert row["report_count"] == 1
        assert row["status"] == "in_progress", "报了工但没到计划量，应是在制"
        assert row["first_reported_at"] is not None

    async def test_second_report_accumulates(self, repo):
        """累计而不是覆盖 —— 分批报工是常态。"""
        step = await self._step(repo)
        await repo.apply_report_to_step(step["id"], output_qty=4)
        await repo.apply_report_to_step(step["id"], output_qty=3)
        row = await repo.get_step(1, 1)
        assert row["output_qty"] == 7
        assert row["report_count"] == 2

    async def test_completes_when_reaching_planned(self, repo):
        step = await self._step(repo)
        await repo.apply_report_to_step(step["id"], output_qty=10)
        assert (await repo.get_step(1, 1))["status"] == "completed"

    async def test_overshoot_also_completes(self, repo):
        step = await self._step(repo)
        await repo.apply_report_to_step(step["id"], output_qty=12)
        assert (await repo.get_step(1, 1))["status"] == "completed"

    async def test_zero_planned_never_completes(self, repo):
        """计划量为 0 时不判完工。

        计划量缺失是最常见的脏数据。按 `output >= planned` 照算的话，
        任何一次报工都会让工序立刻完工 —— 于是"待作业"里明明还有活却没了。
        """
        await repo.expand_steps_from_route(await repo.get_work_order(1))
        # ★ 先展开再改计划量：反过来的话此时表里还没有行，UPDATE 影响 0 行，
        #   用例看着是绿的却根本没构造出"计划量为 0"这个前提（空真）。
        changed = await repo.execute("UPDATE work_order_steps SET planned_qty = 0")
        assert changed == 2, "没改到工序行，前提没建立"
        step = await repo.get_step(1, 1)
        await repo.apply_report_to_step(step["id"], output_qty=99)
        assert (await repo.get_step(1, 1))["status"] == "in_progress"


class TestListWorkSteps:
    async def _prepare(self, repo):
        await repo.expand_steps_from_route(await repo.get_work_order(1))
        # 工序 1 开工在制、工序 2 完工
        await repo.apply_report_to_step((await repo.get_step(1, 1))["id"], output_qty=3)
        await repo.apply_report_to_step((await repo.get_step(1, 2))["id"], output_qty=10)

    async def test_open_scope_excludes_completed(self, repo):
        await self._prepare(repo)
        data = await repo.list_work_steps(scope="open")
        assert data["total"] == 1
        assert data["items"][0]["operation_code"] == "CW010"

    async def test_completed_scope(self, repo):
        await self._prepare(repo)
        data = await repo.list_work_steps(scope="completed")
        assert data["total"] == 1
        assert data["items"][0]["operation_code"] == "CW020"

    async def test_all_scope_returns_both(self, repo):
        await self._prepare(repo)
        assert (await repo.list_work_steps(scope="all"))["total"] == 2

    async def test_filter_by_work_center(self, repo):
        """按工作中心过滤是"工位任务台"的入口，必须真生效。"""
        await self._prepare(repo)
        data = await repo.list_work_steps(scope="all", work_center_id=11)
        assert data["total"] == 1
        assert data["items"][0]["wc_id"] == 11

    async def test_joins_order_and_work_center_names(self, repo):
        await self._prepare(repo)
        row = (await repo.list_work_steps(scope="all"))["items"][0]
        assert row["wo_no"] == "WO-1"
        assert row["product_name"] == "整机"
        assert row["wc_name"] in ("数控工位", "铣削工位")

    async def test_blocked_flag_follows_andon_status(self, repo):
        """未解决的安灯才算阻塞；已解决/已取消的不算。

        `NOT IN` 写反（写成 `IN`）会让所有"已解决"的单都标成阻塞 ——
        现场跑去看一个早就不存在的问题，几次之后就不再信这个标记。
        """
        await self._prepare(repo)
        # ★ `priority` 必须显式给：模型上是 `nullable=False, default="normal"`，
        #   但 `default=` 只是 **ORM 层**默认，裸 `text()` 的 INSERT 不会介入
        #   → 少这一列就是 NOT NULL 约束报错，而不是"用了默认值"。
        await repo.execute(
            "INSERT INTO andon_call (tenant_id, call_no, call_type, caller_id,"
            " description, priority, status, work_order_id) VALUES"
            " ('t', 'A-1', 'material', 1, '缺料', 'normal', 'open', 1),"
            " ('t', 'A-2', 'equipment', 1, '设备故障', 'normal', 'resolved', 1)")
        data = await repo.list_work_steps(scope="all")
        assert all(r["blocked"] is True for r in data["items"]), \
            "有未解决安灯时该工单所有工序都算阻塞"

        await repo.execute("UPDATE andon_call SET status = 'resolved'")
        data = await repo.list_work_steps(scope="all")
        assert all(r["blocked"] is False for r in data["items"])

    async def test_no_steps_returns_empty(self, repo):
        """没下达/没路线时返回空列表，不是报错。"""
        data = await repo.list_work_steps(scope="open")
        assert data["total"] == 0 and data["items"] == []
