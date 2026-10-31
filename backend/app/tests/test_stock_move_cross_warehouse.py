"""E-B1 跨仓调拨（台账 C-52）。

改造前 `POST /wms/inventory/stock-move` 只支持**同仓库位间移位**：目标行的
``warehouse_id`` 直接抄源仓的（``"warehouse_id": source["warehouse_id"]``）。

于是把货移到一个**属于别的仓库**的库位时，库存被记到**源仓名下**：
- 目标仓盘点看不到这批货（货在它地盘上，账在别人名下）；
- 源仓账面少了货却没人认领；
- 清单要的"双仓流水"根本无从谈起 —— 全程只有一条流水，且仓库字段是错的。

这不是"少一个字段"，是**账实不符**：两个仓库的账都对不上自己的地盘。

修：**目标仓库由目标库位解析**（库位归属仓库是权威事实，不是调用方说了算），
跨仓时写**两条流水**（源仓出、目标仓入，共用同一 ``voucher_no`` 以便配对）；
同仓移位仍只写一条（from/to 库位同行），保持既有口径不变。
"""
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.wms import (
    Batch, Inventory, InventoryTransaction, Material, Warehouse, WarehouseLocation,
)
from app.models.sync import ChangeLog
from app.repositories.wms_repo import InventoryRepository
from app.services.wms_service import InventoryService

TABLES = [
    Warehouse.__table__, WarehouseLocation.__table__, Material.__table__,
    Batch.__table__, Inventory.__table__, InventoryTransaction.__table__,
    # MultiTenantRepository.execute 会往 change_log 写一行，缺表会让 INSERT
    # 静默失败（异常被上层 try/except 吞掉）→ 测试"通过"却什么都没验。
    ChangeLog.__table__,
]

SRC_WH, TGT_WH = 1, 2
SRC_LOC, TGT_LOC = 11, 22


def _inv(id, warehouse_id, location_id, qty, locked=0, material_id=1, batch_id=None):
    return {"id": id, "tenant_id": "t", "material_id": material_id,
            "warehouse_id": warehouse_id, "location_id": location_id,
            "batch_id": batch_id, "batch_no": None,
            "quantity": qty, "locked_qty": locked, "unit": "个"}


async def _bundle(rows=()):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        await conn.execute(Warehouse.__table__.insert().values([
            {"id": SRC_WH, "tenant_id": "t", "code": "WH-A", "name": "源仓", "type": "raw"},
            {"id": TGT_WH, "tenant_id": "t", "code": "WH-B", "name": "目标仓", "type": "raw"},
        ]))
        await conn.execute(WarehouseLocation.__table__.insert().values([
            {"id": SRC_LOC, "tenant_id": "t", "warehouse_id": SRC_WH, "location_code": "A-01"},
            {"id": TGT_LOC, "tenant_id": "t", "warehouse_id": TGT_WH, "location_code": "B-01"},
        ]))
        await conn.execute(Material.__table__.insert().values(
            {"id": 1, "tenant_id": "t", "code": "M-1", "name": "料", "unit": "个",
             "is_active": True}))
        if rows:
            await conn.execute(Inventory.__table__.insert().values(list(rows)))
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
        repo = InventoryRepository(self.s)
        repo.set_tenant_id(self.tenant)
        self.svc = InventoryService(repo)
        self.repo = repo
        return self

    async def __aexit__(self, *exc):
        await self.bundle.session_ctx.__aexit__(*exc)
        await self.bundle.engine.dispose()

    async def move(self, qty, src=SRC_LOC, tgt=TGT_LOC, **kw):
        return await self.svc.stock_move(self.tenant, {
            "source_location_id": src, "target_location_id": tgt,
            "material_id": 1, "quantity": qty, "unit": "个", **kw})

    async def inv(self):
        return await self.repo.query(
            "SELECT * FROM inventory ORDER BY id")

    async def txs(self):
        return await self.repo.query(
            "SELECT * FROM inventory_transactions ORDER BY id")


# ==================== 1. 核心：目标仓库不能抄源仓 ====================

