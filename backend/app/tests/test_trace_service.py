"""批次追溯（台账 C-35）。

客诉电话进来问三件事：这批货用了什么料、同批还有多少、影响面多大。
改造前一件都答不上来，而且不是"查得慢"，是**根本没有数据**：

- 完工入库的明细从来没写 ``batch_no`` → 成品在系统里没有批号；
- 领料单只有 ``source_doc_no`` 字符串挂工单号，没有 ``work_order_id``。

本文件锁住追溯的两个方向与两条兜底：

1. 反向：成品批 → 产出工单 → 该工单投入的原料批；
2. 正向：原料批 → 领用它的工单 → 该工单产出的成品批；
3. **弱关联兜底**：历史单据 ``work_order_id IS NULL`` 时仍按 ``source_doc_no``
   追得下去（老数据不能因为没回填就断链）；
4. 批次实体不存在时不报错、不 404，而是按批号字符串匹配并给出 ``warning``；
5. ``depth`` 必须真的截断，否则返工/委外形成的环会把查询打穿。

真实链路见 ``e2e/batch_trace_e2e.py``（T1–T11，23 段全通）。
"""
import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import StaticPool

from app.repositories.wms_repo import BatchRepository
from app.services.trace_service import TraceService

TABLES = [
    "CREATE TABLE materials (id INTEGER PRIMARY KEY, tenant_id TEXT, code TEXT,"
    " name TEXT, spec TEXT, unit TEXT)",
    "CREATE TABLE batches (id INTEGER PRIMARY KEY, tenant_id TEXT, batch_no TEXT,"
    " material_id INTEGER, is_locked BOOLEAN DEFAULT 0, status TEXT)",
    "CREATE TABLE work_orders (id INTEGER PRIMARY KEY, tenant_id TEXT, wo_no TEXT,"
    " product_code TEXT, product_name TEXT, wo_status TEXT, planned_qty INTEGER,"
    " completed_qty INTEGER, org_id INTEGER)",
    "CREATE TABLE issue_orders (id INTEGER PRIMARY KEY, tenant_id TEXT, issue_no TEXT,"
    " issue_type TEXT, status TEXT, source_type TEXT, source_doc_no TEXT,"
    " work_order_id INTEGER, created_at TEXT)",
    "CREATE TABLE issue_order_items (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " issue_id INTEGER, batch_no TEXT, material_id INTEGER, issued_qty NUMERIC,"
    " required_qty NUMERIC)",
    "CREATE TABLE receipt_orders (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " receipt_no TEXT, receipt_type TEXT, status TEXT, source_type TEXT,"
    " source_doc_no TEXT, work_order_id INTEGER, created_at TEXT)",
    "CREATE TABLE receipt_order_items (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " receipt_id INTEGER, batch_no TEXT, material_id INTEGER, received_qty NUMERIC,"
    " expected_qty NUMERIC)",
    "CREATE TABLE warehouses (id INTEGER PRIMARY KEY, tenant_id TEXT, name TEXT)",
    "CREATE TABLE inventory (id INTEGER PRIMARY KEY, tenant_id TEXT,"
    " material_id INTEGER, warehouse_id INTEGER, location_id INTEGER,"
    " batch_id INTEGER, batch_no TEXT, quantity NUMERIC, locked_qty NUMERIC, unit TEXT)",
]


@pytest.fixture
async def svc():
    engine = create_async_engine(
        "sqlite+aiosqlite://", poolclass=StaticPool,
        connect_args={"check_same_thread": False})
    async with engine.begin() as conn:
        for ddl in TABLES:
            await conn.execute(text(ddl))

        await conn.execute(text(
            "INSERT INTO materials (id, tenant_id, code, name, unit) VALUES "
            "(1, 't', 'RM-1', '原料一', 'PCS'), (2, 't', 'FG-1', '成品一', 'PCS')"))
        await conn.execute(text(
            "INSERT INTO batches (id, tenant_id, batch_no, material_id, is_locked) VALUES "
            "(10, 't', 'RM-A', 1, 0), (20, 't', 'WO-1', 2, 0)"))
        await conn.execute(text(
            "INSERT INTO work_orders (id, tenant_id, wo_no, product_code, wo_status) VALUES "
            "(1, 't', 'WO-1', 'FG-1', 'closed'), (2, 't', 'WO-2', 'FG-1', 'closed')"))
        # 工单 1 领料（带 work_order_id）→ 出库单 1
        await conn.execute(text(
            "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, source_type,"
            " source_doc_no, work_order_id) VALUES "
            "(1, 't', 'ISO-1', 'production', 'wo', 'WO-1', 1)"))
        await conn.execute(text(
            "INSERT INTO issue_order_items (id, tenant_id, issue_id, batch_no,"
            " material_id, issued_qty) VALUES (1, 't', 1, 'RM-A', 1, 10)"))
        # 工单 1 完工入库 → 成品批次 WO-1
        await conn.execute(text(
            "INSERT INTO receipt_orders (id, tenant_id, receipt_no, receipt_type,"
            " source_type, source_doc_no, work_order_id) VALUES "
            "(1, 't', 'PRD-1', 'production', 'production', 'WO-1', 1)"))
        await conn.execute(text(
            "INSERT INTO receipt_order_items (id, tenant_id, receipt_id, batch_no,"
            " material_id, received_qty) VALUES (1, 't', 1, 'WO-1', 2, 10)"))
        await conn.execute(text(
            "INSERT INTO warehouses (id, tenant_id, name) VALUES (3, 't', '成品库')"))
        await conn.execute(text(
            "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id,"
            " batch_id, batch_no, quantity, locked_qty, unit) VALUES "
            "(1, 't', 2, 3, 20, 'WO-1', 10, 0, 'PCS')"))

    Session = async_sessionmaker(engine, expire_on_commit=False)
    async with Session() as s:
        repo = BatchRepository(s)
        repo.set_tenant_id("t")
        yield TraceService(repo)
    await engine.dispose()


