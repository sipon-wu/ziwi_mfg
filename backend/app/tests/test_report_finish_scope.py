"""报表口径与作废单据的三个回归锚点（2026-11-05 全流程串跑发现）。

三个缺陷的共同点：**单工序、单批量、不取消的探针永远测不出来**。

1. **生产日报把工序产出当产量累加**。``SUM(work_reports.output_qty)`` 对着一张
   14 道工序的工单会把 30 件算成 410 —— B-1 只修了 ``work_orders.completed_qty``
   （只认末道工序），报表侧没跟着改，于是"工单详情说 29、日报说 410"。
   现在 ``total_output`` 是完工口径，``wip_output`` 是工序流转量，两个都在。

2. **作废的领料单仍被批次追溯当作已领料**。红冲只把库存还回去，不会删原始
   ``issue`` 流水；明细 ``issued_qty`` 也没清零 → 同一批半成品在
   ``source_batches`` 里出现两次、用量翻倍。

3. **报工列表不返回投入数**。``list_reports`` 的 SELECT 漏了 ``input_qty`` /
   ``machine_hours``（``get_report`` 的 ``SELECT wr.*`` 有）→ 列表页看不到工序
   投入，良率算不出来。
"""
from datetime import date

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.repositories.production_repo import ProductionRepository
from app.repositories.wms_repo import (
    InventoryRepository,
    InventoryTransactionRepository,
    IssueOrderItemRepository,
    IssueOrderRepository,
)
from app.services.trace_service import TraceService
from app.services.wms_service import IssueOrderService

TABLES = [
    "CREATE TABLE operations (id INTEGER PRIMARY KEY, tenant_id TEXT, code TEXT, name TEXT)",
    "CREATE TABLE route_steps (id INTEGER PRIMARY KEY, tenant_id TEXT, route_id INTEGER,"
    " operation_id INTEGER, step_seq INTEGER)",
    "CREATE TABLE work_orders (id INTEGER PRIMARY KEY, tenant_id TEXT, wo_no TEXT,"
    " product_name TEXT, route_id INTEGER, wo_status TEXT, planned_qty INTEGER,"
    " completed_qty INTEGER, org_id INTEGER, product_code TEXT)",
    "CREATE TABLE work_reports (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " work_order_id INTEGER, report_date DATE, reporter_id INTEGER, org_id INTEGER,"
    " operation_code TEXT, operation_name TEXT, input_qty INTEGER, output_qty INTEGER,"
    " scrap_qty INTEGER, defect_reason TEXT, labor_hours NUMERIC, machine_hours NUMERIC,"
    " status TEXT, created_at TEXT, reported_at TEXT)",
    "CREATE TABLE issue_orders (id INTEGER PRIMARY KEY, tenant_id TEXT, issue_no TEXT,"
    " issue_type TEXT, status TEXT, source_type TEXT, source_doc_no TEXT,"
    " work_order_id INTEGER, warehouse_id INTEGER, created_at TEXT)",
    "CREATE TABLE issue_order_items (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " issue_id INTEGER, line_no INTEGER, batch_no TEXT, material_id INTEGER,"
    " issued_qty NUMERIC, required_qty NUMERIC, pick_status TEXT, unit TEXT)",
    "CREATE TABLE inventory (id INTEGER PRIMARY KEY, tenant_id TEXT, material_id INTEGER,"
    " warehouse_id INTEGER, location_id INTEGER, batch_id INTEGER, batch_no TEXT,"
    " quantity NUMERIC, locked_qty NUMERIC, unit TEXT, last_transaction_at TEXT)",
    "CREATE TABLE inventory_transactions (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " transaction_type TEXT, voucher_no TEXT, material_id INTEGER, warehouse_id INTEGER,"
    " from_location_id INTEGER, to_location_id INTEGER, batch_id INTEGER, batch_no TEXT,"
    " quantity NUMERIC, reference_type TEXT, reference_id INTEGER, unit TEXT,"
    " created_at TEXT, source_type TEXT, source_doc_no TEXT, remark TEXT,"
    " created_by INTEGER, unit_price NUMERIC)",
    "CREATE TABLE materials (id INTEGER PRIMARY KEY, tenant_id TEXT, code TEXT,"
    " name TEXT, spec TEXT, unit TEXT)",
    "CREATE TABLE batches (id INTEGER PRIMARY KEY, tenant_id TEXT, batch_no TEXT,"
    " material_id INTEGER, is_locked BOOLEAN DEFAULT 0, status TEXT)",
    "CREATE TABLE receipt_orders (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " receipt_no TEXT, receipt_type TEXT, status TEXT, source_type TEXT,"
    " source_doc_no TEXT, work_order_id INTEGER, created_at TEXT)",
    "CREATE TABLE receipt_order_items (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " receipt_id INTEGER, batch_no TEXT, material_id INTEGER, received_qty NUMERIC,"
    " expected_qty NUMERIC)",
    "CREATE TABLE warehouses (id INTEGER PRIMARY KEY, tenant_id TEXT, name TEXT)",
]