async def test_cross_warehouse_target_uses_target_warehouse():
    """跨仓时目标库存必须落在**目标库位所属仓库**，不是源仓。"""
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        res = await h.move(30)
        assert res["cross_warehouse"] is True
        assert res["target_warehouse_id"] == TGT_WH
        rows = await h.inv()
        tgt = next(r for r in rows if r["location_id"] == TGT_LOC)
        assert tgt["warehouse_id"] == TGT_WH, (
            f"目标库存被记到源仓名下（warehouse_id={tgt['warehouse_id']}）—— "
            "目标仓盘点看不到这批货")
        assert abs(tgt["quantity"] - 30) < 0.001


async def test_source_warehouse_decreased():
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        await h.move(30)
        src = next(r for r in await h.inv() if r["location_id"] == SRC_LOC)
        assert abs(src["quantity"] - 70) < 0.001


# ==================== 2. 双仓流水 ====================

async def test_cross_warehouse_writes_two_transactions():
    """跨仓要写两条流水（源仓出 + 目标仓入），否则两仓账都对不上。"""
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        res = await h.move(30)
        txs = await h.txs()
        assert len(txs) == 2, f"跨仓只有 {len(txs)} 条流水"
        whs = sorted(t["warehouse_id"] for t in txs)
        assert whs == [SRC_WH, TGT_WH], f"流水仓库不对：{whs}"
        # 同一凭证号配对
        assert txs[0]["voucher_no"] == txs[1]["voucher_no"] == res["voucher_no"]
        out_row = next(t for t in txs if t["warehouse_id"] == SRC_WH)
        in_row = next(t for t in txs if t["warehouse_id"] == TGT_WH)
        assert out_row["from_location_id"] == SRC_LOC and out_row["to_location_id"] is None
        assert in_row["to_location_id"] == TGT_LOC and in_row["from_location_id"] is None
        assert abs(out_row["quantity"] - 30) < 0.001 and abs(in_row["quantity"] - 30) < 0.001


async def test_same_warehouse_still_writes_one_transaction():
    """同仓移位口径不变：一条流水，from/to 库位同行。"""
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        # 目标库位同仓
        await h.s.execute(WarehouseLocation.__table__.insert().values(
            {"id": 12, "tenant_id": "t", "warehouse_id": SRC_WH, "location_code": "A-02"}))
        await h.s.commit()
        res = await h.move(30, tgt=12)
        assert res["cross_warehouse"] is False
        txs = await h.txs()
        assert len(txs) == 1
        assert txs[0]["from_location_id"] == SRC_LOC and txs[0]["to_location_id"] == 12


# ==================== 3. 校验 ====================

async def test_insufficient_available_rejected():
    """锁定量要算进可用量，不能只看着存量 100 就放行 90。"""
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100, locked=40)])
    async with Harness(b) as h:
        try:
            await h.move(90)
        except ValueError as e:
            assert "可用库存不足" in str(e)
        else:
            raise AssertionError("锁定量没被扣，超发成功")


async def test_same_location_rejected():
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        try:
            await h.move(10, src=SRC_LOC, tgt=SRC_LOC)
        except ValueError:
            pass
        else:
            raise AssertionError("同库位自移未被拦住")


async def test_unknown_target_location_rejected():
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        try:
            await h.move(10, tgt=999)
        except ValueError as e:
            assert "不存在" in str(e)
        else:
            raise AssertionError("目标库位不存在却移成功了")


async def test_mismatched_target_warehouse_rejected():
    """显式传的 target_warehouse_id 与库位实际归属不符 → 拒，不静默按错的走。"""
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100)])
    async with Harness(b) as h:
        try:
            await h.move(10, target_warehouse_id=SRC_WH)  # 库位在 TGT_WH
        except ValueError as e:
            assert "不属于" in str(e)
        else:
            raise AssertionError("目标仓库与库位归属矛盾却放行了")


async def test_batch_no_follows_source_when_not_given():
    """没传批号时沿用源库存行的批号——调拨不能把批号弄丢（丢了追溯就断）。"""
    b = await _bundle(rows=[_inv(1, SRC_WH, SRC_LOC, 100, batch_id=7)])
    async with Harness(b) as h:
        await h.s.execute(Batch.__table__.insert().values(
            {"id": 7, "tenant_id": "t", "batch_no": "B-7", "material_id": 1}))
        await h.s.commit()
        await h.move(30)
        tgt = next(r for r in await h.inv() if r["location_id"] == TGT_LOC)
        assert tgt["batch_id"] == 7
        txs = await h.txs()
        assert all(t["batch_id"] == 7 for t in txs), "流水丢了批次"
