"""物料拣选策略 `pick_strategy` 落库与消费（台账 C-57）。

C-56 之后做了一次全库扫描：把「模型上有 Python 侧 ``default=``、但裸 SQL INSERT
没写进列清单」的列全列出来，再拿库里 NULL 行数去验（不靠读代码猜）。撞出一处实锤：

    materials.pick_strategy：78 行里 69 行是 NULL

模型写的是 ``default="fifo"`` —— 但 ORM 侧的默认值裸 SQL 永远看不到，
``MaterialRepository.create`` 的列清单里也没有这一列，于是落 NULL。

**后果不是"字段显示为空"，是拣货顺序被静默反转**：

    pick_strategy = material.get("pick_strategy", "fifo")   # 键在、值为 None
    order_dir = "ASC" if pick_strategy == "fifo" else "DESC"

``dict.get`` 的默认值只在**键不存在**时生效；键在而值是 NULL 时返回 ``None``，
``None != "fifo"`` → 走 DESC → **FIFO 变 LIFO**：最老的批次一直压在库里。
对有保质期的物料这直接意味着呆滞与过期。接口照样 200、拣选照样成功，
只是顺序反了 —— 没人会去查排序方向。

两处都修：
- 写入侧：``MaterialRepository.create`` 显式兜 ``pick_strategy='fifo'``（顺带把其它
  有默认值的列一并兜住，同一形态不再逐个踩）。
- 读侧：``IssueOrderService`` 用 ``or "fifo"``，NULL 与缺键都兜住 —— 存量 NULL
  在回填迁移跑之前也不该反转策略。
- 存量：迁移 ``20261031_material_pick_strategy.py`` 回填 69 行（填的是模型声明的
  默认值，不是编造；已有显式值一律不动）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.production import WorkOrder
from app.models.wms import (
    Batch, Inventory, InventoryTransaction, IssueOrder, IssueOrderItem,
    Material, ReceiptOrder, ReceiptOrderItem, Warehouse,
)
from app.models.sync import ChangeLog
from app.repositories.wms_repo import (
    InventoryRepository, InventoryTransactionRepository, IssueOrderItemRepository,
    IssueOrderRepository, MaterialRepository,
)
from app.services.wms_service import IssueOrderService

TABLES = [
    Warehouse.__table__, Material.__table__, Batch.__table__, Inventory.__table__,
    InventoryTransaction.__table__, IssueOrder.__table__, IssueOrderItem.__table__,
    ReceiptOrder.__table__, ReceiptOrderItem.__table__, WorkOrder.__table__,
    ChangeLog.__table__,
]

SEED = [
    "INSERT INTO warehouses (id, tenant_id, code, name, type) "
    "VALUES (1, 't', 'WH-RAW', '原料仓', 'raw')",
    # ★ pick_strategy 为 NULL：这就是库里 69/78 行的真实形态
    "INSERT INTO materials (id, tenant_id, code, name, unit, pick_strategy) "
    "VALUES (1, 't', 'RM-1', '原料一', 'PCS', NULL)",
    # 批次 10 更早、11 更晚 —— FIFO 必须先出 10
    "INSERT INTO batches (id, tenant_id, batch_no, material_id, is_locked, status,"
    " created_at) VALUES "
    "(10, 't', 'RM-OLD', 1, 0, 'active', '2026-01-01 00:00:00'), "
    "(11, 't', 'RM-NEW', 1, 0, 'active', '2026-06-01 00:00:00')",
    "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id, location_id,"
    " batch_id, batch_no, quantity, locked_qty, unit) VALUES "
    "(1, 't', 1, 1, 901, 10, 'RM-OLD', 100, 0, 'PCS'), "
    "(2, 't', 1, 1, 902, 11, 'RM-NEW', 100, 0, 'PCS')",
    "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, source_type,"
    " source_doc_no, work_order_id, warehouse_id, status) VALUES "
    "(1, 't', 'ISO-1', 'production', 'wo', 'WO-1', 1, 1, 'pending')",
    "INSERT INTO issue_order_items (id, tenant_id, issue_id, line_no, material_id,"
    " required_qty, issued_qty, unit) VALUES (1, 't', 1, 1, 1, 10, 0, 'PCS')",
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name, wo_status)"
    " VALUES (1, 't', 'WO-1', 'FG-1', '成品一', 'completed')",
]


async def _session():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        for ddl in SEED:
            await conn.execute(text(ddl))
    return engine, async_sessionmaker(engine, expire_on_commit=False)


def _svc(s):
    def r(cls):
        repo = cls(s)
        repo.set_tenant_id("t")
        return repo
    return IssueOrderService(
        r(IssueOrderRepository), r(IssueOrderItemRepository),
        r(InventoryRepository), r(InventoryTransactionRepository))


# ==================== 1. 写入侧：默认值必须真的落库 ====================

async def test_create_material_defaults_pick_strategy():
    """调用方不给 pick_strategy 时，落库的必须是 'fifo' 而不是 NULL。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            repo = MaterialRepository(s)
            repo.set_tenant_id("t")
            mid = await repo.create({
                "tenant_id": "t", "code": "RM-2", "name": "原料二", "unit": "PCS"})
            row = await repo.get(mid)
            assert row["pick_strategy"] == "fifo", (
                f"默认拣选策略没落库（pick_strategy={row['pick_strategy']!r}）—— "
                "NULL 会被拣选逻辑判成非 fifo 而走 LIFO")
    finally:
        await engine.dispose()


async def test_create_material_keeps_explicit_strategy():
    """显式给的策略不能被默认值覆盖。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            repo = MaterialRepository(s)
            repo.set_tenant_id("t")
            mid = await repo.create({
                "tenant_id": "t", "code": "RM-3", "name": "原料三", "unit": "PCS",
                "pick_strategy": "lifo"})
            assert (await repo.get(mid))["pick_strategy"] == "lifo"
    finally:
        await engine.dispose()


# ==================== 2. 消费侧：NULL 不得反转拣选方向 ====================

async def test_null_pick_strategy_still_picks_oldest_batch():
    """★核心：物料策略为 NULL 时必须按 FIFO 出最老的批次，不能反成 LIFO。

    此处 material.pick_strategy 就是 NULL（与库里 69 行同形态），
    若读侧用 `get("pick_strategy", "fifo")` 兜，会拿到 None → 走 DESC →
    出到 RM-NEW（最新批次），老货被无限期压库。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc = _svc(s)
            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            item = await IssueOrderItemRepository(s).get(1)
            assert item["batch_no"] == "RM-OLD", (
                f"拣选方向被反转：期望先出最老的 RM-OLD，实际出了 {item['batch_no']} "
                "（NULL 被当成非 fifo → LIFO，老货压库）")
    finally:
        await engine.dispose()


async def test_explicit_lifo_picks_newest_batch():
    """显式 lifo 仍然要生效 —— 修 NULL 不能把显式策略一起抹平。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            await s.execute(text("UPDATE materials SET pick_strategy='lifo' WHERE id=1"))
            await s.commit()
            svc = _svc(s)
            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            item = await IssueOrderItemRepository(s).get(1)
            assert item["batch_no"] == "RM-NEW", "显式 lifo 未生效"
    finally:
        await engine.dispose()


async def test_manual_strategy_requires_explicit_batch():
    engine, Session = await _session()
    try:
        async with Session() as s:
            await s.execute(text("UPDATE materials SET pick_strategy='manual' WHERE id=1"))
            await s.commit()
            svc = _svc(s)
            with pytest.raises(ValueError, match="manual"):
                await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
    finally:
        await engine.dispose()
