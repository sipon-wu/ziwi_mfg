"""E-S4 盘点 → 差异 → 调整（台账 C-56）。

真实 HTTP 复核（``e2e/wms_receipt_count_e2e.py``）在这一格里连撞**五处**缺陷，
且后一处只在前一处修好后才暴露 —— 典型"叠罗汉"：

1. ``InventoryCountRepository.create`` 的固定列 INSERT 含 ``counted_items`` /
   ``diff_items``，而 Service 只给了 ``total_items`` → 建盘点单**从上线起 100%
   500**（``A value is required for bind parameter 'counted_items'``）。
2. ``inventory_count_items`` 表**根本没有 ``tenant_id`` 列**，而它的 Repo 继承
   ``MultiTenantRepository`` → SELECT 自动拼 ``ci.tenant_id = ...`` → 读明细
   100% ``no such column``。建单却返回 200，看起来像"建成功只是读不出来"。
   同形态还有 ``material_request_items`` / ``approval_nodes``（均 0 行，坑没轮到踩）。
3. ``InventoryCountItemRepository.create`` 同样漏列（``batch_no`` / ``count_qty``
   / ``diff_qty`` ...），修好 1 之后立刻炸在这里。
4. ``adjust`` 里盘盈分支写成 ``inv_repo.stock_in(...)`` **没有 await** → 协程从未
   被调度：接口返回成功、流水记了 +N，**库存一个数没加**。
   **账实不符比不生效更糟** —— 流水说加了，库存没加，对账时两侧都查不出所以然。
   盘亏分支有 await，所以只有盘盈静默失效，更难被发现。
5. 盘亏用 ``find_one(..., batch_id=None)`` → 额外拼 ``batch_id IS NULL`` →
   带批次的库存行永远匹配不到 → 盘亏静默跳过（与 C-52 移位同一坑）。

外加一条业务口径补上：场景要求「差异原因必填」，此前不填也能录。
"""
import pytest
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.wms import (
    Inventory, InventoryCount, InventoryCountItem, InventoryTransaction,
    Material, Warehouse, WarehouseLocation,
)
from app.models.sync import ChangeLog
from app.repositories.wms_repo import (
    InventoryCountItemRepository, InventoryCountRepository, InventoryRepository,
    InventoryTransactionRepository,
)
from app.services.wms_service import InventoryCountService

TABLES = [
    Warehouse.__table__, WarehouseLocation.__table__, Material.__table__,
    Inventory.__table__, InventoryTransaction.__table__,
    InventoryCount.__table__, InventoryCountItem.__table__,
    ChangeLog.__table__,
]

WH, LOC = 1, 11
MAT = 1


async def _bundle(inv_rows=()):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        await conn.execute(Warehouse.__table__.insert().values(
            {"id": WH, "tenant_id": "t", "code": "W1", "name": "仓", "type": "raw"}))
        await conn.execute(WarehouseLocation.__table__.insert().values(
            {"id": LOC, "tenant_id": "t", "warehouse_id": WH, "location_code": "L-01"}))
        await conn.execute(Material.__table__.insert().values(
            {"id": MAT, "tenant_id": "t", "code": "M1", "name": "料", "unit": "个",
             "is_active": True}))
        if inv_rows:
            await conn.execute(Inventory.__table__.insert().values(list(inv_rows)))
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
        repo = InventoryCountRepository(self.s)
        repo.set_tenant_id(self.tenant)
        item_repo = InventoryCountItemRepository(self.s).inherit_context_from(repo)
        self.svc = InventoryCountService(repo, item_repo)
        self.item_repo = item_repo
        self.inv_repo = InventoryRepository(self.s).inherit_context_from(repo)
        self.tx_repo = InventoryTransactionRepository(self.s).inherit_context_from(repo)
        return self

    async def __aexit__(self, *exc):
        await self.bundle.session_ctx.__aexit__(*exc)
        await self.bundle.engine.dispose()

    async def new_count(self, system_qty=100.0, location_id=LOC, batch_no=None):
        cid = (await self.svc.create({
            "tenant_id": self.tenant, "count_no": "CN-1", "count_type": "cycle",
            "warehouse_id": WH, "count_date": "2026-10-31",
            "items": [{"material_id": MAT, "location_id": location_id,
                       "batch_no": batch_no, "system_qty": system_qty}],
        }))["id"]
        items = await self.item_repo.list_by_count(cid)
        return cid, items[0]["id"]

    async def qty(self):
        rows = await self.inv_repo.query("SELECT * FROM inventory")
        return sum(float(r["quantity"] or 0) for r in rows)

    async def txs(self):
        return await self.tx_repo.query("SELECT * FROM inventory_transactions")


# ==================== 1. 建单不再 500（固定列 INSERT 漏列） ====================

async def test_create_count_no_longer_500():
    """建盘点单必须成功 —— 此前 counted_items/diff_items 缺绑定参数直接 500。"""
    b = await _bundle()
    async with Harness(b) as h:
        cid, _ = await h.new_count()
        assert cid
        row = await h.svc.get(cid)
        assert row["counted_items"] == 0
        assert row["diff_items"] == 0
        assert row["total_items"] == 1


async def test_count_item_carries_tenant_id():
    """明细必须带 tenant_id —— 缺列时基类的 SELECT 注入会 no such column。"""
    b = await _bundle()
    async with Harness(b) as h:
        cid, _ = await h.new_count()
        items = await h.item_repo.list_by_count(cid)   # 此前这一句就 500
        assert len(items) == 1
        assert items[0]["tenant_id"] == "t"
        assert items[0]["status"] == "pending"


# ==================== 2. 差异原因必填 ====================

