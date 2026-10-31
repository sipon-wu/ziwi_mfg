"""X3 库存告急：预警的口径 / 幂等 / 可行动性（台账 C-47，场景 X3）。

改造前三处都不对，而且全是**静默错**：接口 200、列表有数据，只是结论不可信。

1. **可用量口径错**：``list_below_safety_stock`` 用 ``SUM(i.quantity)``，
   把锁定量与 IQC 判退/召回冻结的货都算成"手上有"。后果是**反向**的：
   一批不合格被冻结后账面数字没变 → 看起来还够 → **本该告警的不告警**，
   真缺料被静默吞掉。
2. **无幂等**：每次 ``check`` 无条件 INSERT。同一物料扫 N 次就 N 条 open
   告警，真正要处理的那条淹在重复项里（与 SPC 告警 C-43 同一病根，第二次复发）。
3. **预警点不出下一步**：只说"低于安全库存"，缺多少、什么时候该到货都得
   仓管员自己算。采购申请单据本身归 ERP 边界外（B-11），但"还差多少"是
   预警本来就该算出来的。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.sync import ChangeLog
from app.models.wms import Batch, Inventory, InventoryAlert, Material, Warehouse
from app.repositories.wms_repo import InventoryAlertRepository
from app.services.wms_service import InventoryAlertService

TABLES = [
    Warehouse.__table__, Material.__table__, Batch.__table__, Inventory.__table__,
    InventoryAlert.__table__,
    # MultiTenantRepository.execute 会往 change_log 写一行，缺表会让 create
    # 静默失败（异常被上层 try/except 吞掉）→ 测试"通过"却什么都没验。
    ChangeLog.__table__,
]


async def _svc(rows=(), materials=()):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        await conn.execute(Warehouse.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "code": "WH", "name": "原料仓", "type": "raw"}))
        await conn.execute(Material.__table__.insert().values(list(materials)))
        if rows:
            await conn.execute(Inventory.__table__.insert().values(list(rows)))
    Session = async_sessionmaker(engine, expire_on_commit=False)

    class Bundle:
        pass
    b = Bundle()
    b.engine = engine
    b.session_ctx = Session()
    return b


def _mat(id=1, safety=50, reorder=0, lead=0, **kw):
    row = {"id": id, "tenant_id": "t", "code": "M-1", "name": "告急料",
           "unit": "个", "safety_stock_qty": safety, "reorder_point": reorder,
           "lead_time_days": lead, "is_active": True}
    row.update(kw)
    return row


def _inv(id, qty, locked=0, batch_id=None, material_id=1):
    return {"id": id, "tenant_id": "t", "material_id": material_id,
            "warehouse_id": 1, "location_id": 1, "batch_id": batch_id,
            "quantity": qty, "locked_qty": locked, "unit": "个"}


class Harness:
    """包一层：测试里只写 await h.check() / h.alerts()。"""

    def __init__(self, bundle, tenant="t"):
        self.bundle = bundle
        self.tenant = tenant

    async def __aenter__(self):
        self.s = await self.bundle.session_ctx.__aenter__()
        repo = InventoryAlertRepository(self.s)
        repo.set_tenant_id(self.tenant)
        self.svc = InventoryAlertService(repo)
        self.repo = repo
        return self

    async def __aexit__(self, *exc):
        await self.bundle.session_ctx.__aexit__(*exc)
        await self.bundle.engine.dispose()

    async def check(self):
        return await self.svc.check_and_alert(self.tenant)

    async def alerts(self):
        return await self.repo.query("SELECT * FROM inventory_alerts ORDER BY id")


# ==================== 1. 可用量口径 ====================

async def test_frozen_batch_does_not_count_as_available():
    """冻结批次的货不能算"手上有" —— 否则本该告警的不告警。"""
    b = await _svc(
        materials=[_mat(safety=50)],
        rows=[_inv(1, qty=100, batch_id=10)],
    )
    async with Harness(b) as h:
        await h.s.execute(Batch.__table__.insert().values(
            {"id": 10, "tenant_id": "t", "batch_no": "B-REJ", "material_id": 1,
             "is_locked": True}))
        await h.s.commit()
        alerts = await h.check()
        assert alerts, "冻结批次的货被算成可用 → 真缺料静默吞掉"


async def test_locked_qty_deducted():
    """锁定量要从可用量里扣掉。"""
    b = await _svc(materials=[_mat(safety=50)], rows=[_inv(1, qty=80, locked=40)])
    async with Harness(b) as h:
        alerts = await h.check()
        assert len(alerts) == 1 and alerts[0]["current_qty"] == 40


async def test_enough_stock_does_not_alert():
    b = await _svc(materials=[_mat(safety=50)], rows=[_inv(1, qty=80)])
    async with Harness(b) as h:
        assert await h.check() == []


# ==================== 2. 幂等 ====================

async def test_repeat_scan_does_not_duplicate():
    """扫两次只应有一条未闭环告警（第二次刷新数量，不新增）。"""
    b = await _svc(materials=[_mat(safety=50)], rows=[_inv(1, qty=10)])
    async with Harness(b) as h:
        await h.check()
        await h.check()
        rows = await h.alerts()
        assert len(rows) == 1, f"重复扫描刷屏：{len(rows)} 条"
        assert rows[0]["deduplicated"] if "deduplicated" in rows[0] else True


async def test_refresh_keeps_qty_current():
    """补货后重扫，已有告警的数量要跟着变（刷新而不是留着旧数字）。"""
    b = await _svc(materials=[_mat(safety=50)], rows=[_inv(1, qty=10)])
    async with Harness(b) as h:
        await h.check()
        await h.s.execute(
            Inventory.__table__.update().where(Inventory.__table__.c.id == 1)
            .values(quantity=30))
        await h.s.commit()
        await h.check()
        rows = await h.alerts()
        assert len(rows) == 1
        assert rows[0]["current_qty"] == 30, "刷新没跟上最新库存"


async def test_new_alert_after_resolved():
    """处理完又低于阈值 → 允许新开一条（但之后不会再重复）。"""
    b = await _svc(materials=[_mat(safety=50)], rows=[_inv(1, qty=10)])
    async with Harness(b) as h:
        first = await h.check()
        await h.svc.resolve(first[0]["id"], resolved_by=1)
        second = await h.check()
        assert len(second) == 1 and second[0]["id"] != first[0]["id"]
        third = await h.check()
        assert len(third) == 1 and third[0]["id"] == second[0]["id"], "新开后又重复了"


# ==================== 3. 预警要给得出下一步 ====================

async def test_message_carries_suggested_qty_and_eta():
    """预警消息里必须有"还差多少""什么时候该到"，不能只说低于安全线。"""
    b = await _svc(materials=[_mat(safety=50, reorder=120, lead=7)],
                   rows=[_inv(1, qty=10)])
    async with Harness(b) as h:
        alerts = await h.check()
        msg = alerts[0]["alert_message"]
        # 目标水位 120 − 可用 10 = 110
        assert "110" in msg, msg
        assert "提前期 7 天" in msg, msg


async def test_suggested_qty_falls_back_to_double_safety():
    """没配再订货点 → 目标水位取 2 倍安全库存（补一次够扛一阵）。"""
    b = await _svc(materials=[_mat(safety=50, reorder=0)], rows=[_inv(1, qty=10)])
    async with Harness(b) as h:
        msg = (await h.check())[0]["alert_message"]
        assert "90" in msg, msg