async def _mk_engine():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        for ddl in TABLES:
            await conn.execute(text(ddl))
    return engine


@pytest.fixture
async def prod_repo():
    """两张工单：一张 3 道工序（末道 OP30），一张无路线（单工序老单）。"""
    engine = await _mk_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO operations (id, tenant_id, code, name) VALUES "
            "(1, 't', 'OP10', '下料'), (2, 't', 'OP20', '装配'), (3, 't', 'OP30', '终检')"))
        await conn.execute(text(
            "INSERT INTO route_steps (id, tenant_id, route_id, operation_id, step_seq) VALUES "
            "(1, 't', 7, 1, 1), (2, 't', 7, 2, 2), (3, 't', 7, 3, 3)"))
        await conn.execute(text(
            "INSERT INTO work_orders (id, tenant_id, wo_no, product_name, route_id) VALUES "
            "(1, 't', 'WO-A', '定子总成', 7), (2, 't', 'WO-B', '老单无路线', NULL)"))
        # 多工序工单：每道各报 30 件（真实车间就是这么报的）
        rows = [(1, 1, 'OP10', '下料', 30, 30, 0), (2, 1, 'OP20', '装配', 30, 30, 0),
                (3, 1, 'OP30', '终检', 30, 30, 0)]
        # 无路线老单：一条"报整单"，没有工序码
        rows.append((4, 2, None, None, 12, 12, 1))
        def q(v):
            return "NULL" if v is None else "'" + str(v) + "'"

        for rid, wo, op, name, inp, out, scrap in rows:
            await conn.execute(text(
                "INSERT INTO work_reports (id, tenant_id, work_order_id, report_date,"
                " operation_code, operation_name, input_qty, output_qty, scrap_qty,"
                " labor_hours, machine_hours, status) VALUES "
                f"({rid}, 't', {wo}, '2026-11-05', {q(op)}, {q(name)},"
                f" {inp}, {out}, {scrap}, 1.5, 1.5, 'submitted')"))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        repo = ProductionRepository(s)
        repo.set_tenant_id("t")
        yield repo
    await engine.dispose()


# ============================================================
# 1. 日报 / 月报的完工口径
# ============================================================
async def test_daily_report_counts_finish_op_only(prod_repo):
    """3 道工序各报 30 件 → 完工 30，工序流转量 90。

    改造前 ``total_output`` 会是 90，一张 30 件的工单在日报里变成 90 件。
    """
    rows = await prod_repo.daily_report(date(2026, 11, 5))
    by_no = {r["wo_no"]: r for r in rows}
    a = by_no["WO-A"]
    assert a["total_output"] == 30, "完工口径只认末道工序 OP30"
    assert a["wip_output"] == 90, "工序流转量保留全工序累计"


async def test_daily_report_keeps_routerless_order_working(prod_repo):
    """无路线的老单（报整单、无工序码）仍按完工计，不能因为新口径变成 0。"""
    rows = await prod_repo.daily_report(date(2026, 11, 5))
    b = {r["wo_no"]: r for r in rows}["WO-B"]
    assert b["total_output"] == 12
    assert b["wip_output"] == 12


async def test_monthly_report_uses_same_scope(prod_repo):
    rows = await prod_repo.monthly_report(2026, 11)
    assert len(rows) == 1
    m = rows[0]
    # 30（WO-A 完工）+ 12（WO-B 无路线）= 42；不是 90 + 12 = 102
    assert m["total_output"] == 42
    assert m["wip_output"] == 102
    assert m["order_count"] == 2


