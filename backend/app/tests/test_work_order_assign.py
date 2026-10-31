"""C-S2 工单派工：入口 + 校验 + 留痕（台账 C-50）。

改造前派工这条链断在两处，且是**"列在、入口不在"**这种最难看出来的形态：

1. ``work_orders.assignee_id`` 列一直在，但 ``CreateWorkOrderRequest`` /
   ``UpdateWorkOrderRequest`` 都没有它，也没有任何派工端点 —— 派工只能直接
   改库。更隐蔽的是 ``create_work_order`` 的 INSERT 是**固定列清单**，
   就算把字段加到 schema 上也写不进去（与 C-48 的 ``energy_alert.status``
   同一病根：模型的 Python 侧默认值救不了裸 SQL）。
2. **班组维度连列都没有**。组织树里有 ``org_type='team'``，却没有地方挂到
   工单上，于是"派给班组"只能退化成"派给班组里的某个人"，班组作为接单主体
   这件事在系统里不存在。

修：补 ``assigned_org_id`` 列 + ``POST /work-orders/{id}/assign`` +
``GET /work-orders/{id}/assignments``。派工留痕进通用表 ``entity_status_logs``
（``action='assign'``）——决策流看板与精益体检都以它为单一数据源，另建一张
派工表等于让这两处永远看不到派工轨迹。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.organization import Organization
from app.models.production import WorkOrder
from app.models.status_log import EntityStatusLog
from app.models.sync import ChangeLog
from app.models.user import User
from app.repositories.production_repo import ProductionRepository
from app.services.production_service import ProductionService
from fastapi import HTTPException

TABLES = [
    WorkOrder.__table__, User.__table__, Organization.__table__,
    EntityStatusLog.__table__,
    # MultiTenantRepository.execute 会往 change_log 写一行，缺表会让 INSERT
    # 静默失败（异常被上层 try/except 吞掉）→ 测试"通过"却什么都没验。
    ChangeLog.__table__,
]


def _wo(id=1, status="released", **kw):
    row = {"id": id, "tenant_id": "t", "wo_no": f"WO-{id}", "wo_type": "production",
           "wo_status": status, "product_code": "P-1", "product_name": "件",
           "planned_qty": 10, "assignee_id": None, "assigned_org_id": None}
    row.update(kw)
    return row


def _user(id, name):
    return {"id": id, "tenant_id": "t", "username": name,
            "password_hash": "x", "real_name": name}


def _org(id, code, org_type="team"):
    return {"id": id, "tenant_id": "t", "code": code, "name": code,
            "org_type": org_type, "path": f"/{code}"}


async def _bundle(orders=(), users=(), orgs=()):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        for table, rows in ((WorkOrder, orders), (User, users), (Organization, orgs)):
            if rows:
                await conn.execute(table.__table__.insert().values(list(rows)))
    Session = async_sessionmaker(engine, expire_on_commit=False)

    class Bundle:
        pass
    b = Bundle()
    b.engine = engine
    b.session_ctx = Session()
    return b


class Harness:
    def __init__(self, bundle, tenant="t"):
        self.bundle = bundle
        self.tenant = tenant

    async def __aenter__(self):
        self.s = await self.bundle.session_ctx.__aenter__()
        repo = ProductionRepository(self.s)
        repo.set_tenant_id(self.tenant)
        self.svc = ProductionService(repo)
        self.repo = repo
        return self

    async def __aexit__(self, *exc):
        await self.bundle.session_ctx.__aexit__(*exc)
        await self.bundle.engine.dispose()

    async def assign(self, order_id=1, **kw):
        return await self.svc.assign_work_order(order_id, actor_id=99, **kw)

    async def wo(self, id=1):
        return await self.repo.get_work_order(id)

    async def logs(self, id=1):
        return await self.svc.list_assignments(id)


# ==================== 1. 派工要真的写进去 ====================

async def test_assign_to_person_persists():
    """最基础的一条：派了之后工单上的 assignee_id 得变。"""
    b = await _bundle(orders=[_wo()], users=[_user(7, "张三")])
    async with Harness(b) as h:
        res = await h.assign(assignee_id=7)
        assert res["assignee_id"] == 7
        assert res["assignee_name"] == "张三"
        assert (await h.wo())["assignee_id"] == 7, "接口回了 200 但没落库"


async def test_assign_to_team_persists():
    b = await _bundle(orders=[_wo()], orgs=[_org(3, "WS1-A", "team")])
    async with Harness(b) as h:
        await h.assign(assigned_org_id=3)
        assert (await h.wo())["assigned_org_id"] == 3


async def test_assign_both_person_and_team():
    b = await _bundle(orders=[_wo()], users=[_user(7, "张三")],
                      orgs=[_org(3, "WS1-A")])
    async with Harness(b) as h:
        await h.assign(assignee_id=7, assigned_org_id=3)
        wo = await h.wo()
        assert wo["assignee_id"] == 7 and wo["assigned_org_id"] == 3


# ==================== 2. 校验（不然是静默错） ====================

async def test_assign_requires_target():
    """两个都不给 → 400，不能"派了个空"。"""
    b = await _bundle(orders=[_wo()])
    async with Harness(b) as h:
        try:
            await h.assign()
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError("未指定派工对象却成功了")


async def test_unknown_assignee_rejected():
    """派给不存在的人必须被拒：否则界面上负责人一栏空白，还以为派成功了。"""
    b = await _bundle(orders=[_wo()])
    async with Harness(b) as h:
        try:
            await h.assign(assignee_id=404)
        except HTTPException as e:
            assert e.status_code == 400 and "不存在" in str(e.detail)
        else:
            raise AssertionError("派给了不存在的用户")


async def test_assignee_from_other_tenant_rejected():
    """跨租户 id 必须被拒（租户隔离不能被一个 id 绕过）。"""
    b = await _bundle(orders=[_wo()], users=[_user(7, "别人")])
    async with Harness(b) as h:
        await h.s.execute(User.__table__.insert().values(
            {"id": 8, "tenant_id": "other", "username": "o", "password_hash": "x"}))
        await h.s.commit()
        try:
            await h.assign(assignee_id=8)
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError("跨租户派工未被拦住")


async def test_closed_order_cannot_be_assigned():
    b = await _bundle(orders=[_wo(status="closed")], users=[_user(7, "张三")])
    async with Harness(b) as h:
        try:
            await h.assign(assignee_id=7)
        except HTTPException as e:
            assert e.status_code == 400
        else:
            raise AssertionError("已关闭工单还能派工")


async def test_missing_order_is_404():
    b = await _bundle(users=[_user(7, "张三")])
    async with Harness(b) as h:
        try:
            await h.assign(order_id=999, assignee_id=7)
        except HTTPException as e:
            assert e.status_code == 404
        else:
            raise AssertionError("不存在的工单派工成功了")


# ==================== 3. 留痕 ====================

async def test_assign_writes_status_log():
    b = await _bundle(orders=[_wo()], users=[_user(7, "张三")])
    async with Harness(b) as h:
        await h.assign(assignee_id=7, remark="E2E 派工")
        logs = await h.logs()
        assert len(logs) == 1
        log = logs[0]
        assert log["action"] == "assign"
        assert log["entity_type"] == "work_order"
        assert log["actor_id"] == 99
        assert log["reason"] == "E2E 派工"
        assert log["extra"]["assignee_id"] == 7


async def test_reassign_records_previous_assignee():
    """改派要能看出"原来是谁"——否则扯皮时无从追溯。"""
    b = await _bundle(orders=[_wo(assignee_id=7)],
                      users=[_user(7, "张三"), _user(8, "李四")])
    async with Harness(b) as h:
        res = await h.assign(assignee_id=8)
        assert res["previous_assignee_id"] == 7
        logs = await h.logs()
        assert len(logs) == 1
        assert logs[0]["extra"]["previous_assignee_id"] == 7


async def test_multiple_assignments_kept_in_order():
    b = await _bundle(orders=[_wo()],
                      users=[_user(7, "张三"), _user(8, "李四")])
    async with Harness(b) as h:
        await h.assign(assignee_id=7)
        await h.assign(assignee_id=8)
        logs = await h.logs()
        assert len(logs) == 2
        assert [l["extra"]["assignee_id"] for l in logs] == [7, 8]


# ==================== 4. 建单即指定负责人要真的落库 ====================

async def test_create_with_assignee_writes_column():
    """固定列 INSERT 的漏列陷阱：schema 暴露了字段，SQL 却没写进去。"""
    b = await _bundle()
    async with Harness(b) as h:
        # 字段要齐全：INSERT 是固定列清单，缺任何绑定参数都会运行期报错。
        # 真实链路走 CreateWorkOrderRequest，缺失项由 schema 默认值补齐。
        wo_id = await h.repo.create_work_order({
            "tenant_id": "t", "wo_no": "WO-NEW", "wo_type": "production",
            "product_code": "P-1", "product_name": "件", "planned_qty": 5,
            "priority": 0, "scheduled_start_at": None, "scheduled_end_at": None,
            "workshop": None, "line_code": None, "remark": None,
            "assignee_id": 7, "assigned_org_id": 3})
        wo = await h.repo.get_work_order(wo_id)
        assert wo["assignee_id"] == 7, "建单传了 assignee_id 却没落库"
        assert wo["assigned_org_id"] == 3
