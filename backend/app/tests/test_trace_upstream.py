"""「工单 → 原料批」这条追溯边（场景清单 P2-2）。

改造前它**从来没通过**，而且是两个缺口叠加：

1. ``IssueOrderService.issue_item`` 过账只写 ``issued_qty`` / ``pick_status``，
   **从不回写 ``issue_order_items.batch_no``** —— 于是这一列在真实流程里永远是 NULL；
2. ``TraceService._wo_inputs`` 偏偏只认这一列。

净效果：追溯永远只能回答"这批货由哪张工单产出"，回答不了"它用了哪些原料"。
召回时锁得住成品，锁不住上游供应商批次 —— 而供应商批次恰恰是要去追的那一头。

既有 ``test_trace_service.py`` 之所以一直绿，是因为它在造数时**手工**往
``issue_order_items.batch_no`` 写了 `'RM-A'`，绕过了真实过账路径。
这正是"造数绕开缺陷"的典型：测试通过只证明 SQL 能跑，不证明链路能通。

本文件锁四件事：
1. 过账后单据行能拿到**实际出库批次**（单批次场景）；
2. 跨批次出库**不写**单据行（一列装不下多条，挑一条写进去反而误导）；
3. 追溯主口径读**库存流水**，单据行 batch_no 为 NULL 时也能展开上游；
4. 没有流水的老数据退回单据行弱关联，仍然查得到。
"""
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.core.database import Base
from app.models.production import WorkOrder
from app.models.wms import (
    Batch, Inventory, InventoryTransaction, IssueOrder, IssueOrderItem,
    Material, ReceiptOrder, ReceiptOrderItem, Warehouse)
from app.repositories.wms_repo import (
    InventoryRepository, InventoryTransactionRepository, IssueOrderItemRepository,
    IssueOrderRepository)
from app.services.trace_service import TraceService
from app.services.wms_service import IssueOrderService

TABLES = [
    Warehouse.__table__, Material.__table__, Batch.__table__, Inventory.__table__,
    InventoryTransaction.__table__, IssueOrder.__table__, IssueOrderItem.__table__,
    ReceiptOrder.__table__, ReceiptOrderItem.__table__, WorkOrder.__table__,
]

# 成品批 WO-1 ← 生产入库单 ← 工单 1：反向追溯的起点
PRODUCER_SQL = [
    "INSERT INTO receipt_orders (id, tenant_id, receipt_no, receipt_type, source_type,"
    " source_doc_no, work_order_id, warehouse_id, status) VALUES "
    "(1, 't', 'PRD-1', 'production', 'production', 'WO-1', 1, 1, 'pending')",
    "INSERT INTO receipt_order_items (id, tenant_id, receipt_id, line_no, material_id,"
    " expected_qty, received_qty, unit, batch_no) VALUES "
    "(1, 't', 1, 1, 2, 10, 10, 'PCS', 'WO-1')",
    "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, product_name, wo_status)"
    " VALUES (1, 't', 'WO-1', 'FG-1', '成品一', 'completed')",
]


def _seed_sql():
    """单据 + 批次 + 库存（不含流水，流水按用例各自插）。"""
    return [
        "INSERT INTO warehouses (id, tenant_id, code, name, type) "
        "VALUES (1, 't', 'WH-RAW', '原料仓', 'raw')",
        "INSERT INTO materials (id, tenant_id, code, name, unit, pick_strategy) "
        "VALUES (1, 't', 'RM-1', '原料一', 'PCS', 'fifo'), "
        "       (2, 't', 'FG-1', '成品一', 'PCS', 'fifo')",
        "INSERT INTO batches (id, tenant_id, batch_no, material_id, is_locked) VALUES "
        "(10, 't', 'RM-A', 1, 0), (11, 't', 'RM-B', 1, 0), (20, 't', 'WO-1', 2, 0)",
        "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id, location_id,"
        " batch_id, batch_no, quantity, locked_qty, unit) VALUES "
        "(1, 't', 1, 1, 901, 10, 'RM-A', 100, 0, 'PCS'), "
        "(2, 't', 1, 1, 902, 11, 'RM-B', 100, 0, 'PCS'), "
        "(3, 't', 2, 1, 901, 20, 'WO-1', 10, 0, 'PCS')",
    ]


async def _make_session(seed_extra=()):
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        await conn.run_sync(
            lambda c: Base.metadata.create_all(c, tables=TABLES, checkfirst=True))
        for ddl in [*_seed_sql(), *seed_extra]:
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


ISSUE_ORDER_SQL = (
    "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, source_type,"
    " source_doc_no, work_order_id, warehouse_id, status) VALUES "
    "(1, 't', 'ISO-1', 'production', 'wo', 'WO-1', 1, 1, 'pending')")
