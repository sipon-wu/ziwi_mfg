"""E-E3 红冲回滚必须"从哪扣的回哪去"（台账 C-59）。

真实 HTTP 复核时撞出来的**极隐蔽**缺陷：

    过账扣减行：id=92（库位 28、批次 70） 87 → 82
    红冲加回行：id=122（库位 28、**无批次**） 10 → 15

总数完全对得上（1335 → 1330 → 1335），接口返回 ``reversed_qty=5.0`` 也"成功"了 ——
但**货没回到原批次**。批次 70 少的 5 个没回来，凭空多出一坨无批次的"幽灵库存"。
对要做批次追溯的物料，等于把追溯链冲断：这批货到底在哪个批次、还剩多少，
从此查不准。

根因是 ``stock_in`` 内部用 ``find_one(..., batch_id=None)`` 定位，而 ``find_one``
在不传 ``batch_id`` 时会追加 ``batch_id IS NULL`` —— 带批次的库存行**永远匹配不到**，
于是回滚落到那条无批次的残留行上。

**同一陷阱已踩三次**：C-52 移位（带批次的货移不动）、C-56 盘点调整（盘亏静默跳过）、
本条红冲（回滚落错行）。前两次都是"功能不生效"，这次更糟 ——
**功能"生效"了，只是加错了地方，所以没有任何报错**。

修：新增 ``_resolve_rollback_row``（优先同批次、其次同库位可用量最大，刻意绕开
``find_one``）+ ``InventoryRepository.add_quantity``（按 id 增量，不再靠重新定位）。
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.production import WorkOrder
from app.models.sync import ChangeLog
from app.models.wms import (
    Batch, Inventory, InventoryTransaction, IssueOrder, IssueOrderItem,
    Material, ReceiptOrder, ReceiptOrderItem, Warehouse,
)
from app.repositories.wms_repo import (
    InventoryRepository, InventoryTransactionRepository, IssueOrderItemRepository,
    IssueOrderRepository,
)
from app.services.wms_service import IssueOrderService

TABLES = [
    Warehouse.__table__, Material.__table__, Batch.__table__, Inventory.__table__,
    InventoryTransaction.__table__, IssueOrder.__table__, IssueOrderItem.__table__,
    ReceiptOrder.__table__, ReceiptOrderItem.__table__, WorkOrder.__table__,
    ChangeLog.__table__,
]

# 三行库存，故意造出"带批次 + 无批次残留"共存的局面（真实库里就是这样）：
#   id=1 库位 901 批次 10（RM-OLD）→ 可用 100，自动拣选会先扣它
#   id=2 库位 901 **无批次残留行**   → 可用 10，红冲若走 find_one 就会加到这里
#   id=3 库位 902 批次 11（RM-NEW）  → 可用 100
SEED = [
    "INSERT INTO warehouses (id, tenant_id, code, name, type) "
    "VALUES (1, 't', 'WH-RAW', '原料仓', 'raw')",
    "INSERT INTO materials (id, tenant_id, code, name, unit, pick_strategy) "
    "VALUES (1, 't', 'RM-1', '原料一', 'PCS', 'fifo')",
    "INSERT INTO batches (id, tenant_id, batch_no, material_id, is_locked, status,"
    " created_at) VALUES "
    "(10, 't', 'RM-OLD', 1, 0, 'active', '2026-01-01 00:00:00'), "
    "(11, 't', 'RM-NEW', 1, 0, 'active', '2026-06-01 00:00:00')",
    "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id, location_id,"
    " batch_id, batch_no, quantity, locked_qty, unit) VALUES "
    "(1, 't', 1, 1, 901, 10, 'RM-OLD', 100, 0, 'PCS'), "
    "(2, 't', 1, 1, 901, NULL, NULL, 10, 0, 'PCS'), "
    "(3, 't', 1, 1, 902, 11, 'RM-NEW', 100, 0, 'PCS')",
    "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, source_type,"
    " source_doc_no, work_order_id, warehouse_id, status, issued_qty) VALUES "
    "(1, 't', 'ISO-1', 'production', 'wo', 'WO-1', 1, 1, 'pending', 0)",
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
        r(InventoryRepository), r(InventoryTransactionRepository)), r(InventoryRepository)


async def _qtys(inv_repo):
    rows = await inv_repo.query("SELECT id, batch_id, quantity FROM inventory ORDER BY id")
    return {r["id"]: r for r in rows}


# ==================== 1. 核心：回滚不得落到别的批次行 ====================

async def test_rollback_returns_to_the_same_batch_row():
    """★红冲必须回到**被扣的那一行**，不能落到无批次的残留行上。

    总数对得上不等于对：批次账会被冲乱，追溯链从此查不准。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, inv_repo = _svc(s)
            before = await _qtys(inv_repo)

            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            mid = await _qtys(inv_repo)
            deducted = [k for k in before
                        if abs(before[k]["quantity"] - mid[k]["quantity"]) > 1e-9]
            assert deducted == [1], (
                f"预期扣批次 10 那行（id=1），实际扣了 {deducted} "
                "—— 用例前提不成立，后面验的就不是同一件事")

            res = await svc.cancel_issue_order(1, "复核", "t", created_by=1)
            assert res["reversed_qty"] == 10

            after = await _qtys(inv_repo)
            added = [k for k in mid
                     if abs(mid[k]["quantity"] - after[k]["quantity"]) > 1e-9]
            assert added == [1], (
                f"红冲把货加回了 {added}（期望 id=1）：落到别的行会让批次账错乱 —— "
                "总数看着没变，实际原批次少的货没回来、凭空多出无批次库存")
            assert abs(after[1]["quantity"] - before[1]["quantity"]) < 1e-9
            # 无批次残留行必须原地不动
            assert abs(after[2]["quantity"] - before[2]["quantity"]) < 1e-9
    finally:
        await engine.dispose()