# ============================================================
# 2. 作废领料单：明细清零 + 追溯排除
# ============================================================
@pytest.fixture
async def wms_repos():
    """已过账的领料单：明细 issued_qty=15.15，库存已扣、流水已落。"""
    engine = await _mk_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO warehouses (id, tenant_id, name) VALUES (1, 't', '成品库')"))
        await conn.execute(text(
            "INSERT INTO materials (id, tenant_id, code, name, unit) VALUES "
            "(20, 't', 'SP-AH-ROTOR', '转子总成', '件')"))
        await conn.execute(text(
            "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, status,"
            " source_type, source_doc_no, work_order_id, warehouse_id) VALUES "
            "(1, 't', 'ISS-1', 'production', 'issued', 'production', 'WO-1', 1, 1)"))
        await conn.execute(text(
            "INSERT INTO issue_order_items (id, tenant_id, issue_id, line_no, batch_no,"
            " material_id, issued_qty, required_qty, pick_status, unit) VALUES "
            "(1, 't', 1, 1, 'B-ROTOR', 20, 15.15, 15.15, 'picked', '件')"))
        # 已出库：库存行被扣空，流水留了一条 issue 腿（红冲要照它逐腿还回去）
        await conn.execute(text(
            "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id, location_id,"
            " batch_id, batch_no, quantity, locked_qty, unit) VALUES "
            "(1, 't', 20, 1, 5, 20, 'B-ROTOR', 0, 0, '件')"))
        await conn.execute(text(
            "INSERT INTO inventory_transactions (id, tenant_id, transaction_type,"
            " voucher_no, material_id, warehouse_id, from_location_id, batch_id, batch_no,"
            " quantity, reference_type, reference_id, unit, created_at) VALUES "
            "(1, 't', 'issue', 'ISS-1', 20, 1, 5, 20, 'B-ROTOR', -15.15,"
            " 'issue_order', 1, '件', '2026-11-05 09:00:00')"))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        yield {
            "repo": IssueOrderRepository(s),
            "item": IssueOrderItemRepository(s),
            "inv": InventoryRepository(s),
            "tx": InventoryTransactionRepository(s),
            "session": s,
        }
    await engine.dispose()


async def test_cancel_clears_issued_qty(wms_repos):
    """作废后明细 ``issued_qty`` 必须归零 —— 否则"还欠多少料"永远是 15.15，
    追溯也会把这张废单当成真的领过料。"""
    for r in (wms_repos["repo"], wms_repos["item"]):
        r.set_tenant_id("t")
    wms_repos["inv"].set_tenant_id("t")
    wms_repos["tx"].set_tenant_id("t")
    svc = IssueOrderService(wms_repos["repo"], wms_repos["item"],
                            wms_repos["inv"], wms_repos["tx"])
    await svc.cancel_issue_order(1, "建错单", "t")
    items = await wms_repos["item"].list_by_issue(1)
    assert [float(i["issued_qty"] or 0) for i in items] == [0.0]
    order = await wms_repos["repo"].get(1)
    assert order["status"] == "cancelled"


async def test_trace_ignores_cancelled_issue(prod_repo):
    """作废单不得成为"这批料的去向"。

    正向追溯里 ``_consumers`` 若不过滤 cancelled，一张废单会凭空变出一个
    受影响工单；反向追溯则让 ``source_batches`` 里同一批料出现两次。
    """
    engine = await _mk_engine()
    async with engine.begin() as conn:
        await conn.execute(text(
            "INSERT INTO materials (id, tenant_id, code, name, unit) VALUES "
            "(1, 't', 'RM-1', '原料一', 'PCS')"))
        await conn.execute(text(
            "INSERT INTO batches (id, tenant_id, batch_no, material_id) VALUES "
            "(10, 't', 'RM-A', 1)"))
        await conn.execute(text(
            "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, status,"
            " source_type, work_order_id) VALUES "
            "(1, 't', 'ISS-OK', 'production', 'issued', 'production', 1)"))
        await conn.execute(text(
            "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, status,"
            " source_type, work_order_id) VALUES "
            "(2, 't', 'ISS-VOID', 'production', 'cancelled', 'production', 1)"))
        await conn.execute(text(
            "INSERT INTO issue_order_items (id, tenant_id, issue_id, batch_no,"
            " material_id, issued_qty) VALUES "
            "(1, 't', 1, 'RM-A', 1, 5), (2, 't', 2, 'RM-A', 1, 5)"))
    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        from app.repositories.wms_repo import BatchRepository
        repo = BatchRepository(s)
        repo.set_tenant_id("t")
        svc = TraceService(repo)
        res = await svc.forward("RM-A")
    await engine.dispose()
    nos = [x["issue_no"] for x in res["issue_orders"]]
    assert nos == ["ISS-OK"], f"作废单不该出现：{nos}"


# ============================================================
# 3. 报工列表要带投入数与机时
# ============================================================
async def test_list_reports_exposes_input_and_machine_hours(prod_repo):
    data = await prod_repo.list_reports(1, 20, work_order_id=1)
    row = data["items"][0]
    assert "input_qty" in row, "列表页看不到工序投入 → 算不出良率"
    assert "machine_hours" in row
    assert row["input_qty"] == 30
    assert float(row["machine_hours"]) == 1.5