ISSUE_ITEM_SQL = (
    "INSERT INTO issue_order_items (id, tenant_id, issue_id, line_no, material_id,"
    " required_qty, issued_qty, unit) VALUES (1, 't', 1, 1, 1, 10, 0, 'PCS')")


# ==================== 1. 过账回写实际批次 ====================

async def test_issue_writes_back_actual_batch():
    """单批次出库 → 单据行 batch_no 必须是实际出的那一批。"""
    engine, Session = await _make_session([ISSUE_ORDER_SQL, ISSUE_ITEM_SQL])
    try:
        async with Session() as s:
            svc = _svc(s)
            await svc.issue_item(1, {"issued_qty": 10}, "t", created_by=1)
            item = await IssueOrderItemRepository(s).get(1)
            assert item["batch_no"] == "RM-A", "过账没回写实际批次，追溯上游永远断"
            assert item["issued_qty"] == 10
    finally:
        await engine.dispose()


async def test_issue_across_batches_does_not_fake_single_batch():
    """跨批次出库（4+2 出 6）→ 单据行**不写**批次。

    一列装不下两条。写"RM-A"会让追溯以为这批货全来自 A，
    漏掉真正用到的 B —— 那比留空更糟。多批次事实留在流水里。
    """
    engine, Session = await _make_session([
        ISSUE_ORDER_SQL, ISSUE_ITEM_SQL,
        # 两批各只有 4 → 出 6 必须跨批次
        "UPDATE inventory SET quantity = 4 WHERE id IN (1, 2)",
    ])
    try:
        async with Session() as s:
            svc = _svc(s)
            await svc.issue_item(1, {"issued_qty": 6}, "t", created_by=1)
            item = await IssueOrderItemRepository(s).get(1)
            assert item["batch_no"] is None, "跨批次时不该伪造单一批次"
            # 但流水必须两条、各带自己的批号
            rows = await InventoryTransactionRepository(s).query(
                "SELECT batch_no, quantity FROM inventory_transactions "
                "WHERE reference_type = 'issue_order' ORDER BY id")
            assert [r["batch_no"] for r in rows] == ["RM-A", "RM-B"]
            assert sum(abs(r["quantity"]) for r in rows) == 6
    finally:
        await engine.dispose()


# ==================== 2. 追溯读流水，不依赖单据行 ====================

REAL_PATH_SEED = [
    ISSUE_ORDER_SQL,
    # 真实过账后的老样子：单据行没有批次（改造前就是这样），批次只在流水里
    ISSUE_ITEM_SQL,
    "INSERT INTO inventory_transactions (id, tenant_id, transaction_type, voucher_no,"
    " material_id, warehouse_id, quantity, unit, batch_no, reference_type, reference_id)"
    " VALUES (1, 't', 'issue', 'ISO-1', 1, 1, -10, 'PCS', 'RM-A', 'issue_order', 1)",
    *PRODUCER_SQL,
]


async def test_backward_reads_transactions_even_if_item_batch_missing():
    """单据行 batch_no 为 NULL，但流水有批号 → 上游仍然展开。"""
    engine, Session = await _make_session(REAL_PATH_SEED)
    try:
        async with Session() as s:
            repo = IssueOrderRepository(s)
            repo.set_tenant_id("t")
            svc = TraceService(repo)
            res = await svc.backward("WO-1")
            wos = [x["work_order"] for x in res["origin_work_orders"] if x.get("work_order")]
            assert wos, "工单级反向链接都没建立（发货入库单造数缺失？）"
            assert [b["batch_no"] for b in res["source_batches"]] == ["RM-A"], (
                "上游原料批没展开 —— 追溯又只看单据行了")
    finally:
        await engine.dispose()


async def test_backward_falls_back_to_item_batch_for_legacy_rows():
    """没有流水的历史单据：退回单据行弱关联，不能因为升级就查不到了。"""
    engine, Session = await _make_session([
        ISSUE_ORDER_SQL,
        "INSERT INTO issue_order_items (id, tenant_id, issue_id, line_no, material_id,"
        " required_qty, issued_qty, unit, batch_no)"
        " VALUES (1, 't', 1, 1, 1, 10, 10, 'PCS', 'RM-B')",
        *PRODUCER_SQL,
    ])
    try:
        async with Session() as s:
            repo = IssueOrderRepository(s)
            repo.set_tenant_id("t")
            svc = TraceService(repo)
            res = await svc.backward("WO-1")
            assert [b["batch_no"] for b in res["source_batches"]] == ["RM-B"]
    finally:
        await engine.dispose()