async def test_rollback_restores_exact_original_state():
    """红冲后整张库存表必须逐行回到过账前（不只是总数对）。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, inv_repo = _svc(s)
            before = await _qtys(inv_repo)
            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            await svc.cancel_issue_order(1, "复核", "t", created_by=1)
            after = await _qtys(inv_repo)
            for k in before:
                assert abs(after[k]["quantity"] - before[k]["quantity"]) < 1e-9, (
                    f"库存行 {k} 未回到原值：{before[k]['quantity']} → "
                    f"{after[k]['quantity']}")
    finally:
        await engine.dispose()


# ==================== 2. 无批次场景仍要能回滚 ====================

async def test_rollback_works_for_non_batch_stock():
    """物料没有批次时（全是 batch_id NULL 的行）回滚照常生效。"""
    engine, Session = await _session()
    try:
        async with Session() as s:
            await s.execute(text("DELETE FROM inventory"))
            await s.execute(text(
                "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id,"
                " location_id, batch_id, batch_no, quantity, locked_qty, unit) VALUES "
                "(9, 't', 1, 1, 901, NULL, NULL, 50, 0, 'PCS')"))
            await s.commit()
            svc, inv_repo = _svc(s)
            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            assert abs((await _qtys(inv_repo))[9]["quantity"] - 40) < 1e-9
            await svc.cancel_issue_order(1, "复核", "t", created_by=1)
            assert abs((await _qtys(inv_repo))[9]["quantity"] - 50) < 1e-9
    finally:
        await engine.dispose()


# ==================== 4. 同批号多行（幽灵行）不得抢走回滚量 ====================

async def test_rollback_ignores_ghost_row_with_same_batch_no():
    """★同一 ``batch_no`` 挂在两行上时，红冲必须按 ``batch_id`` 定位。

    真实库里的形态（material 59，仓库 5，库位 28）：

        id=92   batch_id=70   batch_no=B-1031195744   qty 21   ← 真实批次行
        id=122  batch_id=NULL batch_no=B-1031195744   qty 246  ← 历史幽灵行

    出库流水改造前写死 ``batch_id=None``，红冲只能按批号文字匹配；而候选池
    按"可用量最大优先"排序，幽灵行余额更大 → 货还进了幽灵行，真实行永远少 5。
    总数、接口返回值全对，只有批次账/库位账错 —— **没有任何报错**。

    修法两层：①出库流水记库存行自己的 ``batch_id``；②回滚先按
    ``(库位, batch_id)`` 精确命中，批号文字只作历史流水的兜底。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            # 幽灵行：同批号、无 batch_id、余额远大于真实行
            await s.execute(text(
                "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id,"
                " location_id, batch_id, batch_no, quantity, locked_qty, unit) VALUES "
                "(4, 't', 1, 1, 901, NULL, 'RM-OLD', 500, 0, 'PCS')"))
            await s.commit()
            svc, inv_repo = _svc(s)
            before = await _qtys(inv_repo)

            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            assert abs((await _qtys(inv_repo))[1]["quantity"] - 90) < 1e-9, (
                "用例前提不成立：自动拣选应先扣真实批次行 id=1")

            # 流水的 batch_id 必须落下来，否则下一次红冲照样只能比批号文字
            txs = await inv_repo.query(
                "SELECT batch_id, batch_no FROM inventory_transactions "
                "WHERE transaction_type = 'issue'")
            assert txs and txs[0]["batch_id"] == 10, (
                f"出库流水未记 batch_id（实际 {txs[0] if txs else None}）——"
                "红冲将无法区分同批号的多行库存")

            await svc.cancel_issue_order(1, "复核", "t", created_by=1)
            after = await _qtys(inv_repo)
            assert abs(after[1]["quantity"] - before[1]["quantity"]) < 1e-9, (
                f"真实批次行未回位：{before[1]['quantity']} → {after[1]['quantity']}")
            assert abs(after[4]["quantity"] - 500) < 1e-9, (
                f"货被加进了同批号的幽灵行：500 → {after[4]['quantity']}")
    finally:
        await engine.dispose()