async def test_record_without_reason_rejected_when_diff():
    """有差异却不填原因 → 必须拒。盘盈盘亏要进损益，说不清原因的调整无从复盘。"""
    b = await _bundle()
    async with Harness(b) as h:
        _, iid = await h.new_count(system_qty=100.0)
        with pytest.raises(ValueError, match="差异原因"):
            await h.svc.record_count(iid, {"count_qty": 90.0})


async def test_record_without_reason_allowed_when_no_diff():
    """无差异的行不该逼人编理由。"""
    b = await _bundle()
    async with Harness(b) as h:
        _, iid = await h.new_count(system_qty=100.0)
        res = await h.svc.record_count(iid, {"count_qty": 100.0})
        assert res["diff_qty"] == 0


async def test_record_computes_diff_and_persists_reason():
    b = await _bundle()
    async with Harness(b) as h:
        _, iid = await h.new_count(system_qty=100.0)
        res = await h.svc.record_count(
            iid, {"count_qty": 92.0, "diff_reason": "破损丢失"})
        assert abs(res["diff_qty"] + 8.0) < 0.001
        item = await h.item_repo.get(iid)
        assert item["diff_reason"] == "破损丢失"
        assert item["status"] == "counted"


# ==================== 3. 盘盈必须真的加库存（await 缺失） ====================

async def test_adjust_gain_really_increases_inventory():
    """★核心：盘盈必须落到库存上。此前 stock_in 没 await，流水记了库存没动。"""
    b = await _bundle(inv_rows=[{
        "id": 1, "tenant_id": "t", "material_id": MAT, "warehouse_id": WH,
        "location_id": LOC, "quantity": 100.0, "locked_qty": 0.0, "unit": "个"}])
    async with Harness(b) as h:
        cid, iid = await h.new_count(system_qty=100.0)
        await h.svc.record_count(iid, {"count_qty": 115.0, "diff_reason": "盘盈"})
        await h.svc.update(cid, {"status": "completed"})

        before = await h.qty()
        res = await h.svc.adjust(cid, h.tenant)
        after = await h.qty()

        assert res["adjusted_count"] == 1
        assert abs((after - before) - 15.0) < 0.001, (
            f"盘盈 15 但库存只动了 {after - before} —— stock_in 未被 await")


async def test_adjust_loss_really_decreases_inventory():
    b = await _bundle(inv_rows=[{
        "id": 1, "tenant_id": "t", "material_id": MAT, "warehouse_id": WH,
        "location_id": LOC, "quantity": 100.0, "locked_qty": 0.0, "unit": "个"}])
    async with Harness(b) as h:
        cid, iid = await h.new_count(system_qty=100.0)
        await h.svc.record_count(iid, {"count_qty": 88.0, "diff_reason": "盘亏"})
        await h.svc.update(cid, {"status": "completed"})

        before = await h.qty()
        await h.svc.adjust(cid, h.tenant)
        assert abs((before - await h.qty()) - 12.0) < 0.001


async def test_adjust_loss_hits_batch_managed_stock():
    """带批次的库存行也必须能扣 —— find_one(batch_id=None) 会拼
    `batch_id IS NULL` 而永远匹配不到（与 C-52 移位同一坑）。"""
    b = await _bundle(inv_rows=[{
        "id": 1, "tenant_id": "t", "material_id": MAT, "warehouse_id": WH,
        "location_id": LOC, "batch_id": 9, "batch_no": "B-9",
        "quantity": 100.0, "locked_qty": 0.0, "unit": "个"}])
    async with Harness(b) as h:
        cid, iid = await h.new_count(system_qty=100.0, batch_no="B-9")
        await h.svc.record_count(iid, {"count_qty": 95.0, "diff_reason": "盘亏"})
        await h.svc.update(cid, {"status": "completed"})

        res = await h.svc.adjust(cid, h.tenant)
        assert not res.get("skipped"), f"带批次库存被静默跳过：{res}"
        assert abs(await h.qty() - 95.0) < 0.001


async def test_adjust_reports_skipped_instead_of_swallowing():
    """没有库存行时不能装作调平了 —— 必须回传 skipped 让调用方看得见。"""
    b = await _bundle()
    async with Harness(b) as h:
        cid, iid = await h.new_count(system_qty=100.0)
        await h.svc.record_count(iid, {"count_qty": 80.0, "diff_reason": "盘亏"})
        await h.svc.update(cid, {"status": "completed"})

        res = await h.svc.adjust(cid, h.tenant)
        assert res.get("skipped"), "没库存行却没回传 skipped，等于静默吞掉盘亏"


# ==================== 4. 流水与闸门 ====================

async def test_adjust_writes_transaction():
    b = await _bundle(inv_rows=[{
        "id": 1, "tenant_id": "t", "material_id": MAT, "warehouse_id": WH,
        "location_id": LOC, "quantity": 100.0, "locked_qty": 0.0, "unit": "个"}])
    async with Harness(b) as h:
        cid, iid = await h.new_count(system_qty=100.0)
        await h.svc.record_count(iid, {"count_qty": 110.0, "diff_reason": "盘盈"})
        await h.svc.update(cid, {"status": "completed"})
        await h.svc.adjust(cid, h.tenant)

        txs = await h.txs()
        assert len(txs) == 1
        assert txs[0]["transaction_type"] == "adjust"
        assert txs[0]["voucher_no"] == "CN-1"
        # 盘盈记"入到哪"，追溯时才看得出方向
        assert txs[0]["to_location_id"] == LOC
        assert txs[0]["from_location_id"] is None


async def test_adjust_requires_completed():
    b = await _bundle()
    async with Harness(b) as h:
        cid, _ = await h.new_count()
        with pytest.raises(ValueError, match="已完成"):
            await h.svc.adjust(cid, h.tenant)