# ============================================================
# 双向追溯
# ============================================================

async def test_backward_from_finished_batch(svc):
    """成品批 → 产出工单 → 该工单投入的原料批。"""
    res = await svc.backward("WO-1")
    wos = [x["work_order"] for x in res["origin_work_orders"] if x.get("work_order")]
    assert [w["id"] for w in wos] == [1]
    assert [b["batch_no"] for b in res["source_batches"]] == ["RM-A"]


async def test_forward_from_raw_batch(svc):
    """原料批 → 领用工单 → 产出的成品批（召回要锁的对象）。"""
    res = await svc.forward("RM-A")
    wos = [x["work_order"] for x in res["affected_work_orders"]]
    assert [w["id"] for w in wos] == [1]
    assert [b["batch_no"] for b in res["output_batches"]] == ["WO-1"]
    assert res["issue_orders"][0]["issue_no"] == "ISO-1"


async def test_trace_both_directions_and_summary(svc):
    res = await svc.trace("WO-1")
    assert res["batch_found"] is True
    assert res["material"]["code"] == "FG-1"
    assert res["summary"]["source_batch_count"] == 1
    assert res["stock"]["on_hand"] == 10


# ============================================================
# 兜底：老数据弱关联
# ============================================================

async def test_legacy_issue_without_work_order_id_still_traces(svc):
    """历史领料单没回填 ``work_order_id`` 时，按 ``source_doc_no`` 仍能追到工单。

    不能因为"老数据没回填"就让质量部门查不下去 —— 那等于追溯功能只对新单生效。
    """
    await svc.repo.execute(
        "UPDATE issue_orders SET work_order_id = NULL WHERE id = 1")
    res = await svc.forward("RM-A")
    wos = [x["work_order"]["id"] for x in res["affected_work_orders"]]
    assert wos == [1], "弱关联兜底失效：工单号字符串匹配没生效"
    assert [b["batch_no"] for b in res["output_batches"]] == ["WO-1"]


async def test_unknown_batch_returns_warning_not_error(svc):
    res = await svc.trace("NO-SUCH")
    assert res["batch_found"] is False
    assert "warning" in res
    assert res["summary"]["output_batch_count"] == 0


# ============================================================
# 深度截断
# ============================================================

async def test_depth_limits_expansion(svc):
    """``depth=1`` 只展开一层：原料批 → 工单 1 的成品批，不再往下追。"""
    # 让成品批 WO-1 作为原料被工单 2 领用，形成第二层
    await svc.repo.execute(
        "INSERT INTO issue_orders (id, tenant_id, issue_no, issue_type, source_type,"
        " source_doc_no, work_order_id) VALUES (2, 't', 'ISO-2', 'production', 'wo', 'WO-2', 2)")
    await svc.repo.execute(
        "INSERT INTO issue_order_items (id, tenant_id, issue_id, batch_no,"
        " material_id, issued_qty) VALUES (2, 't', 2, 'WO-1', 2, 5)")
    await svc.repo.execute(
        "INSERT INTO receipt_orders (id, tenant_id, receipt_no, receipt_type,"
        " source_type, source_doc_no, work_order_id) VALUES "
        "(2, 't', 'PRD-2', 'production', 'production', 'WO-2', 2)")
    await svc.repo.execute(
        "INSERT INTO receipt_order_items (id, tenant_id, receipt_id, batch_no,"
        " material_id, received_qty) VALUES (2, 't', 2, 'WO-2', 2, 5)")

    one = await svc.forward("RM-A", depth=1)
    assert {b["batch_no"] for b in one["output_batches"]} == {"WO-1"}
    two = await svc.forward("RM-A", depth=2)
    assert {b["batch_no"] for b in two["output_batches"]} == {"WO-1", "WO-2"}


# ============================================================
# C-36：按批次出库不能取到 0 数量行
# ============================================================

async def test_find_batch_rows_skips_empty_rows(svc):
    """同一批次散在多条库位行时，只能返回真正有货的那些。

    ``find_one(batch_id=...)`` 不排序，取到的常常是待检区那条 0 行 →
    明明有货却报"可用库存不足：现有 0.0"（台账 C-36）。
    """
    from app.repositories.wms_repo import InventoryRepository

    inv_repo = InventoryRepository(svc.repo._session)
    inv_repo.set_tenant_id("t")
    await inv_repo.execute(
        "INSERT INTO inventory (id, tenant_id, material_id, warehouse_id,"
        " batch_id, batch_no, quantity, locked_qty, unit) VALUES "
        "(2, 't', 2, 3, 20, 'WO-1', 0, 0, 'PCS')")
    rows = await inv_repo.find_batch_rows(2, 3, 20)
    assert [r["id"] for r in rows] == [1], f"应只返回有货的行，实际 {[r['id'] for r in rows]}"