async def test_rollback_prefers_registered_batch_row_for_legacy_leg():
    """历史流水没记 ``batch_id`` 时（改造前出的库），回滚仍要优先还回已登记批次行。

    老单据只能靠批号文字匹配，此时同批号多行的取舍必须站到"真实批次行"这边：
    把货还进 ``batch_id IS NULL`` 的幽灵行，等于把追溯链彻底断掉。
    """
    engine, Session = await _session()
    try:
        async with Session() as s:
            await s.execute(text(
                "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id,"
                " location_id, batch_id, batch_no, quantity, locked_qty, unit) VALUES "
                "(4, 't', 1, 1, 901, NULL, 'RM-OLD', 500, 0, 'PCS')"))
            await s.commit()
            svc, inv_repo = _svc(s)
            row = await svc._resolve_rollback_row(1, 1, 901, "RM-OLD", None)
            assert row and row["id"] == 1, (
                f"历史流水兜底落到了 {row and row['id']} 行（期望 id=1 的真实批次行）")
    finally:
        await engine.dispose()


# ==================== 3. 未过账的红冲不该动库存 ====================

async def test_cancel_pending_order_does_not_touch_inventory():
    engine, Session = await _session()
    try:
        async with Session() as s:
            svc, inv_repo = _svc(s)
            before = await _qtys(inv_repo)
            res = await svc.cancel_issue_order(1, "未过账就取消", "t", created_by=1)
            assert res["reversed_qty"] == 0
            after = await _qtys(inv_repo)
            for k in before:
                assert abs(after[k]["quantity"] - before[k]["quantity"]) < 1e-9
    finally:
        await engine.dispose()
